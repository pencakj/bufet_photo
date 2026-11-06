import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

import imagestore
import main


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.originals = self.root / "originals"
        self.thumbs = self.root / "thumbnails"
        self.cache = self.root / "cache"
        for directory in (self.originals, self.thumbs, self.cache):
            directory.mkdir()
        for attribute, value in [("IMAGES_DIR", self.originals), ("THUMBS_DIR", self.thumbs), ("DATA_DIR", self.cache)]:
            item = patch.object(imagestore, attribute, value)
            item.start()
            self.addCleanup(item.stop)
        self.file = self.originals / "image_20261106_120000.jpg"
        Image.effect_noise((2000, 1500), 30).convert("RGB").save(self.file, "JPEG", quality=95)
        self.content = self.file.read_bytes()
        self.disk = patch.object(imagestore.shutil, "disk_usage")
        self.disk.start().return_value.free = 1024 * 1024 * 1024
        self.addCleanup(self.disk.stop)
        self.client = TestClient(main.app)

    def test_display_preview_smaller_and_original_untouched(self):
        for width in (640, 1280):
            response = self.client.get(f"/previews/{self.file.name}?width={width}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"], "image/webp")
            self.assertIn("immutable", response.headers["cache-control"])
            self.assertLess(len(response.content), len(self.content))
            with Image.open(io.BytesIO(response.content)) as image:
                self.assertEqual(image.width, width)
                self.assertEqual(image.format, "WEBP")
        self.assertEqual(self.file.read_bytes(), self.content)
        self.assertEqual(list(self.thumbs.iterdir()), [])
        self.assertEqual(self.client.get(f"/images/{self.file.name}").content, self.content)

    def test_cached_preview_is_not_encoded_twice(self):
        preview = imagestore.make_preview(self.file)
        self.assertTrue(preview.is_relative_to(self.cache))
        with patch.object(imagestore.Image, "open", side_effect=AssertionError("Should use cache")):
            self.assertEqual(imagestore.make_preview(self.file), preview)

    def test_invalid_sizes_unknown_cameras_and_traversal_rejected(self):
        self.assertEqual(self.client.get(f"/previews/{self.file.name}?width=99999").status_code, 422)
        self.assertEqual(self.client.get(f"/previews/{self.file.name}?camera=unknown").status_code, 404)
        self.assertEqual(self.client.get("/previews/%2e%2e/private.jpg").status_code, 404)
        self.assertEqual(self.client.get("/previews/nonexistent.jpg").status_code, 404)

    def test_low_disk_space_falls_back_to_original(self):
        with patch.object(imagestore.shutil, "disk_usage") as usage:
            usage.return_value.free = 0
            response = self.client.get(f"/previews/{self.file.name}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertEqual(response.content, self.content)

    def test_unchanged_archive_does_not_rescan(self):
        store = imagestore.Archive("rozcesti")
        self.assertEqual(len(store.list()), 1)
        store.refreshed = float("-inf")
        with patch.object(imagestore.os, "listdir", side_effect=AssertionError("Unchanged directory")):
            self.assertEqual(len(store.list()), 1)
        self.file.unlink()
        store.refreshed = float("-inf")
        self.assertEqual(store.list(), [])

    def test_already_small_jpeg_never_replaced_with_larger_webp(self):
        large = self.cache / "larger.webp"
        large.write_bytes(b"x" * (len(self.content) + 1))
        with patch.object(imagestore, "make_preview", return_value=large):
            response = self.client.get(f"/previews/{self.file.name}?width=1280")
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertEqual(response.content, self.content)


if __name__ == "__main__":
    unittest.main()
