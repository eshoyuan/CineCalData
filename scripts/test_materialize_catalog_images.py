import unittest

from materialize_catalog_images import Box, choose_crop


class CropSelectionTests(unittest.TestCase):
    def test_medium_crop_keeps_right_side_face_above_text_zone(self):
        face = Box(x=0.72, y=0.18, width=0.09, height=0.16)
        crop = choose_crop(1920, 1080, 1080 / 508, [face], [], size="medium")
        local_x = (face.center[0] - crop.x) / crop.width
        local_y = (face.center[1] - crop.y) / crop.height
        self.assertGreater(local_x, 0.5)
        self.assertLess(local_y, 0.58)

    def test_square_crop_follows_subject_in_wide_frame(self):
        subject = Box(x=0.68, y=0.14, width=0.18, height=0.54)
        crop = choose_crop(1920, 1080, 1.0, [], [subject], size="small")
        self.assertGreater(crop.x, 0.3)
        self.assertGreaterEqual(
            (min(crop.x + crop.width, subject.x + subject.width) - max(crop.x, subject.x)),
            subject.width * 0.95,
        )


if __name__ == "__main__":
    unittest.main()
