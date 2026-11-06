import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

import cameras
import imagestore
import main


class CameraTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch.object(imagestore, "DATA_DIR", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.disk = patch.object(imagestore.shutil, "disk_usage")
        self.disk.start().return_value.free = 1024 * 1024 * 1024
        self.addCleanup(self.disk.stop)
        self.client = TestClient(main.app)
        output = io.BytesIO()
        Image.new("RGB", (64, 48), "orange").save(output, "JPEG")
        self.jpeg = output.getvalue()

    def test_registry_is_unique_and_original_is_first(self):
        self.assertEqual(len(cameras.CAMERAS), 8)
        self.assertEqual(len(cameras.BY_ID), 8)
        self.assertEqual(cameras.CAMERAS[0].id, "rozcesti")
        self.assertEqual(sum(c.kind == "hls" for c in cameras.CAMERAS), 4)

    def test_tabs_render_in_order(self):
        html = self.client.get("/").text
        positions = [html.index(f'id="tab-{c.id}"') for c in cameras.CAMERAS]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('role="tablist"', html)

    def test_capture_and_thumbnail_are_camera_scoped(self):
        with patch.object(imagestore, "_fetch_jpeg", return_value=self.jpeg):
            pec = imagestore.capture_once("pec")
            lucni = imagestore.capture_once("lucni-bouda")
        self.assertTrue(pec.is_file())
        self.assertTrue(lucni.is_file())
        self.assertNotEqual(pec.parent, lucni.parent)
        for camera in ("pec", "lucni-bouda"):
            listing = self.client.get(f"/api/images?camera={camera}").json()
            self.assertEqual(listing["total"], 1)
            self.assertEqual(listing["today_count"], 1)
            filename = listing["images"][0]["path"]
            self.assertEqual(self.client.get(f"/images/{filename}?camera={camera}").status_code, 200)
            self.assertEqual(self.client.get(f"/thumbnails/thumb_{filename}?camera={camera}").status_code, 200)
        self.assertFalse(list(self.root.rglob(".capture-*")))

    def test_unknown_camera_and_cross_camera_paths_rejected(self):
        for endpoint in ("/api/images", "/images/test.jpg", "/thumbnails/test.jpg",
                         "/api/generate-thumbnail/test.jpg"):
            self.assertEqual(self.client.get(endpoint + "?camera=unknown").status_code, 404)
        self.assertEqual(self.client.get("/images/%2e%2e/other/images/test.jpg?camera=pec").status_code, 404)

    def test_read_only_original_never_captures_or_generates(self):
        with patch.object(imagestore, "_fetch_jpeg") as fetch:
            self.assertIsNone(imagestore.capture_once("rozcesti"))
            fetch.assert_not_called()
        path = self.root / "original.jpg"
        path.write_bytes(self.jpeg)
        with patch.object(imagestore, "THUMBS_DIR", self.root):
            self.assertIsNone(imagestore.make_thumbnail(path, "rozcesti"))
            self.assertFalse((self.root / "thumb_original.jpg").exists())

    def test_video_extracts_one_frame_with_timeout_without_shell(self):
        with patch.object(imagestore.subprocess, "run") as run:
            run.return_value.stdout = self.jpeg
            self.assertEqual(imagestore._snapshot_hls(cameras.BY_ID["klinove-boudy"].url), self.jpeg)
            args, options = run.call_args
            command = args[0]
            self.assertEqual(command[command.index("-frames:v") + 1], "1")
            self.assertEqual(options["timeout"], 45)
            self.assertNotIn("shell", options)

    def test_failed_camera_does_not_contaminate_another(self):
        with patch.object(imagestore, "_snapshot_hls", side_effect=subprocess.TimeoutExpired("ffmpeg", 45)):
            self.assertIsNone(imagestore.capture_once("klinove-boudy"))
        self.assertEqual(imagestore.camera_status("klinove-boudy")["status"], "error")
        with patch.object(imagestore, "_fetch_jpeg", return_value=self.jpeg):
            self.assertIsNotNone(imagestore.capture_once("pec"))
        self.assertEqual(imagestore.camera_status("pec")["status"], "ok")

    def test_invalid_image_not_archived(self):
        with patch.object(imagestore, "_fetch_jpeg", return_value=b"not an image"):
            self.assertIsNone(imagestore.capture_once("pec"))
        self.assertEqual(imagestore.list_images("pec"), [])

    def test_low_disk_space_pauses_without_deleting(self):
        with patch.object(imagestore, "_fetch_jpeg", return_value=self.jpeg):
            existing = imagestore.capture_once("pec")
        with patch.object(imagestore.shutil, "disk_usage") as usage, patch.object(imagestore, "_fetch_jpeg") as fetch:
            usage.return_value.free = 0
            self.assertIsNone(imagestore.capture_once("pec"))
            fetch.assert_not_called()
        self.assertTrue(existing.is_file())

    def test_truncated_jpeg_retried_but_never_archived(self):
        with patch.object(imagestore, "_fetch_jpeg", return_value=self.jpeg[:-20]) as fetch:
            self.assertIsNone(imagestore.capture_once("pec"))
            self.assertEqual(fetch.call_count, 2)
        self.assertEqual(imagestore.list_images("pec"), [])


if __name__ == "__main__":
    unittest.main()
