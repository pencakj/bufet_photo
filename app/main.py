"""Krkonoše Live v3 — camera-scoped archives and snapshots."""
from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

import imagestore
import localweather
import weather
from cameras import CAMERAS, DEFAULT_CAMERA, get_camera
from solar import TZ, is_daytime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

PORT = 8003


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = threading.Event()
    threading.Thread(target=imagestore.run_capture_loop, args=(stop,), daemon=True).start()
    threading.Thread(target=localweather.run_poll_loop, args=(stop,), daemon=True).start()
    await run_in_threadpool(imagestore.list_images, DEFAULT_CAMERA)
    # The release reads the production station; only production polls/writes it.
    if os.environ.get("WEATHER_POLL_ENABLED", "false").lower() == "true":
        threading.Thread(target=weather.run_poll_loop, daemon=True).start()
    logger.info("Background workers started")
    try:
        yield
    finally:
        stop.set()


app = FastAPI(title="Krkonoše Live", version="3.0.0-rc.3", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"is_daytime": is_daytime(), "cameras": CAMERAS},
    )


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


def image_path(directory: Path, filename: str) -> Path:
    """Allow only JPEG files inside the requested storage directory."""
    base = directory.resolve()
    path = (base / filename).resolve()
    if not path.is_relative_to(base) or path.suffix.lower() != ".jpg" or not path.is_file():
        raise HTTPException(404, "Image not found")
    return path


def valid_camera(camera_id: str):
    try:
        return get_camera(camera_id)
    except KeyError:
        raise HTTPException(404, "Unknown camera") from None


@app.get("/api/cameras")
def api_cameras():
    return {"cameras": [{**imagestore.camera_status(camera.id),
                         "weather": localweather.metadata(camera.id)} for camera in CAMERAS]}


@app.get("/api/images")
def api_images(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    order: Literal["asc", "desc"] = "desc",
    camera: str = DEFAULT_CAMERA,
):
    valid_camera(camera)
    images = imagestore.list_images(camera)
    if order.lower() == "asc":
        images = list(reversed(images))
    total = len(images)
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    page = images[offset : offset + limit]
    return {
        "images": page,
        "total": total,
        "today_count": sum(image["day"] == today for image in images),
        "camera": camera,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + limit) < total,
        "is_daytime": is_daytime(),
    }


@app.get("/api/generate-thumbnail/{filename:path}")
def api_generate_thumbnail(filename: str, camera: str = DEFAULT_CAMERA):
    source = valid_camera(camera)
    images, thumbs = imagestore.directories(camera)
    path = image_path(images, filename)
    if source.read_only and not (thumbs / f"thumb_{path.name}").is_file():
        raise HTTPException(404, "Thumbnail unavailable for read-only archive")
    thumb = imagestore.make_thumbnail(path, camera)
    if thumb is None:
        raise HTTPException(500, "Failed to create thumbnail")
    return {"success": True, "thumb_path": f"thumb_{filename}"}


@app.get("/images/{filename:path}")
def serve_image(filename: str, camera: str = DEFAULT_CAMERA):
    valid_camera(camera)
    images, _ = imagestore.directories(camera)
    path = image_path(images, filename)
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/thumbnails/{filename:path}")
def serve_thumb(filename: str, camera: str = DEFAULT_CAMERA):
    valid_camera(camera)
    _, thumbs = imagestore.directories(camera)
    path = image_path(thumbs, filename)
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000"},
    )


@app.get("/previews/{filename:path}")
def serve_preview(filename: str, camera: str = DEFAULT_CAMERA,
                  width: Annotated[int, Query(ge=640, le=1280)] = 1280):
    valid_camera(camera)
    if width not in imagestore.PREVIEW_WIDTHS:
        raise HTTPException(422, "Preview width must be 640 or 1280")
    images, _ = imagestore.directories(camera)
    original = image_path(images, filename)
    # The archive is flat; do not allow nested paths to alias cache filenames.
    if original.parent != images.resolve():
        raise HTTPException(404, "Image not found")
    preview = imagestore.make_preview(original, camera, width)
    # Some video snapshots are already very compact JPEGs. Never transfer a
    # larger derivative just because its format is WebP.
    if preview is not None and preview.stat().st_size >= original.stat().st_size:
        preview = None
    return FileResponse(preview or original, media_type="image/webp" if preview else "image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/api/weather/current")
def api_weather_current(camera: str = DEFAULT_CAMERA):
    valid_camera(camera)
    try:
        return localweather.current(camera)
    except Exception as e:
        logger.error("Weather stats error: %s", e)
        return JSONResponse({"success": False, "error": "Weather data unavailable"}, status_code=500)


@app.get("/api/weather/history")
def api_weather_history(hours: Annotated[int, Query(ge=1, le=720)] = 24, camera: str = DEFAULT_CAMERA):
    valid_camera(camera)
    try:
        records = localweather.history(camera, hours)
        return {"success": True, "data": records, "count": len(records),
                "station": localweather.metadata(camera),
                "coverage_start": records[0]["timestamp"] if records else None,
                "coverage_end": records[-1]["timestamp"] if records else None}
    except Exception as e:
        logger.error("Weather history error: %s", e)
        return JSONResponse({"success": False, "error": "Weather data unavailable"}, status_code=500)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="info")
