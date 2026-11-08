import unittest

from tracking import FaceSample, Settings, Tracker


class MotionOnlyTests(unittest.TestCase):
    def test_calibrates_and_moves_without_interpreting_eye_closures(self):
        tracker = Tracker(Settings(motion_only=True, calibration_seconds=0.2, smoothing_seconds=0))
        closed = FaceSample(0.5, 0.5, 0.95, 0.95)
        self.assertEqual(tracker.update(0, closed).state, "calibrating")
        self.assertEqual(tracker.update(0.1, closed).state, "calibrating")
        result = tracker.update(0.21, closed, calibration_position=(0.3, 0.7))
        self.assertEqual(result.position, (0.3, 0.7))

        for index, (left, right) in enumerate(((0.95, 0), (0, 0.95), (0.95, 0.95), (0, 0))):
            sample = FaceSample(0.46, 0.55, left, right)
            result = tracker.update(0.3 + index * 0.1, sample)
            self.assertEqual(result.state, "tracking")
            self.assertGreater(result.position[0], 0.3)
            self.assertGreater(result.position[1], 0.7)
            self.assertIsNone(result.click)

    def test_still_pauses_on_lost_face_and_rearms_on_valid_frames(self):
        tracker = Tracker(Settings(motion_only=True, calibration_seconds=0, smoothing_seconds=0))
        closed = FaceSample(0.5, 0.5, 0.95, 0.95)
        tracker.update(0, closed)
        lost = tracker.update(0.1, None)
        self.assertEqual((lost.state, lost.position, lost.click), ("paused", None, None))
        self.assertEqual(tracker.update(0.2, closed).state, "rearming")
        resumed = tracker.update(0.38, closed)
        self.assertEqual((resumed.state, resumed.position, resumed.click), ("tracking", (0.5, 0.5), None))

    def test_rejects_combining_motion_only_with_dwell_clicks(self):
        with self.assertRaisesRegex(ValueError, "Motion-only mode cannot use dwell"):
            Settings(motion_only=True, dwell_seconds=0.6)


if __name__ == "__main__":
    unittest.main()
