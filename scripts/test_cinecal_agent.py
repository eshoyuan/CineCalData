import unittest

from PIL import Image

from cinecal_agent import (
    PublicationError,
    corrected_crop_box,
    enforce_grounded_provenance,
    parse_json_object,
    render_crop,
)


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


if __name__ == "__main__":
    unittest.main()
