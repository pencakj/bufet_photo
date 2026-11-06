"""Security and compatibility checks; no collectors or real data are touched."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.images = self.root / "images"
        self.images.mkdir()
        (self.images / "image_test.jpg").write_bytes(b"test image")
        (self.root / "outside.jpg").write_bytes(b"outside")
        (self.images / "link.jpg").symlink_to(self.root / "outside.jpg")
        self.mock_dir = patch.object(main.imagestore, "IMAGES_DIR", self.images)
        self.mock_dir.start()
        self.addCleanup(self.mock_dir.stop)

    def test_home_renders_with_current_starlette(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Krkonoše Live", response.text)

    def test_health(self):
        self.assertEqual(self.client.get("/healthz").json(), {"status": "ok"})

    def test_image(self):
        response = self.client.get("/images/image_test.jpg")
        self.assertEqual(response.status_code, 200)
        self.assertIn("immutable", response.headers["cache-control"])

    def test_traversal(self):
        for prefix in ("/images/", "/thumbnails/", "/api/generate-thumbnail/"):
            for name in ("%2e%2e/outside.jpg", "%2fetc/passwd", "../main.py"):
                with self.subTest(prefix=prefix, name=name):
                    self.assertEqual(self.client.get(prefix + name).status_code, 404)

    def test_symlink_escape(self):
        self.assertEqual(self.client.get("/images/link.jpg").status_code, 404)

    def test_non_image_blocked(self):
        (self.images / "config.txt").write_text("private")
        self.assertEqual(self.client.get("/images/config.txt").status_code, 404)

    def test_pagination_bounds(self):
        for query in ("offset=-1", "limit=0", "limit=201", "order=invalid"):
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/api/images?" + query).status_code, 422)

    def test_image_listing(self):
        with patch.object(main.imagestore, "list_images", return_value=[]):
            response = self.client.get("/api/images?limit=50&order=asc")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 0)

    def test_weather_bounds(self):
        for hours in (-1, 0, 721):
            self.assertEqual(self.client.get(f"/api/weather/history?hours={hours}").status_code, 422)

    def test_errors_do_not_leak_details(self):
        with patch.object(main.weather, "stats", side_effect=RuntimeError("private path")):
            response = self.client.get("/api/weather/current")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private path", response.text)


if __name__ == "__main__":
    unittest.main()
