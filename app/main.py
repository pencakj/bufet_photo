"""Krkonoše Live v2 — FastAPI entrypoint."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import imagestore
import weather
from solar import is_daytime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

PORT = 8003


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        data = weather.fetch()
        if data:
            weather.save(data)
    except Exception as e:
        logger.error("Startup weather fetch failed: %s", e)

    threading.Thread(target=imagestore.run_capture_loop, daemon=True).start()
    threading.Thread(target=weather.run_poll_loop, daemon=True).start()
    logger.info("Background workers started")
    yield


app = FastAPI(title="Krkonoše Live", version="2.0", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"is_daytime": is_daytime()},
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


@app.get("/api/images")
def api_images(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    order: Literal["asc", "desc"] = "desc",
):
    images = imagestore.list_images()
    if order.lower() == "asc":
        images = list(reversed(images))
    total = len(images)
    page = images[offset : offset + limit]
    return {
        "images": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + limit) < total,
        "is_daytime": is_daytime(),
    }


@app.get("/api/generate-thumbnail/{filename:path}")
def api_generate_thumbnail(filename: str):
    path = image_path(imagestore.IMAGES_DIR, filename)
    thumb = imagestore.make_thumbnail(path)
    if thumb is None:
        raise HTTPException(500, "Failed to create thumbnail")
    return {"success": True, "thumb_path": f"thumb_{filename}"}


@app.get("/images/{filename:path}")
def serve_image(filename: str):
    path = image_path(imagestore.IMAGES_DIR, filename)
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/thumbnails/{filename:path}")
def serve_thumb(filename: str):
    path = image_path(imagestore.THUMBS_DIR, filename)
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000"},
    )


@app.get("/api/weather/current")
def api_weather_current():
    try:
        return {"success": True, "data": weather.stats(24)}
    except Exception as e:
        logger.error("Weather stats error: %s", e)
        return JSONResponse({"success": False, "error": "Weather data unavailable"}, status_code=500)


@app.get("/api/weather/history")
def api_weather_history(hours: Annotated[int, Query(ge=1, le=720)] = 24):
    try:
        hours = min(hours, 24 * 30)
        records = weather.history(hours)
        return {"success": True, "data": records, "count": len(records)}
    except Exception as e:
        logger.error("Weather history error: %s", e)
        return JSONResponse({"success": False, "error": "Weather data unavailable"}, status_code=500)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="info")
