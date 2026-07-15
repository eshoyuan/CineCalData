import unittest
from unittest.mock import patch

from media_provider import MediaProviderError, douban_lookup


class DoubanLookupTests(unittest.TestCase):
    def test_searches_title_without_polluting_query_with_year(self):
        payload = {
            "cards": [
                {
                    "type": "movie",
                    "title": "公民凯恩",
                    "year": "1941",
                    "url": "https://movie.douban.com/subject/1292288/",
                    "card_subtitle": "8.8分 / 1941 / 美国",
                }
            ]
        }
        with patch("media_provider.request_json", return_value=payload) as request:
            result = douban_lookup("公民凯恩", 1941)
        self.assertEqual(result["rating"], "8.8")
        requested_url = request.call_args.args[0]
        self.assertIn("q=%E5%85%AC%E6%B0%91%E5%87%AF%E6%81%A9", requested_url)
        self.assertNotIn("1941", requested_url)
        self.assertEqual(request.call_args.kwargs["timeout"], 8)

    def test_rejects_same_year_but_nonexact_title(self):
        payload = {
            "cards": [
                {
                    "type": "movie",
                    "title": "另一部电影",
                    "year": "1941",
                    "url": "https://movie.douban.com/subject/1/",
                    "card_subtitle": "8.8分 / 1941 / 美国",
                }
            ]
        }
        with patch("media_provider.request_json", return_value=payload):
            with self.assertRaises(MediaProviderError):
                douban_lookup("公民凯恩", 1941)

    def test_accepts_same_year_first_season_for_series_base_title(self):
        payload = {
            "cards": [
                {
                    "type": "tv",
                    "title": "绝命毒师 第一季",
                    "year": "2008",
                    "url": "https://movie.douban.com/subject/2373195/",
                    "card_subtitle": "9.2分 / 2008 / 美国",
                }
            ]
        }
        with patch("media_provider.request_json", return_value=payload):
            result = douban_lookup("绝命毒师", 2008)
        self.assertEqual(result["doubanURL"], "https://movie.douban.com/subject/2373195/")


if __name__ == "__main__":
    unittest.main()
