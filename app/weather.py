"""Weathercloud polling, storage, and aggregation."""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytz
import requests

from solar import TZ

logger = logging.getLogger(__name__)

WEATHER_FILE = Path("/app/data/weather.jsonl")
WEATHER_FILE.parent.mkdir(parents=True, exist_ok=True)

DEVICE_ID = "3280293183"
POLL_SECONDS = 600

_lock = threading.Lock()


def _now_prague() -> datetime:
    return datetime.now(pytz.UTC).astimezone(TZ)


def fetch() -> dict[str, Any] | None:
    try:
        url = f"https://app.weathercloud.net/device/values/{DEVICE_ID}"
        r = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
        logger.error("Weather HTTP %s", r.status_code)
    except Exception as e:
        logger.error("Weather fetch error: %s", e)
    return None


def save(data: dict[str, Any]) -> None:
    if not data:
        return
    record = {
        "timestamp": _now_prague().strftime("%Y-%m-%d %H:%M:%S"),
        "temp": data.get("temp"),
        "hum": data.get("hum"),
        "bar": data.get("bar"),
        "wdir": data.get("wdir"),
        "wspd": data.get("wspd"),
        "rain": data.get("rain"),
        "uvi": data.get("uvi"),
        "solarrad": data.get("solarrad"),
    }
    with _lock, open(WEATHER_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")
    logger.info("Weather saved: %s°C", record.get("temp"))


def load(since: datetime | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not WEATHER_FILE.exists():
        return records
    with _lock, open(WEATHER_FILE) as f:
        for line in f:
            try:
                rec = json.loads(line.strip())
                if since:
                    t = datetime.strptime(rec["timestamp"], "%Y-%m-%d %H:%M:%S")
                    if t < since:
                        continue
                records.append(rec)
            except (json.JSONDecodeError, KeyError):
                continue
    return records


def stats(hours: int = 24) -> dict[str, Any] | None:
    since = (_now_prague() - timedelta(hours=hours)).replace(tzinfo=None)
    records = load(since)
    if not records:
        return None

    latest = records[-1]
    temps = [r["temp"] for r in records if r.get("temp") is not None]
    if not temps:
        return None

    return {
        "temp": {"current": latest.get("temp"), "min": min(temps), "max": max(temps)},
        "humidity": latest.get("hum"),
        "wind_speed": latest.get("wspd"),
        "wind_dir": latest.get("wdir"),
        "pressure": latest.get("bar"),
        "rain": latest.get("rain"),
        "uvi": latest.get("uvi"),
        "solarrad": latest.get("solarrad"),
        "count": len(temps),
    }


def history(hours: int) -> list[dict[str, Any]]:
    since = (_now_prague() - timedelta(hours=hours)).replace(tzinfo=None)
    return load(since)


def run_poll_loop() -> None:
    while True:
        try:
            data = fetch()
            if data:
                save(data)
        except Exception as e:
            logger.error("Weather loop error: %s", e)
        time.sleep(POLL_SECONDS)
