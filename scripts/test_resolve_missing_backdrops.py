import unittest

from resolve_missing_backdrops import validate_match


class BackdropResolutionTests(unittest.TestCase):
    def test_accepts_exact_original_title_and_year(self):
        item = {"title": "疯狂动物城", "originalTitle": "Zootopia", "year": 2016, "mediaType": "movie"}
        result = {
            "title": "疯狂动物城",
            "originalTitle": "Zootopia",
            "releaseYear": 2016,
            "mediaType": "movie",
            "imageCandidates": [{"imageURL": "https://example.test/image.jpg"}],
        }
        self.assertIsNone(validate_match(item, result))

    def test_rejects_cross_year_title_match(self):
        item = {"title": "傲慢与偏见", "originalTitle": "Pride and Prejudice", "year": 1995, "mediaType": "tv"}
        result = {
            "title": "傲慢与偏见",
            "originalTitle": "Pride & Prejudice",
            "releaseYear": 2005,
            "mediaType": "movie",
            "imageCandidates": [{"imageURL": "https://example.test/image.jpg"}],
        }
        self.assertIsNotNone(validate_match(item, result))


if __name__ == "__main__":
    unittest.main()
