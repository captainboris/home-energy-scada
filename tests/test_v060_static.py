import base64
import gzip
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from lambda_function import frontend_file


PROJECT = Path(__file__).resolve().parents[1]
DIST = PROJECT / "source" / "frontend-react" / "dist"


class ReactStaticAssetTests(unittest.TestCase):
    def call(self, path):
        with patch.dict(os.environ, {"FRONTEND_ROOT": str(DIST)}):
            return frontend_file(path)

    def test_react_entry_pages_are_deployable(self):
        for path in ("/", "/daily"):
            result = self.call(path)
            self.assertEqual(result["statusCode"], 200)
            self.assertIn("text/html", result["headers"]["Content-Type"])
            self.assertIn('id="root"', result["body"])
            self.assertEqual(result["headers"]["Cache-Control"], "no-store")

    def test_hashed_javascript_is_gzipped_and_immutable(self):
        asset = next((DIST / "assets").glob("overview-*.js"))
        result = self.call("/assets/" + asset.name)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["headers"]["Content-Encoding"], "gzip")
        self.assertEqual(
            result["headers"]["Cache-Control"],
            "public, max-age=31536000, immutable",
        )
        decoded = gzip.decompress(base64.b64decode(result["body"])).decode()
        self.assertEqual(decoded, asset.read_text(encoding="utf-8"))

    def test_current_readings_image_uses_the_existing_production_csp(self):
        asset = next((DIST / "assets").glob("overview-*.js"))
        result = self.call("/assets/" + asset.name)
        script = gzip.decompress(base64.b64decode(result["body"])).decode()
        image = re.search(r'data:image/webp;base64,([A-Za-z0-9+/=]+)', script)
        self.assertIsNotNone(image, "Scene must not require a new image route or CSP change")
        decoded = base64.b64decode(image.group(1))
        self.assertEqual(decoded[:4], b"RIFF")
        self.assertEqual(decoded[8:12], b"WEBP")
        self.assertIn("img-src data:;", self.call("/")["headers"]["Content-Security-Policy"])

    def test_legacy_shared_assets_remain_available(self):
        result = self.call("/shared.js")
        self.assertEqual(result["statusCode"], 200)
        self.assertIn("application/javascript", result["headers"]["Content-Type"])


if __name__ == "__main__":
    unittest.main()
