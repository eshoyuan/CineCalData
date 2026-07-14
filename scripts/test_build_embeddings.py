import unittest

import numpy as np

from build_embeddings import embedding_text, normalize_mrl


class EmbeddingBuilderTests(unittest.TestCase):
    def test_text_contains_recommendation_metadata(self):
        text = embedding_text(
            {
                "title": "花样年华",
                "originalTitle": "In the Mood for Love",
                "alternateTitles": [],
                "year": 2000,
                "genres": ["剧情", "爱情"],
                "countries": ["中国香港"],
                "creators": ["王家卫"],
                "cast": ["梁朝伟", "张曼玉"],
                "keywords": ["怀旧"],
                "overview": "一段克制的感情。",
            }
        )
        self.assertIn("花样年华", text)
        self.assertIn("王家卫", text)
        self.assertIn("怀旧", text)

    def test_mrl_truncates_and_renormalizes(self):
        vectors = np.array([[3.0, 4.0, 12.0]], dtype=np.float32)
        result = normalize_mrl(vectors, 2)
        np.testing.assert_allclose(result, [[0.6, 0.8]], rtol=1e-6)


if __name__ == "__main__":
    unittest.main()
