import math
import unittest

from tracking import FaceSample, Settings, Tracker


def face(x=0.5, y=0.5):
    return FaceSample(x, y, 0.1, 0.1)


class AnchorTests(unittest.TestCase):
    def test_calibration_uses_the_cursor_position_at_completion(self):
        tracker = Tracker(Settings(calibration_seconds=0.3))
        for now, cursor in [(0.0, (0.2, 0.8)), (0.12, (0.35, 0.6)), (0.24, (0.7, 0.2))]:
            result = tracker.update(now, face(), calibration_position=cursor)
            self.assertFalse(tracker.calibrated)
            self.assertIsNone(result.position)
            self.assertIsNone(result.click)

        final_cursor = (0.8, 0.25)
        result = tracker.update(0.31, face(), calibration_position=final_cursor)
        self.assertTrue(tracker.calibrated)
        self.assertTrue(result.calibrated)
        self.assertEqual(result.position, final_cursor)
        self.assertIsNone(result.click)
        self.assertEqual(
            tracker.update(0.38, face(0.505, 0.497), calibration_position=(0.2, 0.2)).position,
            final_cursor,
        )

    def test_earlier_calibration_position_is_not_used_without_a_fresh_one(self):
        tracker = Tracker(Settings(calibration_seconds=0.1))
        tracker.update(0.0, face(), calibration_position=(0.1, 0.9))
        self.assertEqual(tracker.update(0.11, face()).position, (0.5, 0.5))

    def test_anchored_calibration_accounts_for_drift_on_each_axis(self):
        tracker = Tracker(Settings(calibration_seconds=0.3, dwell_seconds=0.3))
        anchor = (0.8, 0.25)
        for now, x, y in [(0, 0.50, 0.488), (0.1, 0.52, 0.490),
                          (0.2, 0.57, 0.492), (0.31, 0.60, 0.500)]:
            result = tracker.update(now, face(x, y), calibration_position=anchor)
        self.assertEqual(result.position, anchor)

        # X drifted during calibration. Y stayed close enough to keep its average.
        for now in (0.35, 0.49, 0.63, 0.77):
            result = tracker.update(now, face(0.60, 0.487))
            self.assertEqual(result.position, anchor)
            self.assertEqual(result.dwell_progress, 0)
            self.assertIsNone(result.click)

        moved = tracker.update(0.81, face(0.62, 0.487))
        self.assertLess(moved.position[0], anchor[0])
        self.assertEqual(moved.position[1], anchor[1])
        self.assertIsNone(moved.click)

    def test_unanchored_preview_keeps_the_calibration_average_after_drift(self):
        tracker = Tracker(Settings(calibration_seconds=0.3, smoothing_seconds=0))
        for now, y in [(0, 0.50), (0.1, 0.52), (0.2, 0.57), (0.31, 0.60)]:
            tracker.update(now, face(y=y))
        self.assertEqual(tracker.update(0.35, face(y=0.5475)).position, (0.5, 0.5))
        self.assertGreater(tracker.update(0.39, face(y=0.60)).position[1], 0.5)

    def test_mirrored_mapping_reaches_all_edges_from_an_offset_origin(self):
        tracker = Tracker(Settings(calibration_seconds=0, smoothing_seconds=0))
        origin = (0.78, 0.23)
        self.assertEqual(tracker.update(0.0, face(), calibration_position=origin).position, origin)
        self.assertEqual(tracker.update(0.04, face(0.64, 0.64)).position, (0.0, 1.0))
        self.assertEqual(tracker.update(0.08, face()).position, origin)
        self.assertEqual(tracker.update(0.12, face(0.36, 0.36)).position, (1.0, 0.0))

    def test_unmirrored_mapping_scales_to_the_distance_on_each_side(self):
        tracker = Tracker(Settings(calibration_seconds=0, smoothing_seconds=0, mirror=False))
        tracker.update(0.0, face(), calibration_position=(0.8, 0.2))
        # Halfway from the horizontal dead zone to the edge in either direction.
        positive = tracker.update(0.04, face(0.566)).position
        negative = tracker.update(0.08, face(0.434)).position
        self.assertAlmostEqual(positive[0], 0.9)
        self.assertAlmostEqual(negative[0], 0.4)

    def test_face_loss_keeps_anchor_but_jump_and_reset_clear_it(self):
        tracker = Tracker(Settings(calibration_seconds=0, smoothing_seconds=0, rearm_seconds=0))
        origin = (0.14, 0.73)
        tracker.update(0.0, face(), calibration_position=origin)
        loss = tracker.update(0.08, None)
        self.assertEqual(loss.state, "paused")
        self.assertTrue(tracker.calibrated)
        self.assertEqual(tracker.update(0.12, face()).position, origin)
        jump = tracker.update(0.16, face(0.76))
        self.assertEqual(jump.state, "face_jump")
        self.assertFalse(tracker.calibrated)
        self.assertIsNone(jump.position)
        self.assertIsNone(jump.click)
        self.assertEqual(tracker.update(0.20, face(0.76)).position, (0.5, 0.5))
        tracker.reset()
        self.assertFalse(tracker.calibrated)
        self.assertEqual(tracker.update(0.0, face(0.3)).position, (0.5, 0.5))

    def test_dwell_stays_disarmed_at_an_offset_origin(self):
        tracker = Tracker(Settings(calibration_seconds=0, smoothing_seconds=0, dwell_seconds=0.3))
        origin = (0.8, 0.2)
        tracker.update(0.0, face(), calibration_position=origin)
        for now in (0.10, 0.22, 0.34, 0.46, 0.58):
            still = tracker.update(now, face())
            self.assertEqual(still.position, origin)
            self.assertEqual(still.dwell_progress, 0)
            self.assertIsNone(still.click)
        for now in (0.69, 0.82, 0.94):
            self.assertIsNone(tracker.update(now, face(0.54)).click)
        result = tracker.update(1.04, face(0.54))
        self.assertEqual(result.click, "left")
        self.assertEqual(result.dwell_progress, 1)
        self.assertLess(result.position[0], origin[0])

    def test_calibration_position_must_be_finite_and_normalized(self):
        tracker = Tracker(Settings(calibration_seconds=0))
        for invalid in ((math.nan, 0.5), (0.5, math.inf), (0.5, -0.1), (1.1, 0.5), (0.5,), (None, 0.5)):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    tracker.update(0.0, face(), calibration_position=invalid)
                self.assertFalse(tracker.calibrated)
        self.assertEqual(tracker.update(0.0, face(), calibration_position=(0.0, 1.0)).position, (0.0, 1.0))


if __name__ == "__main__":
    unittest.main()
