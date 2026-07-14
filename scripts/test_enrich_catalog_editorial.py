import unittest

from enrich_catalog_editorial import (
    DOUBAN_SUBJECT,
    PROMPT_VERSION,
    build_prompt,
    build_review_prompt,
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

    def test_review_prompt_batches_and_preserves_keys(self):
        items = [
            {"key": "a", "title": "甲", "ratings": {"douban": {}}, "images": {}},
            {"key": "b", "title": "乙", "ratings": {"douban": {}}, "images": {}},
        ]
        prompt = build_review_prompt(items, [{"key": "a", "quote": "甲句"}, {"key": "b", "quote": "乙句"}])
        self.assertIn('"key": "a"', prompt)
        self.assertIn('"key": "b"', prompt)
        self.assertIn("Never merge, omit, or change an input key", prompt)


if __name__ == "__main__":
    unittest.main()
