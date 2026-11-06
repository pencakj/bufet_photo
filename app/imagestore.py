"""Image storage: download, thumbnail, cache, scheduled capture."""
from __future__ import annotations

import io
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypedDict

import pytz
import requests
from PIL import Image

from solar import TZ, capture_interval_seconds

logger = logging.getLogger(__name__)

IMAGES_DIR = Path("/app/images")
THUMBS_DIR = Path("/app/thumbnails")
SOURCE_URL = "https://chalupanarozcesti.cz/webcam/latest.php"
THUMB_SIZE = (400, 400)

IMAGES_DIR.mkdir(parents=True, exist_ok=True)
THUMBS_DIR.mkdir(parents=True, exist_ok=True)


class ImageEntry(TypedDict):
    path: str
    thumb_path: str
    formatted_time: str
    day: str
    timestamp: str
    has_thumbnail: bool


_cache: list[ImageEntry] | None = None
_cache_latest_ts: str = ""
_cache_lock = threading.Lock()


def _now_prague() -> datetime:
    return datetime.now(pytz.UTC).astimezone(TZ)


def _entry_from_name(name: str, thumb_set: set[str]) -> ImageEntry:
    ts = name[len("image_") : -len(".jpg")]
    day = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
    formatted = f"{day} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"
    thumb = f"thumb_{name}"
    return {
        "path": name,
        "thumb_path": thumb,
        "formatted_time": formatted,
        "day": day,
        "timestamp": ts,
        "has_thumbnail": thumb in thumb_set,
    }


def make_thumbnail(image_path: Path) -> Path | None:
    try:
        thumb_path = THUMBS_DIR / f"thumb_{image_path.name}"
        if not thumb_path.exists():
            with Image.open(image_path) as img:
                img.thumbnail(THUMB_SIZE)
                img.save(thumb_path, "JPEG", quality=85)
        return thumb_path
    except Exception as e:
        logger.error("Thumbnail failed for %s: %s", image_path, e)
        return None


def list_images() -> list[ImageEntry]:
    """Return all images newest-first, using an incrementally-refreshed cache."""
    global _cache, _cache_latest_ts

    with _cache_lock:
        try:
            names = os.listdir(IMAGES_DIR)
        except FileNotFoundError:
            return _cache or []

        if _cache is None:
            try:
                thumbs = set(os.listdir(THUMBS_DIR))
            except FileNotFoundError:
                thumbs = set()

            t0 = time.time()
            entries: list[ImageEntry] = []
            for n in names:
                if not (n.startswith("image_") and n.endswith(".jpg")):
                    continue
                try:
                    entries.append(_entry_from_name(n, thumbs))
                except Exception as e:
                    logger.error("Skipping %s: %s", n, e)

            entries.sort(key=lambda e: e["timestamp"], reverse=True)
            _cache = entries
            _cache_latest_ts = entries[0]["timestamp"] if entries else ""
            logger.info("Image cache built: %d entries in %.2fs", len(entries), time.time() - t0)
            return _cache

        new_names = [
            n for n in names
            if n.startswith("image_") and n.endswith(".jpg")
            and n[len("image_") : -len(".jpg")] > _cache_latest_ts
        ]
        if not new_names:
            return _cache

        try:
            thumbs = set(os.listdir(THUMBS_DIR))
        except FileNotFoundError:
            thumbs = set()

        new_entries = []
        for n in new_names:
            try:
                new_entries.append(_entry_from_name(n, thumbs))
            except Exception as e:
                logger.error("Skipping %s: %s", n, e)

        new_entries.sort(key=lambda e: e["timestamp"], reverse=True)
        _cache = new_entries + _cache
        _cache_latest_ts = new_entries[0]["timestamp"]
        logger.info("Image cache: +%d new (total %d)", len(new_entries), len(_cache))
        return _cache


def _prepend_cache(image_path: Path) -> None:
    global _cache, _cache_latest_ts
    with _cache_lock:
        if _cache is None:
            return
        name = image_path.name
        ts = name[len("image_") : -len(".jpg")]
        if ts <= _cache_latest_ts:
            return
        try:
            thumbs = {f"thumb_{name}"} if (THUMBS_DIR / f"thumb_{name}").exists() else set()
            _cache.insert(0, _entry_from_name(name, thumbs))
            _cache_latest_ts = ts
        except Exception as e:
            logger.error("Failed to prepend %s: %s", name, e)


def capture_once() -> Path | None:
    try:
        r = requests.get(SOURCE_URL, stream=True, timeout=30)
        if r.status_code != 200:
            logger.error("Capture HTTP %s", r.status_code)
            return None
        content = r.content
        try:
            Image.open(io.BytesIO(content)).verify()
        except Exception as e:
            logger.error("Invalid image payload: %s", e)
            return None

        ts = _now_prague().strftime("%Y%m%d_%H%M%S")
        target = IMAGES_DIR / f"image_{ts}.jpg"
        target.write_bytes(content)

        # De-duplicate within the same minute, keep largest
        minute_prefix = ts[:-2]
        siblings = sorted(
            IMAGES_DIR.glob(f"image_{minute_prefix}*.jpg"),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        if len(siblings) > 1:
            for extra in siblings[1:]:
                try:
                    extra.unlink()
                except FileNotFoundError:
                    pass

        final = siblings[0] if siblings else target
        if final.exists():
            make_thumbnail(final)
            _prepend_cache(final)
            logger.info("Captured %s", final.name)
            return final
    except Exception as e:
        logger.error("Capture failed: %s", e)
    return None


def run_capture_loop() -> None:
    try:
        list_images()
    except Exception as e:
        logger.error("Warm cache failed: %s", e)

    try:
        capture_once()
    except Exception as e:
        logger.error("Initial capture failed: %s", e)

    while True:
        interval = capture_interval_seconds()
        now = datetime.now(TZ)
        seconds_since_midnight = now.hour * 3600 + now.minute * 60 + now.second
        next_tick = ((seconds_since_midnight // interval) + 1) * interval

        if next_tick >= 86400:
            next_tick %= 86400
            base = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            target = base + timedelta(seconds=next_tick)
        else:
            h, m, s = next_tick // 3600, (next_tick % 3600) // 60, next_tick % 60
            target = now.replace(hour=h, minute=m, second=s, microsecond=0)

        delay = (target - now).total_seconds()
        if delay > 0:
            logger.info("Next capture at %s (in %ds)", target.strftime("%H:%M:%S"), int(delay))
            time.sleep(delay)

        capture_once()
