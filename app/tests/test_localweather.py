from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import requests

from cameras import CAMERAS
import localweather as lw
import main


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.date = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
        self.patches = [patch.object(lw, "ROOT", Path(self.temp.name)),
                        patch.object(lw, "_records", {}), patch.object(lw, "_errors", {}),
                        patch.object(lw, "_bootstrapped", set()), patch.object(lw, "now", return_value=self.date)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = TestClient(main.app)

    def record(self, value, age=1):
        return {"timestamp": lw.iso(self.date - timedelta(hours=age)), "temp": value, "hum": 50, "wspd": 2}

    def test_every_camera_has_source_and_requested_aliases_match(self):
        self.assertEqual(set(lw.CAMERA_STATIONS), {c.id for c in CAMERAS})
        self.assertEqual(lw.station_for("bedrichov"), lw.station_for("pec"))
        self.assertEqual(lw.station_for("bedriska"), lw.station_for("pec"))
        self.assertEqual(lw.station_for("klinove-boudy"), lw.station_for("rozcesti"))
        self.assertTrue(lw.metadata("bedriska")["shared"])
        self.assertIn("1046", lw.metadata("pec")["note"])
        self.assertEqual(lw.metadata("svaty-petr")["kind"], "model")

    def test_chmi_units_flags_and_unsupported_fields(self):
        wsi = lw.STATIONS["pec"].wsi
        rows = [[wsi, element, "2026-11-06T11:00:00Z", value, flag, 5]
                for element, value, flag in [("T", -2.5, ""), ("H", 80, ""),
                    ("Fprum", 3.2, ""), ("P", 930.4, ""), ("SRA10M", 0.2, ""),
                    ("TMA", 99, ""), ("RGLB10", 100, "Z")]]
        data = lw.parse_chmi({"data": {"data": {"header": "STATION,ELEMENT,DT,VAL,FLAG,QUALITY", "values": rows}}}, wsi)
        self.assertEqual(data[0]["temp"], -2.5)
        self.assertEqual(data[0]["wspd"], 3.2)
        self.assertEqual(data[0]["bar"], 930.4)
        self.assertEqual(data[0]["rain"], 0.2)
        self.assertNotIn("solarrad", data[0])
        self.assertNotIn("uvi", data[0])

    def test_zero_values_are_not_missing(self):
        summary = lw.summarise([self.record(0)])
        self.assertEqual(summary["temp"]["current"], 0)
        self.assertIsNone(summary["uvi"])

    def test_shared_cameras_read_exact_same_station_archive(self):
        lw.merge("pec", [self.record(7)])
        for camera in ("pec", "bedrichov", "bedriska"):
            data = self.client.get(f"/api/weather/current?camera={camera}").json()
            self.assertEqual(data["station"]["id"], "pec")
            self.assertEqual(data["data"]["temp"]["current"], 7)
            self.assertFalse(data["stale"])
        self.assertEqual(lw.history("pec", 24), lw.history("bedriska", 24))
        self.assertEqual(len(list(Path(self.temp.name).glob("*.json"))), 1)

    def test_bufet_alias_uses_production_without_writes(self):
        data = {"temp": {"current": 2, "min": -3, "max": 3}, "observed_at": "2026-11-06 12:00:00"}
        with patch.object(lw.weather, "stats", return_value=data), patch.object(lw, "merge") as save:
            response = self.client.get("/api/weather/current?camera=klinove-boudy").json()
            self.assertEqual(response["station"]["id"], "bufet")
            self.assertEqual(response["observed_at"], "2026-11-06T11:00:00Z")
            save.assert_not_called()

    def test_station_failure_keeps_cached_data_and_reports_error(self):
        lw.merge("pec", [self.record(7)])
        with patch.object(lw, "fetch_json", side_effect=requests.Timeout("private details")):
            lw.refresh(lw.STATIONS["pec"])
        result = lw.current("bedrichov")
        self.assertEqual(result["data"]["temp"]["current"], 7)
        self.assertTrue(result["error"])
        self.assertNotIn("private details", result["error"])

    def test_stale_readings_are_explicit_not_replaced_with_other_station(self):
        lw.merge("pec", [self.record(7, age=30)])
        result = lw.current("pec")
        self.assertTrue(result["stale"])
        self.assertEqual(result["station"]["id"], "pec")
        self.assertEqual(result["data"]["temp"]["current"], 7)

    def test_history_limits_and_iso_timestamps(self):
        lw.merge("pec", [self.record(-2, age=25), self.record(7)])
        data = self.client.get("/api/weather/history?camera=bedriska&hours=24").json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["coverage_start"], self.record(7)["timestamp"])
        self.assertTrue(data["data"][0]["timestamp"].endswith("Z"))

    def test_unknown_weather_camera_rejected(self):
        for path in ("current", "history"):
            self.assertEqual(self.client.get(f"/api/weather/{path}?camera=unknown").status_code, 404)

    def test_model_never_puts_future_forecasts_into_history(self):
        times = [(self.date - timedelta(hours=1)).timestamp(), (self.date + timedelta(hours=1)).timestamp()]
        hourly = {"time": times}
        for variable in ("temperature_2m", "relative_humidity_2m", "wind_speed_10m", "wind_direction_10m",
                         "surface_pressure", "rain", "shortwave_radiation", "uv_index"):
            hourly[variable] = [1, 2]
        records = lw.parse_model({"hourly": hourly})
        self.assertEqual(len(records), 1)
        self.assertLess(lw.timestamp(records[0]["timestamp"]), self.date)

    def test_cache_survives_restart_and_merges_without_duplicates(self):
        lw.merge("pec", [self.record(7)])
        lw.merge("pec", [self.record(8)])
        with patch.object(lw, "_records", {}):
            self.assertEqual(len(lw.cached("pec")), 1)
            self.assertEqual(lw.cached("pec")[0]["temp"], 8)
        self.assertFalse(list(Path(self.temp.name).glob(".pec-*")))
        self.assertEqual(len(json.loads((Path(self.temp.name) / "pec.json").read_text())), 1)


if __name__ == "__main__":
    unittest.main()
