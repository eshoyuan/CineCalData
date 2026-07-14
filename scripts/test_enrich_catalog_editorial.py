import unittest

from enrich_catalog_editorial import (
    DOUBAN_SUBJECT,
    MIN_DOUBAN_SCORE,
    PROMPT_VERSION,
    build_prompt,
    build_local_draft_prompt,
    build_review_prompt,
    catalog_quality_summary,
    needs_enrichment,
)


class EditorialEnrichmentTests(unittest.TestCase):
    def test_only_accepts_canonical_douban_subject(self):
        self.assertIsNotNone(DOUBAN_SUBJECT.fullmatch("https://movie.douban.com/subject/1295644/"))
        self.assertIsNone(DOUBAN_SUBJECT.fullmatch("https://www.themoviedb.org/movie/550"))
        self.assertIsNone(DOUBAN_SUBJECT.fullmatch("https://search.douban.com/movie/subject_search?q=x"))

    def test_existing_link_without_editorial_is_pending(self):
        item = {
            "ratings": {"douban": {"url": "https://movie.douban.com/subject/1295644/", "score": 9.4}},
            "editorial": {},
        }
        self.assertTrue(needs_enrichment(item))

    def test_prompt_forbids_fake_or_copied_quotes(self):
        prompt = build_prompt([{"key": "x", "title": "霸王别姬", "ratings": {"douban": {}}, "images": {}}])
        self.assertIn("do not guess", prompt)
        self.assertIn("Do not quote", prompt)
        self.assertIn("Do not use an app store", prompt)

    def test_new_prompt_version_requeues_old_copy(self):
        item = {
            "ratings": {"douban": {"url": "https://movie.douban.com/subject/1295644/", "score": 9.4}},
            "editorial": {"quote": "旧文案", "promptVersion": "catalog-editorial-v1"},
        }
        self.assertEqual(PROMPT_VERSION, "catalog-editorial-v2")
        self.assertTrue(needs_enrichment(item))

    def test_douban_floor_is_six(self):
        self.assertEqual(MIN_DOUBAN_SCORE, 6.0)

    def test_review_prompt_batches_and_preserves_keys(self):
        items = [
            {"key": "a", "title": "甲", "ratings": {"douban": {}}, "images": {}},
            {"key": "b", "title": "乙", "ratings": {"douban": {}}, "images": {}},
        ]
        prompt = build_review_prompt(items, [{"key": "a", "quote": "甲句"}, {"key": "b", "quote": "乙句"}])
        self.assertIn('"key": "a"', prompt)
        self.assertIn('"key": "b"', prompt)
        self.assertIn("Never merge, omit, or change an input key", prompt)

    def test_local_draft_prompt_does_not_change_verified_facts(self):
        item = {
            "key": "x",
            "title": "霸王别姬",
            "ratings": {"douban": {"score": 9.6, "url": "https://movie.douban.com/subject/1291546/"}},
            "images": {},
        }
        prompt = build_local_draft_prompt([item])
        self.assertIn("Do not search for or change those factual fields", prompt)
        self.assertIn("based only on the supplied metadata", prompt)

    def test_quality_summary_requires_complete_reviewed_cards(self):
        complete = {
            "ratings": {"douban": {"score": 8.8, "url": "https://movie.douban.com/subject/1295644/"}},
            "images": {"small": "small.jpg", "medium": "medium.jpg"},
            "editorial": {
                "quote": "潮水退去以后，沉默仍替相遇保管余温",
                "promptVersion": PROMPT_VERSION,
                "review": {"scores": {
                    "relevance": 8, "literary": 9, "specificity": 8,
                    "spoilerSafety": 10, "widgetFit": 9,
                }},
            },
        }
        incomplete = {
            **complete,
            "editorial": {**complete["editorial"], "review": {"scores": {"relevance": 7}}},
        }
        summary = catalog_quality_summary([complete, incomplete])
        self.assertEqual(summary["directDoubanAtLeastSixTotal"], 2)
        self.assertEqual(summary["completeCardTotal"], 1)
        self.assertEqual(summary["failedReviewTotal"], 1)


if __name__ == "__main__":
    unittest.main()
