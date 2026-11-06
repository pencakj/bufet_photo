"""Camera-scoped archives and bounded JPEG/HLS snapshot collection."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import io
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time

import requests
from PIL import Image

from cameras import CAMERAS, DEFAULT_CAMERA, get_camera
from solar import TZ, capture_interval_seconds

logger = logging.getLogger(__name__)
IMAGES_DIR = Path("/app/images")
THUMBS_DIR = Path("/app/thumbnails")
DATA_DIR = Path(os.environ.get("CAMERA_DATA_DIR", "/app/camera-data"))
THUMB_SIZE = (400, 400)
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MIN_FREE_BYTES = 512 * 1024 * 1024
IMAGE_NAME = re.compile(r"^image_\d{8}_\d{6}\.jpg$")
_stores: dict[str, Archive] = {}
_stores_lock = threading.Lock()


def directories(camera_id: str = DEFAULT_CAMERA) -> tuple[Path, Path]:
    get_camera(camera_id)  # Reject unknown IDs before constructing paths.
    if camera_id == DEFAULT_CAMERA:
        return IMAGES_DIR, THUMBS_DIR
    root = DATA_DIR / camera_id
    return root / "images", root / "thumbnails"


def _entry(name: str, thumbs: set[str]) -> dict:
    ts = name[6:-4]
    day = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
    return {
        "path": name, "thumb_path": f"thumb_{name}", "day": day,
        "timestamp": ts,
        "formatted_time": f"{day} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}",
        "has_thumbnail": f"thumb_{name}" in thumbs,
    }


class Archive:
    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self.images, self.thumbs = directories(camera_id)
        self.lock = threading.Lock()
        self.entries: list[dict] = []
        self.refreshed = float("-inf")
        self.last_error: str | None = None
        if not get_camera(camera_id).read_only:
            self.images.mkdir(parents=True, exist_ok=True)
            self.thumbs.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict]:
        with self.lock:
            if time.monotonic() - self.refreshed < 10:
                return list(self.entries)
            names = {n for n in os.listdir(self.images) if IMAGE_NAME.fullmatch(n)} if self.images.exists() else set()
            thumbs = set(os.listdir(self.thumbs)) if self.thumbs.exists() else set()
            # Reuse existing metadata, but honor deletions and backfilled captures.
            previous = {item["path"]: item for item in self.entries}
            self.entries = sorted(
                (dict(previous[n], has_thumbnail=f"thumb_{n}" in thumbs)
                 if n in previous else _entry(n, thumbs) for n in names),
                key=lambda item: item["timestamp"], reverse=True,
            )
            self.refreshed = time.monotonic()
            return list(self.entries)

    def invalidate(self):
        with self.lock:
            self.refreshed = float("-inf")


def archive(camera_id: str = DEFAULT_CAMERA) -> Archive:
    with _stores_lock:
        paths = directories(camera_id)
        store = _stores.get(camera_id)
        if store is None or (store.images, store.thumbs) != paths:
            store = _stores[camera_id] = Archive(camera_id)
        return store


def list_images(camera_id: str = DEFAULT_CAMERA) -> list[dict]:
    return archive(camera_id).list()


def _atomic_write(path: Path, content: bytes):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".capture-", delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
        temporary.chmod(0o644)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def make_thumbnail(image_path: Path, camera_id: str = DEFAULT_CAMERA) -> Path | None:
    try:
        camera = get_camera(camera_id)
        _, thumbs = directories(camera_id)
        target = thumbs / f"thumb_{image_path.name}"
        if target.exists():
            return target
        if camera.read_only:
            return None
        with Image.open(image_path) as img:
            img.thumbnail(THUMB_SIZE)
            output = io.BytesIO()
            img.convert("RGB").save(output, "JPEG", quality=85)
        _atomic_write(target, output.getvalue())
        return target
    except Exception:
        logger.exception("Thumbnail failed for %s", image_path)
        return None


def _fetch_jpeg(url: str) -> bytes:
    chunks = []
    size = 0
    started = time.monotonic()
    with requests.get(url, stream=True, timeout=(10, 15)) as response:
        response.raise_for_status()
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > MAX_IMAGE_BYTES or time.monotonic() - started > 30:
                raise ValueError("Image download exceeded its size or time limit")
            chunks.append(chunk)
    return b"".join(chunks)


def _snapshot_hls(url: str) -> bytes:
    # No shell, no user-provided URL, no continuous recording, one decoder thread.
    result = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-protocol_whitelist", "https,tls,tcp,crypto", "-rw_timeout", "15000000",
        "-threads", "1", "-i", url, "-frames:v", "1", "-an",
        "-vf", "scale='min(2048,iw)':-2", "-threads", "1",
        "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ], capture_output=True, timeout=45, check=True)
    return result.stdout


def capture_once(camera_id: str = DEFAULT_CAMERA) -> Path | None:
    camera = get_camera(camera_id)
    if camera.read_only:
        return None
    store = archive(camera_id)
    try:
        if shutil.disk_usage(store.images).free < MIN_FREE_BYTES:
            raise OSError("Less than 512 MiB free; capture paused to protect storage")
        # Providers can update a JPEG while it is being downloaded. Decode it
        # fully before publishing and retry a torn JPEG once (never accept it).
        attempts = 2 if camera.kind == "jpeg" else 1
        for attempt in range(attempts):
            try:
                content = _fetch_jpeg(camera.url) if camera.kind == "jpeg" else _snapshot_hls(camera.url)
                if not content or len(content) > MAX_IMAGE_BYTES:
                    raise ValueError("Invalid snapshot size")
                with Image.open(io.BytesIO(content)) as image:
                    if image.format != "JPEG":
                        raise ValueError("Snapshot is not a JPEG")
                    image.load()
                break
            except (OSError, ValueError, requests.RequestException):
                if attempt + 1 == attempts:
                    raise
                time.sleep(0.5)
        timestamp = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
        target = store.images / f"image_{timestamp}.jpg"
        _atomic_write(target, content)
        make_thumbnail(target, camera_id)
        store.invalidate()
        with store.lock:
            store.last_error = None
        logger.info("Captured %s: %s", camera_id, target.name)
        return target
    except Exception:
        with store.lock:
            store.last_error = "Capture failed; retrying at the next scheduled capture"
        logger.exception("Capture failed for %s", camera_id)
        return None


def camera_status(camera_id: str) -> dict:
    camera = get_camera(camera_id)
    store = archive(camera_id)
    images = store.list()
    latest = images[0] if images else None
    with store.lock:
        error = store.last_error
    return {
        "id": camera.id, "name": camera.name, "kind": camera.kind,
        "location": camera.location, "provider": camera.provider,
        "source_page": camera.source_page, "read_only": camera.read_only,
        "total": len(images), "latest": latest,
        "last_error": error,
        "status": "error" if error else ("ok" if latest else "waiting"),
    }


def run_capture_loop(stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    active = [camera for camera in CAMERAS if not camera.read_only]
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="capture") as pool:
        while not stop.is_set():
            list(pool.map(lambda camera: capture_once(camera.id), active))
            now = datetime.now(TZ)
            interval = capture_interval_seconds(now)
            seconds = now.hour * 3600 + now.minute * 60 + now.second
            target = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
                seconds=((seconds // interval) + 1) * interval)
            delay = max(1, (target - now).total_seconds())
            logger.info("Next camera captures in %ds", delay)
            stop.wait(delay)
