import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from PIL import Image

from cinecal_agent import (
    PublicationError,
    corrected_crop_box,
    enforce_grounded_provenance,
    parse_json_object,
    render_crop,
)
from plan_calendar import build_matrix, merge_batches
from publish_today import choose_entry, publish


class AgentTests(unittest.TestCase):
    def test_extracts_fenced_json(self):
        self.assertEqual(parse_json_object('```json\n{"ok": true}\n```'), {"ok": True})

    def test_square_crop_stays_in_bounds(self):
        box = corrected_crop_box((1600, 900), [350, 0, 1000, 1000], 1.0)
        self.assertGreaterEqual(box[0], 0)
        self.assertGreaterEqual(box[1], 0)
        self.assertLessEqual(box[2], 1600)
        self.assertLessEqual(box[3], 900)
        self.assertAlmostEqual(box[2] - box[0], box[3] - box[1], delta=1)

    def test_medium_output_has_widget_dimensions(self):
        image = Image.new("RGB", (1600, 900), "navy")
        crop = render_crop(image, [0, 100, 1000, 900], 349.67 / 164.33, (1080, 508))
        self.assertEqual(crop.size, (1080, 508))

    def test_rejects_hotlinked_image_without_explicit_license(self):
        item = {
            "doubanURL": "https://movie.douban.com/subject/1/",
            "ratingSourceURL": "https://movie.douban.com/subject/1/",
            "imageCandidates": [
                {
                    "imageURL": "https://studio.example/still.jpg",
                    "sourcePageURL": "https://studio.example/press",
                    "credit": "Studio",
                }
            ],
        }
        grounded = [
            "https://movie.douban.com/subject/1/",
            "https://studio.example/press",
        ]
        with self.assertRaises(PublicationError):
            enforce_grounded_provenance(item, grounded, rights_mode="production")

    def test_accepts_grounded_crop_safe_cc_image(self):
        item = {
            "doubanURL": "https://movie.douban.com/subject/1/",
            "ratingSourceURL": "https://movie.douban.com/subject/1/",
            "imageCandidates": [
                {
                    "imageURL": "https://commons.example/still.jpg",
                    "sourcePageURL": "https://commons.example/still",
                    "credit": "Photographer",
                    "rightsHolder": "Photographer",
                    "rightsStatus": "cc_by",
                    "licenseName": "CC BY 4.0",
                    "licenseURL": "https://creativecommons.org/licenses/by/4.0/",
                    "commercialUseAllowed": True,
                    "modificationAllowed": True,
                }
            ],
        }
        grounded = [
            "https://movie.douban.com/subject/1/",
            "https://commons.example/still",
            "https://creativecommons.org/licenses/by/4.0/",
        ]
        enforce_grounded_provenance(item, grounded, rights_mode="production")
        self.assertEqual(len(item["imageCandidates"]), 1)

    def test_prototype_accepts_grounded_official_promotional_image(self):
        item = {
            "doubanURL": "https://movie.douban.com/subject/1/",
            "ratingSourceURL": "https://movie.douban.com/subject/1/",
            "imageCandidates": [
                {
                    "imageURL": "https://studio.example/still.jpg",
                    "sourcePageURL": "https://studio.example/press",
                    "credit": "Studio",
                    "rightsHolder": "Studio",
                    "rightsStatus": "official_promotional",
                    "licenseName": "",
                    "licenseURL": "",
                    "commercialUseAllowed": False,
                    "modificationAllowed": False,
                }
            ],
        }
        grounded = [
            "https://movie.douban.com/subject/1/",
            "https://studio.example/press",
        ]
        enforce_grounded_provenance(item, grounded, rights_mode="prototype")
        self.assertEqual(len(item["imageCandidates"]), 1)

    def test_prototype_allows_canonical_douban_link_when_rating_is_grounded(self):
        item = {
            "doubanURL": "https://movie.douban.com/subject/123/",
            "ratingSourceURL": "https://ratings.example/work/123",
            "imageCandidates": [
                {
                    "imageURL": "https://studio.example/still.jpg",
                    "sourcePageURL": "https://studio.example/press",
                    "credit": "Studio",
                    "rightsHolder": "Studio",
                    "rightsStatus": "official_promotional",
                }
            ],
        }
        grounded = [
            "https://ratings.example/work/123",
            "https://studio.example/press",
        ]
        enforce_grounded_provenance(item, grounded, rights_mode="prototype")

    def test_planning_matrix_covers_requested_horizon(self):
        matrix = build_matrix(date(2026, 1, 1), days=31, batch_days=14)
        self.assertEqual(matrix, [
            {"start": "2026-01-01", "days": 14},
            {"start": "2026-01-15", "days": 14},
            {"start": "2026-01-29", "days": 3},
        ])

    def test_plan_merge_preserves_locked_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "plan.json"
            plan.write_text(json.dumps({
                "schemaVersion": 1,
                "entries": [{"date": "2026-01-01", "title": "Locked", "locked": True}],
            }), encoding="utf-8")
            batches = root / "batches"
            batches.mkdir()
            (batches / "batch.json").write_text(json.dumps({
                "entries": [
                    {"date": "2026-01-01", "title": "Replacement", "locked": False},
                    {"date": "2026-01-02", "title": "New", "locked": False},
                ]
            }), encoding="utf-8")
            merge_batches(plan, batches, horizon_days=730)
            merged = json.loads(plan.read_text(encoding="utf-8"))
            self.assertEqual([entry["title"] for entry in merged["entries"]], ["Locked", "New"])

    def test_lightweight_today_publisher_uses_cached_entry(self):
        entries = [
            {"date": "2026-01-01", "title": "Earlier"},
            {"date": "2026-01-02", "title": "Today"},
        ]
        entry, fallback = choose_entry(entries, "2026-01-02")
        self.assertEqual(entry["title"], "Today")
        self.assertFalse(fallback)


if __name__ == "__main__":
    unittest.main()
