import unittest

import cv2
import numpy as np

from visionlogix.detector import MarkerDetector, create_marker_png


class MarkerDetectorTests(unittest.TestCase):
    def test_detects_marker_id_and_center_from_generated_marker(self):
        encoded = np.frombuffer(create_marker_png(7, pixels=240), dtype=np.uint8)
        marker = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
        frame = np.full((400, 400), 255, dtype=np.uint8)
        frame[80:320, 80:320] = marker

        detections, annotated = MarkerDetector().detect(frame)

        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].marker_id, 7)
        self.assertAlmostEqual(detections[0].center_x, 199.5, delta=2)
        self.assertAlmostEqual(detections[0].center_y, 199.5, delta=2)
        self.assertGreater(detections[0].side_pixels, 200)
        self.assertEqual(annotated.shape, (400, 400))

    def test_detects_marker_id_96_from_the_supported_range(self):
        encoded = np.frombuffer(create_marker_png(96, pixels=240), dtype=np.uint8)
        marker = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
        frame = np.full((400, 400), 255, dtype=np.uint8)
        frame[80:320, 80:320] = marker

        detections, _ = MarkerDetector().detect(frame)

        self.assertEqual([detection.marker_id for detection in detections], [96])

    def test_blank_frame_has_no_detections(self):
        detections, _ = MarkerDetector().detect(np.full((360, 640), 255, dtype=np.uint8))

        self.assertEqual(detections, [])

    def test_marker_id_outside_supported_dictionary_is_rejected(self):
        with self.assertRaises(ValueError):
            create_marker_png(97)


if __name__ == "__main__":
    unittest.main()
