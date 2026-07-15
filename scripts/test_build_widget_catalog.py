import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("build_widget_catalog.py")


class WidgetCatalogTests(unittest.TestCase):
    def test_deduplicates_by_douban_subject(self):
        base = {
            "title": "未麻的部屋",
            "recommendationEligible": True,
            "quote": "现实裂开一道缝，另一个自己从中凝望。",
            "images": {"small": "https://example.com/s.jpg", "medium": "https://example.com/m.jpg"},
            "ratings": {"douban": {"score": 9.1, "url": "https://movie.douban.com/subject/1395091/"}},
        }
        first = {**base, "key": "tmdb:movie:10494", "doubanSubjectID": "1395091"}
        second = {**base, "key": "douban:1395091", "doubanSubjectID": "1395091"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.json"
            output = root / "widget.json"
            catalog.write_text(json.dumps({"items": [first, second]}), encoding="utf-8")
            subprocess.run(
                [sys.executable, str(SCRIPT), "--catalog", str(catalog), "--output", str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["doubanSubjectID"], "1395091")


if __name__ == "__main__":
    unittest.main()
