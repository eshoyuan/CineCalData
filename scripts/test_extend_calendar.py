import unittest
from datetime import date

from extend_calendar import extend_calendar


def item(index: int, *, title: str | None = None) -> dict:
    subject = str(1000 + index)
    return {
        "key": f"tmdb:movie:{index}",
        "doubanSubjectID": subject,
        "title": title or f"电影 {index}",
        "rating": 8.0,
        "quote": f"短句 {index}",
        "imageURLSmall": f"https://example.com/{index}-small.jpg",
        "imageURLMedium": f"https://example.com/{index}-medium.jpg",
        "doubanURL": f"https://movie.douban.com/subject/{subject}/",
    }


class ExtendCalendarTests(unittest.TestCase):
    def test_builds_complete_unique_date_keyed_horizon(self):
        result = extend_calendar(
            {"entries": []},
            {"items": [item(index) for index in range(5)]},
            {"entries": []},
            start=date(2026, 7, 14),
            days=3,
            generated_at="now",
        )
        self.assertEqual([entry["date"] for entry in result["entries"]], ["2026-07-14", "2026-07-15", "2026-07-16"])
        self.assertEqual(len({entry["doubanSubjectID"] for entry in result["entries"]}), 3)
        self.assertTrue(all(entry["imageURLSmall"] and entry["imageURLMedium"] for entry in result["entries"]))

    def test_preserves_complete_existing_card_and_replaces_incomplete_card(self):
        complete = {
            "date": "2026-07-14",
            "id": "curated",
            "title": "策展电影",
            "rating": "9.0",
            "quote": "策展短句",
            "imageURLSmall": "https://example.com/s.jpg",
            "imageURLMedium": "https://example.com/m.jpg",
            "doubanURL": "https://movie.douban.com/subject/999/",
        }
        incomplete = {"date": "2026-07-15", "title": "缺图电影"}
        result = extend_calendar(
            {"entries": [complete, incomplete]},
            {"items": [item(index) for index in range(5)]},
            {"entries": []},
            start=date(2026, 7, 14),
            days=2,
            generated_at="now",
        )
        self.assertEqual(result["entries"][0]["id"], "curated")
        self.assertIn("imageURLSmall", result["entries"][1])

    def test_matches_plan_title_when_available(self):
        result = extend_calendar(
            {"entries": []},
            {"items": [item(1), item(2, title="花样年华"), item(3)]},
            {"entries": [{"date": "2026-07-14", "title": "花样年华", "reason": "导演生日"}]},
            start=date(2026, 7, 14),
            days=1,
            generated_at="now",
        )
        self.assertEqual(result["entries"][0]["title"], "花样年华")
        self.assertEqual(result["entries"][0]["selectionReason"], "导演生日")

    def test_is_deterministic_for_the_same_date(self):
        arguments = (
            {"entries": []},
            {"items": [item(index) for index in range(5)]},
            {"entries": []},
        )
        first = extend_calendar(*arguments, start=date(2026, 7, 14), days=3, generated_at="one")
        second = extend_calendar(*arguments, start=date(2026, 7, 14), days=3, generated_at="two")
        self.assertEqual(
            [entry["doubanSubjectID"] for entry in first["entries"]],
            [entry["doubanSubjectID"] for entry in second["entries"]],
        )


if __name__ == "__main__":
    unittest.main()
