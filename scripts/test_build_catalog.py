import unittest

from build_catalog import finalize, merge_douban_top250, merge_existing, parse_douban_top250_page


class CatalogBuilderTests(unittest.TestCase):
    def test_parses_douban_top250_without_copying_tagline(self):
        page = """
        <div class="item">
          <em class="">1</em>
          <a href="https://movie.douban.com/subject/1292052/">
            <span class="title">肖申克的救赎</span>
            <span class="title">The Shawshank Redemption</span>
          </a>
          <div class="bd"><p class="">导演: 弗兰克·德拉邦特<br>1994 / 美国 / 犯罪 剧情</p></div>
          <span class="rating_num" property="v:average">9.7</span>
          <span>3303548人评价</span>
          <span class="inq">希望让人自由。</span>
        </div>
        """
        records = parse_douban_top250_page(page)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["subjectID"], "1292052")
        self.assertEqual(records[0]["year"], 1994)
        self.assertEqual(records[0]["rating"], 9.7)
        self.assertNotIn("希望让人自由", records[0]["metadataText"])

    def test_merges_top250_by_title_and_year(self):
        tmdb_item = {
            "key": "tmdb:movie:278",
            "tmdbID": 278,
            "doubanSubjectID": "",
            "mediaType": "movie",
            "title": "肖申克的救赎",
            "originalTitle": "The Shawshank Redemption",
            "alternateTitles": [],
            "year": 1994,
            "ratings": {
                "tmdb": {"score": 8.7, "count": 25000, "url": "https://www.themoviedb.org/movie/278"},
                "douban": {"score": None, "count": None, "url": "", "top250Rank": None},
            },
            "sourceRanks": {"top_rated": 1},
        }
        record = {
            "rank": 1,
            "title": "肖申克的救赎",
            "alternateTitles": ["The Shawshank Redemption"],
            "year": 1994,
            "rating": 9.7,
            "ratingCount": 3303548,
            "url": "https://movie.douban.com/subject/1292052/",
            "subjectID": "1292052",
            "metadataText": "1994 / 美国 / 犯罪 剧情",
        }
        merged = merge_douban_top250([tmdb_item], [record], "2026-07-14T00:00:00Z")
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["doubanSubjectID"], "1292052")
        self.assertEqual(merged[0]["ratings"]["douban"]["top250Rank"], 1)

    def test_final_filter_accepts_known_douban_score_between_six_and_seven(self):
        item = {
            "title": "Example",
            "originalTitle": "",
            "alternateTitles": [],
            "year": 2026,
            "mediaType": "movie",
            "overview": "",
            "genres": [],
            "countries": [],
            "creators": [],
            "cast": [],
            "keywords": [],
            "ratings": {
                "tmdb": {"score": 8.0, "count": 1000, "url": ""},
                "douban": {"score": 6.9, "count": 100, "url": "", "top250Rank": None},
            },
            "popularity": {"tmdb": 50},
            "sourceRanks": {"popular": 1},
            "images": {"backdrop": "", "poster": ""},
            "lastSeenAt": "2026-07-14T00:00:00Z",
        }
        self.assertEqual(len(finalize([item], "2026-07-14T00:00:00Z")), 1)

    def test_final_filter_rejects_known_douban_score_below_six(self):
        item = {
            "title": "Example",
            "originalTitle": "",
            "alternateTitles": [],
            "year": 2026,
            "mediaType": "movie",
            "overview": "",
            "genres": [],
            "countries": [],
            "creators": [],
            "cast": [],
            "keywords": [],
            "ratings": {
                "tmdb": {"score": 8.0, "count": 1000, "url": ""},
                "douban": {"score": 5.9, "count": 100, "url": "", "top250Rank": None},
            },
            "popularity": {"tmdb": 50},
            "sourceRanks": {"popular": 1},
            "images": {"backdrop": "", "poster": ""},
            "lastSeenAt": "2026-07-14T00:00:00Z",
        }
        self.assertEqual(finalize([item], "2026-07-14T00:00:00Z"), [])

    def test_incremental_merge_preserves_top250_authority(self):
        previous = {
            "key": "tmdb:movie:278",
            "tmdbID": 278,
            "doubanSubjectID": "1292052",
            "mediaType": "movie",
            "sourceRanks": {"douban_top250": 1},
            "ratings": {
                "tmdb": {"score": 8.7, "count": 30000, "url": ""},
                "douban": {"score": 9.7, "count": 3300000, "url": "https://movie.douban.com/subject/1292052/", "top250Rank": 1},
            },
            "firstSeenAt": "2026-07-01T00:00:00Z",
        }
        refreshed = {
            "key": "tmdb:movie:278",
            "tmdbID": 278,
            "doubanSubjectID": "1292052",
            "mediaType": "movie",
            "sourceRanks": {"popular": 20},
            "ratings": {
                "tmdb": {"score": 8.7, "count": 30100, "url": ""},
                "douban": {"score": 9.7, "count": None, "url": "https://movie.douban.com/subject/1292052/", "top250Rank": None},
            },
        }
        merged = merge_existing([refreshed], [previous], "2026-07-14T00:00:00Z")
        self.assertEqual(merged[0]["ratings"]["douban"]["top250Rank"], 1)
        self.assertEqual(merged[0]["ratings"]["douban"]["count"], 3300000)
        self.assertEqual(merged[0]["sourceRanks"]["popular"], 20)


if __name__ == "__main__":
    unittest.main()
