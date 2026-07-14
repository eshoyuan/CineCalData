import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from cinecal_agent import (
    PublicationError,
    corrected_crop_box,
    enforce_grounded_provenance,
    parse_json_object,
    passes_plan,
    render_crop,
)
from merge_cards import merge_cards
from media_provider import TMDBProvider, douban_lookup, title_without_season
from plan_calendar import build_matrix, merge_batches
from publish_today import choose_entry, publish


class AgentTests(unittest.TestCase):
    def test_season_suffix_is_removed_for_api_search(self):
        self.assertEqual(title_without_season("龙之家族 第三季"), ("龙之家族", 3))

    @patch("media_provider.request_json")
    def test_douban_rating_is_parsed_mechanically(self, request):
        request.return_value = {
            "cards": [{
                "title": "花样年华",
                "url": "https://movie.douban.com/subject/1291557/",
                "year": "2000",
                "card_subtitle": "8.8分 / 2000 / 中国香港 / 剧情 爱情",
                "type": "movie",
            }]
        }
        result = douban_lookup("花样年华", 2000)
        self.assertEqual(result["rating"], "8.8")
        self.assertEqual(result["doubanURL"], "https://movie.douban.com/subject/1291557/")

    @patch("media_provider.request_json")
    def test_tmdb_resolver_returns_ranked_landscape_candidates(self, request):
        request.side_effect = [
            {"results": [{
                "id": 123,
                "media_type": "movie",
                "title": "花样年华",
                "original_title": "花樣年華",
                "release_date": "2000-09-29",
                "popularity": 10,
            }]},
            {
                "id": 123,
                "title": "花样年华",
                "original_title": "花樣年華",
                "release_date": "2000-09-29",
                "overview": "简介",
                "images": {"backdrops": [
                    {"file_path": "/low.jpg", "width": 1280, "height": 720, "vote_count": 1, "vote_average": 7},
                    {"file_path": "/best.jpg", "width": 1920, "height": 1080, "vote_count": 9, "vote_average": 8},
                ]},
            },
        ]
        result = TMDBProvider("test-token").resolve("花样年华", release_year=2000)
        self.assertEqual(result["tmdbID"], 123)
        self.assertEqual(result["imageCandidates"][0]["imageURL"], "https://image.tmdb.org/t/p/original/best.jpg")

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

    def test_crop_plan_rejects_thematic_image_from_wrong_work(self):
        plan = {
            "sourceAcceptable": True,
            "workIdentityMatch": False,
            "square": {"compositionScore": 9},
            "medium": {"compositionScore": 9},
        }
        self.assertFalse(passes_plan(plan))

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
                "horizonDays": 730,
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
            merge_batches(plan, batches, horizon_days=1)
            merged = json.loads(plan.read_text(encoding="utf-8"))
            self.assertEqual([entry["title"] for entry in merged["entries"]], ["Locked", "New"])
            self.assertEqual(merged["horizonDays"], 730)

    def test_lightweight_today_publisher_uses_cached_entry(self):
        entries = [
            {"date": "2026-01-01", "title": "Earlier"},
            {"date": "2026-01-02", "title": "Today"},
        ]
        entry, fallback = choose_entry(entries, "2026-01-02")
        self.assertEqual(entry["title"], "Today")
        self.assertFalse(fallback)

    def test_card_merge_accepts_flat_downloaded_artifact_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            calendar = data / "calendar.json"
            calendar.write_text(json.dumps({
                "schemaVersion": 1,
                "entries": [{"date": "2026-01-01", "title": "Existing"}],
            }), encoding="utf-8")
            artifact = root / "artifacts" / "card-2026-01-02"
            (artifact / "images").mkdir(parents=True)
            (artifact / "reports").mkdir()
            (artifact / "calendar.json").write_text(json.dumps({
                "schemaVersion": 1,
                "entries": [{"date": "2026-01-02", "title": "Generated"}],
            }), encoding="utf-8")
            (artifact / "images" / "2026-01-02-small.jpg").write_bytes(b"image")
            (artifact / "reports" / "2026-01-02.json").write_text("{}", encoding="utf-8")

            self.assertEqual(merge_cards(calendar, root / "artifacts"), 1)
            merged = json.loads(calendar.read_text(encoding="utf-8"))
            self.assertEqual([entry["title"] for entry in merged["entries"]], ["Existing", "Generated"])
            self.assertTrue((data / "images" / "2026-01-02-small.jpg").exists())
            self.assertTrue((data / "reports" / "2026-01-02.json").exists())


if __name__ == "__main__":
    unittest.main()
