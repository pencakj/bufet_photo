"""Camera weather mappings, shared station caches and explicit provenance."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import os
from pathlib import Path
import tempfile
import threading
import time

import requests

from cameras import get_camera, read_only_mode
from solar import TZ
import weather

logger = logging.getLogger(__name__)
UTC = timezone.utc
ROOT = Path(os.environ.get("CAMERA_DATA_DIR", "/app/camera-data")) / "weather"
METRICS = ("temp", "hum", "wspd", "wdir", "bar", "rain", "solarrad", "uvi")
CHMI_ELEMENTS = {"T": "temp", "H": "hum", "Fprum": "wspd", "Dprum": "wdir",
                 "P": "bar", "SRA10M": "rain", "RGLB10": "solarrad"}


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    provider: str
    kind: str
    url: str
    wsi: str = ""
    rain_interval_minutes: int | None = None


STATIONS = {
    "bufet": Station("bufet", "Chalupa na Rozcestí · bufet", "Weathercloud", "measured",
                     "https://app.weathercloud.net/d3280293183"),
    "pec": Station("pec", "Pec pod Sněžkou · 816 m", "ČHMÚ", "measured",
                   "https://www.chmi.cz/w/h1pecs01-pec-pod-snezkou", "0-20000-0-11643", 10),
    "lucni": Station("lucni", "Luční bouda · 1413 m", "ČHMÚ", "measured",
                     "https://opendata.chmi.cz/meteorology/climate/now/", "0-203-0-11633", 10),
    "snezka": Station("snezka", "Sněžka, Poštovna · 1602 m", "ČHMÚ", "measured",
                      "https://opendata.chmi.cz/meteorology/climate/now/", "0-20000-0-11653", 10),
    "plan": Station("plan", "Svatý Petr – Pláň · model pro 1198 m", "Open-Meteo", "model",
                    "https://open-meteo.com/", rain_interval_minutes=60),
}
CAMERA_STATIONS = {"rozcesti": "bufet", "klinove-boudy": "bufet",
                   "pec": "pec", "bedrichov": "pec", "bedriska": "pec",
                   "lucni-bouda": "lucni", "snezka": "snezka", "svaty-petr": "plan"}
_records: dict[str, list[dict]] = {}
_errors: dict[str, str | None] = {}
_bootstrapped: set[str] = set()
_lock = threading.Lock()


def now() -> datetime:
    return datetime.now(UTC)


def timestamp(value: str) -> datetime:
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:  # Existing Weathercloud archive uses Prague wall time.
        date = TZ.localize(date)
    return date.astimezone(UTC)


def iso(date: datetime) -> str:
    return date.astimezone(UTC).isoformat().replace("+00:00", "Z")


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def station_for(camera_id: str) -> Station:
    get_camera(camera_id)
    return STATIONS[CAMERA_STATIONS[camera_id]]


def metadata(camera_id: str) -> dict:
    station = station_for(camera_id)
    shared = camera_id in ("klinove-boudy", "bedrichov", "bedriska")
    note = "Modelový odhad, nikoliv měření z meteostanice." if station.kind == "model" else "Naměřená data z uvedené stanice."
    if shared:
        note += " Sdílená stanice; neměří přímo u této kamery."
    if camera_id == "pec":
        note += " Kamera je na Husově boudě (1046 m), stanice v údolí Pece (816 m)."
    return {"id": station.id, "name": station.name, "provider": station.provider,
            "kind": station.kind, "url": station.url, "shared": shared, "note": note,
            "rain_interval_minutes": station.rain_interval_minutes,
            "attribution": "ČHMÚ, CC BY 4.0, operativní neověřená data" if station.wsi else station.provider}


def parse_chmi(payload: dict, wsi: str) -> list[dict]:
    table = payload["data"]["data"]
    fields = [field.strip() for field in table["header"].split(",")]
    records = {}
    for values in table["values"]:
        row = dict(zip(fields, values))
        metric = CHMI_ELEMENTS.get(row.get("ELEMENT"))
        value = number(row.get("VAL"))
        if row.get("STATION") != wsi or metric is None or value is None:
            continue
        if row.get("FLAG") not in (None, ""):
            continue  # Omit flagged operative values rather than guessing.
        key = iso(timestamp(row["DT"]))
        records.setdefault(key, {"timestamp": key})[metric] = value
    return [records[key] for key in sorted(records)]


def fetch_json(url: str, params=None) -> dict:
    started = time.monotonic()
    chunks = []
    size = 0
    with requests.get(url, params=params, stream=True, timeout=(10, 15)) as response:
        response.raise_for_status()
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 8 * 1024 * 1024 or time.monotonic() - started > 30:
                raise ValueError("Weather response exceeded limits")
            chunks.append(chunk)
    return json.loads(b"".join(chunks))


def parse_model(payload: dict) -> list[dict]:
    hourly = payload["hourly"]
    variables = {"temperature_2m": "temp", "relative_humidity_2m": "hum",
                 "wind_speed_10m": "wspd", "wind_direction_10m": "wdir",
                 "surface_pressure": "bar", "rain": "rain",
                 "shortwave_radiation": "solarrad", "uv_index": "uvi"}
    records = []
    for index, epoch in enumerate(hourly["time"]):
        date = datetime.fromtimestamp(epoch, UTC)
        if date > now():
            continue  # Future predictions never go into the historical graph.
        record = {"timestamp": iso(date)}
        for variable, metric in variables.items():
            record[metric] = number(hourly[variable][index])
        records.append(record)
    return records


def cached(station_id: str) -> list[dict]:
    with _lock:
        if station_id not in _records or read_only_mode():
            path = ROOT / f"{station_id}.json"
            try:
                _records[station_id] = json.loads(path.read_text()) if path.exists() else []
            except (OSError, ValueError):
                logger.exception("Could not load cached station %s", station_id)
                _records[station_id] = []
        return list(_records[station_id])


def merge(station_id: str, incoming: list[dict]):
    cutoff = now() - timedelta(days=32)
    rows = {row["timestamp"]: dict(row) for row in cached(station_id)}
    for row in incoming:
        rows.setdefault(row["timestamp"], {}).update(row)
    records = [rows[key] for key in sorted(rows) if cutoff <= timestamp(key) <= now()]
    ROOT.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=ROOT, prefix=f".{station_id}-", delete=False) as file:
            temporary = Path(file.name)
            json.dump(records, file, allow_nan=False)
        temporary.replace(ROOT / f"{station_id}.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    with _lock:
        _records[station_id] = records


def refresh(station: Station):
    try:
        if station.wsi:
            days = 3 if station.id not in _bootstrapped else 2
            for offset in reversed(range(days)):
                date = (now() - timedelta(days=offset)).strftime("%Y%m%d")
                url = f"https://opendata.chmi.cz/meteorology/climate/now/data/10m-{station.wsi}-{date}.json"
                try:
                    merge(station.id, parse_chmi(fetch_json(url), station.wsi))
                except requests.HTTPError as error:
                    if error.response is not None and error.response.status_code == 404:
                        continue
                    raise
            _bootstrapped.add(station.id)
            if not cached(station.id):
                raise ValueError("No station observations available")
        else:
            payload = fetch_json("https://api.open-meteo.com/v1/forecast", {
                "latitude": 50.7078564, "longitude": 15.6170042, "elevation": 1198,
                "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,surface_pressure,rain,shortwave_radiation,uv_index",
                "wind_speed_unit": "ms", "timezone": "UTC", "timeformat": "unixtime",
                "past_days": 30, "forecast_days": 1,
            })
            merge(station.id, parse_model(payload))
        with _lock:
            _errors[station.id] = None
        logger.info("Weather refreshed: %s", station.id)
    except Exception:
        with _lock:
            _errors[station.id] = "Zdroj není dostupný; zobrazuji poslední uložená data."
        logger.exception("Weather refresh failed: %s", station.id)


def run_poll_loop(stop: threading.Event):
    while not stop.is_set():
        for station in STATIONS.values():
            if stop.is_set():
                return
            if station.id != "bufet":
                refresh(station)
        stop.wait(600)


def history(camera_id: str, hours: int) -> list[dict]:
    station = station_for(camera_id)
    rows = weather.history(hours) if station.id == "bufet" else cached(station.id)
    cutoff = now() - timedelta(hours=hours)
    return [{**row, "timestamp": iso(timestamp(row["timestamp"]))} for row in rows
            if cutoff <= timestamp(row["timestamp"]) <= now()]


def summarise(records: list[dict]) -> dict | None:
    rows = [row for row in records if number(row.get("temp")) is not None]
    if not rows:
        return None
    latest = rows[-1]
    temperatures = [row["temp"] for row in rows]
    return {"temp": {"current": latest["temp"], "min": min(temperatures), "max": max(temperatures)},
            "humidity": number(latest.get("hum")), "wind_speed": number(latest.get("wspd")),
            "wind_dir": number(latest.get("wdir")), "pressure": number(latest.get("bar")),
            "rain": number(latest.get("rain")), "uvi": number(latest.get("uvi")),
            "solarrad": number(latest.get("solarrad")), "count": len(temperatures),
            "observed_at": latest["timestamp"]}


def current(camera_id: str) -> dict:
    station = station_for(camera_id)
    if station.id == "bufet":
        data = weather.stats(24)
        if data and data.get("observed_at"):
            data["observed_at"] = iso(timestamp(data["observed_at"]))
        records = []  # Production owns this archive; never duplicate it.
    else:
        records = history(camera_id, 24)
        data = summarise(records) or summarise(cached(station.id))
    observed = data.get("observed_at") if data else None
    stale = observed is None or now() - timestamp(observed) > timedelta(hours=2)
    with _lock:
        error = _errors.get(station.id)
    return {"success": True, "data": data, "station": metadata(camera_id),
            "stale": stale, "error": error, "observed_at": observed,
            "available_metrics": [metric for metric in METRICS if any(number(row.get(metric)) is not None for row in records)]
            if station.id != "bufet" else list(METRICS)}
