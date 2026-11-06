import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cameras import CAMERAS, get_camera
import imagestore
import localweather
import main


class DeploymentTests(unittest.TestCase):
    def test_default_port_is_8000(self):
        self.assertEqual(main.PORT, 8000)

    def test_read_only_mode_overrides_collectors_flag_and_all_cameras(self):
        with patch.dict(os.environ, {"READ_ONLY_MODE": "true", "COLLECTORS_ENABLED": "true"}):
            self.assertFalse(main.collectors_enabled())
            self.assertTrue(all(get_camera(camera.id).read_only for camera in CAMERAS))
        with patch.dict(os.environ, {"READ_ONLY_MODE": "false", "COLLECTORS_ENABLED": "true"}):
            self.assertTrue(main.collectors_enabled())
        with patch.dict(os.environ, {"READ_ONLY_MODE": "false", "COLLECTORS_ENABLED": "false"}):
            self.assertFalse(main.collectors_enabled())

    def test_preview_does_not_capture_or_generate_previews(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"READ_ONLY_MODE": "true"}):
            with patch.object(imagestore, "DATA_DIR", Path(directory)), patch.object(imagestore, "_fetch_jpeg") as fetch:
                self.assertIsNone(imagestore.capture_once("pec"))
                self.assertIsNone(imagestore.make_preview(Path(directory) / "image_test.jpg", "pec"))
                fetch.assert_not_called()
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_preview_reloads_weather_written_by_production(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"READ_ONLY_MODE": "true"}):
            root = Path(directory)
            with patch.object(localweather, "ROOT", root), patch.object(localweather, "_records", {}):
                file = root / "pec.json"
                file.write_text(json.dumps([{"temp": 1}]))
                self.assertEqual(localweather.cached("pec")[0]["temp"], 1)
                file.write_text(json.dumps([{"temp": 2}]))
                self.assertEqual(localweather.cached("pec")[0]["temp"], 2)


if __name__ == "__main__":
    unittest.main()
