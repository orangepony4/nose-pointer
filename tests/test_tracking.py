import math
import unittest

from tracking import FaceSample, Settings, Tracker


def face(x=0.5, y=0.5, left=0.1, right=0.1):
    return FaceSample(x, y, left, right)


class TrackingTests(unittest.TestCase):
    def assert_centered(self, output):
        self.assertTrue(output.calibrated)
        self.assertIsNotNone(output.position)
        self.assertAlmostEqual(output.position[0], 0.5)
        self.assertAlmostEqual(output.position[1], 0.5)

    def ready_tracker(self, **overrides):
        options = {"calibration_seconds": 0, "smoothing_seconds": 0}
        options.update(overrides)
        tracker = Tracker(Settings(**options))
        self.assert_centered(tracker.update(0.0, face()))
        return tracker

    def test_calibrates_from_an_average_of_both_open_samples(self):
        tracker = Tracker()
        for now, x in [(0.0, 0.48), (0.2, 0.49), (0.4, 0.50), (0.6, 0.51)]:
            result = tracker.update(now, face(x, 0.4))
            self.assertFalse(result.calibrated)
            self.assertIsNone(result.position)
            self.assertIsNone(result.click)
        result = tracker.update(0.81, face(0.52, 0.4))
        self.assert_centered(result)
        self.assertEqual(result.calibration_progress, 1)
        self.assert_centered(tracker.update(0.86, face(0.50, 0.4)))

    def test_calibration_requires_continuous_open_eyes(self):
        tracker = Tracker(Settings(calibration_seconds=0.3, smoothing_seconds=0))
        tracker.update(0.0, face(0.2, 0.3))
        tracker.update(0.1, face(0.2, 0.3))
        interrupted = tracker.update(0.16, face(0.2, 0.3, left=0.9))
        self.assertFalse(interrupted.calibrated)
        self.assertIsNone(interrupted.click)
        for now in [0.20, 0.31, 0.41]:
            self.assertFalse(tracker.update(now, face(0.35, 0.4)).calibrated)
        self.assert_centered(tracker.update(0.51, face(0.35, 0.4)))
        self.assert_centered(tracker.update(0.55, face(0.35, 0.4)))

    def test_dead_zone_horizontal_mirror_and_screen_clamping(self):
        mirrored = self.ready_tracker(mirror=True)
        straight = self.ready_tracker(mirror=False)
        for tracker in (mirrored, straight):
            self.assert_centered(tracker.update(0.04, face(0.507, 0.493)))

        reflected = mirrored.update(0.08, face(0.55, 0.54)).position
        direct = straight.update(0.08, face(0.55, 0.54)).position
        self.assertLess(reflected[0], 0.5)
        self.assertGreater(direct[0], 0.5)
        self.assertAlmostEqual(reflected[0] + direct[0], 1)
        self.assertGreater(direct[1], 0.5)
        self.assertAlmostEqual(reflected[1], direct[1])

        self.assertEqual(mirrored.update(0.12, face(0.63, 0.63)).position, (0, 1))
        mirrored.update(0.16, face(0.51, 0.51))
        self.assertEqual(mirrored.update(0.20, face(0.37, 0.39)).position, (1, 0))
        self.assertEqual(straight.update(0.12, face(0.63, 0.63)).position, (1, 1))

    def test_smoothing_moves_progressively_towards_the_target(self):
        tracker = self.ready_tracker(mirror=False, smoothing_seconds=0.10)
        positions = [tracker.update(now, face(0.63)).position for now in (0.04, 0.08, 0.16)]
        self.assertTrue(0.5 < positions[0][0] < positions[1][0] < positions[2][0] < 1)
        for _, y in positions:
            self.assertAlmostEqual(y, 0.5)

    def test_single_eye_wink_clicks_once_on_reopen_and_holds_the_pointer(self):
        for button, closed, mirror in [
            ("left", face(0.65, 0.6, left=0.9), True),
            ("right", face(0.65, 0.6, right=0.9), True),
            ("left", face(0.65, 0.6, left=0.9), False),
            ("right", face(0.65, 0.6, right=0.9), False),
        ]:
            with self.subTest(button=button, mirror=mirror):
                tracker = self.ready_tracker(mirror=mirror)
                for now in (0.10, 0.22, 0.33):
                    result = tracker.update(now, closed)
                    self.assertIsNone(result.click)
                    self.assertIsNone(result.position)
                opened = tracker.update(0.37, face(0.65, 0.6))
                self.assertEqual(opened.click, button)
                self.assertIsNone(opened.position)
                for now in (0.44, 0.56, 0.68, 0.83):
                    self.assertIsNone(tracker.update(now, face()).click)

    def test_brief_single_sample_bilateral_and_overlong_blinks_do_not_click(self):
        closed_left = face(left=0.9)
        closed_both = face(left=0.9, right=0.9)
        sequences = {
            "brief": [(0.10, closed_left), (0.15, closed_left), (0.19, face())],
            "single closed sample": [(0.10, closed_left), (0.33, face())],
            "bilateral": [(0.10, closed_both), (0.23, closed_both), (0.38, face())],
            "overlong": [
                (0.10, closed_left), (0.28, closed_left), (0.46, closed_left),
                (0.64, closed_left), (0.82, closed_left), (1.00, closed_left), (1.07, face()),
            ],
        }
        for name, sequence in sequences.items():
            with self.subTest(name=name):
                tracker = self.ready_tracker()
                for now, sample in sequence:
                    self.assertIsNone(tracker.update(now, sample).click)

    def test_uncertain_reopening_does_not_extend_the_wink_duration(self):
        sequences = {
            "short closure before a slow reopening": (
                [(0.125, 0.9), (0.1875, 0.9), (0.25, 0.5), (0.375, 0.5), (0.4375, 0.1)], False
            ),
            "reopening starts at minimum": (
                [(0.125, 0.9), (0.25, 0.9), (0.375, 0.5), (0.4375, 0.1)], True
            ),
            "directly open at minimum": (
                [(0.125, 0.9), (0.25, 0.9), (0.375, 0.1)], True
            ),
            "transient uncertainty followed by clear closure": (
                [(0.125, 0.9), (0.1875, 0.9), (0.25, 0.5), (0.3125, 0.9), (0.375, 0.1)], True
            ),
            "reopening still incomplete after maximum": (
                [(0.125, 0.9), (0.25, 0.9), (0.375, 0.5), (0.5625, 0.5),
                 (0.75, 0.5), (0.9375, 0.5), (1.0, 0.1)], False
            ),
        }
        for side in ("left", "right"):
            for description, (samples, valid) in sequences.items():
                with self.subTest(side=side, description=description):
                    tracker = self.ready_tracker(wink_min_seconds=0.25)
                    outputs = [tracker.update(now, face(**{side: score})) for now, score in samples]
                    self.assertTrue(all(output.click is None for output in outputs[:-1]))
                    self.assertEqual(outputs[-1].click, side if valid else None)
                    self.assertIsNone(outputs[-1].position)

    def test_opposite_eye_or_both_eyes_cancel_a_pending_wink(self):
        for interruption in (face(right=0.9), face(left=0.9, right=0.9), face(left=0.9, right=0.5)):
            with self.subTest(interruption=interruption):
                tracker = self.ready_tracker()
                for now, sample in [
                    (0.10, face(left=0.9)), (0.22, face(left=0.9)),
                    (0.31, interruption), (0.39, face()), (0.48, face()), (0.56, face()),
                    (0.64, face(right=0.9)), (0.77, face(right=0.9)),
                ]:
                    self.assertIsNone(tracker.update(now, sample).click)
                self.assertEqual(tracker.update(0.91, face()).click, "right")

    def test_lost_or_invalid_face_discards_wink_and_rearms_with_open_eyes(self):
        for missing in (None, face(x=math.nan)):
            with self.subTest(missing=missing):
                tracker = self.ready_tracker(mirror=False)
                tracker.update(0.10, face(left=0.9))
                tracker.update(0.22, face(left=0.9))
                loss = tracker.update(0.31, missing)
                self.assertEqual(loss.state, "paused")
                self.assertTrue(loss.calibrated)
                self.assertIsNone(loss.position)
                self.assertIsNone(loss.click)

                for now, sample in [
                    (0.36, face(0.60, left=0.9)), (0.49, face(0.60, left=0.9)),
                    (0.52, face(0.60)), (0.60, face(0.60)),
                ]:
                    result = tracker.update(now, sample)
                    self.assertEqual(result.state, "rearming")
                    self.assertIsNone(result.position)
                    self.assertIsNone(result.click)
                self.assertIsNone(tracker.update(0.69, face(0.60)).click)
                resumed = tracker.update(0.72, face(0.60))
                self.assertEqual(resumed.state, "tracking")
                self.assertGreater(resumed.position[0], 0.5)
                tracker.update(0.78, face(right=0.9))
                tracker.update(0.90, face(right=0.9))
                self.assertEqual(tracker.update(1.05, face()).click, "right")

    def test_stale_sample_cannot_complete_a_wink(self):
        tracker = self.ready_tracker()
        tracker.update(0.10, face(left=0.9))
        tracker.update(0.22, face(left=0.9))
        stale_reopen = tracker.update(0.60, face())
        self.assertEqual(stale_reopen.state, "rearming")
        self.assertIsNone(stale_reopen.click)
        self.assertIsNone(stale_reopen.position)
        self.assertIsNone(tracker.update(0.70, face()).position)
        self.assertIsNone(tracker.update(0.77, face()).click)
        self.assert_centered(tracker.update(0.81, face()))

    def test_stale_sample_restarts_calibration_without_old_positions(self):
        tracker = Tracker(Settings(calibration_seconds=0.3, smoothing_seconds=0))
        tracker.update(0.0, face(0.2, 0.3))
        tracker.update(0.1, face(0.2, 0.3))
        for now in (0.50, 0.61, 0.72):
            self.assertFalse(tracker.update(now, face(0.75, 0.25)).calibrated)
        self.assert_centered(tracker.update(0.81, face(0.75, 0.25)))
        self.assert_centered(tracker.update(0.85, face(0.75, 0.25)))

    def test_face_jump_cancels_wink_and_requires_new_neutral(self):
        tracker = Tracker(Settings(calibration_seconds=0.3, smoothing_seconds=0))
        for now in (0.0, 0.1, 0.2):
            self.assertFalse(tracker.update(now, face()).calibrated)
        self.assert_centered(tracker.update(0.31, face()))
        self.assertEqual(tracker.update(0.40, face(left=0.9)).state, "wink")
        self.assertEqual(tracker.update(0.52, face(left=0.9)).state, "wink")

        handoff = tracker.update(0.66, face(0.76))
        self.assertEqual(handoff.state, "face_jump")
        self.assertEqual(handoff.calibration_progress, 0)
        self.assertIsNone(handoff.position)
        self.assertIsNone(handoff.click)
        for now in (0.70, 0.81, 0.92):
            result = tracker.update(now, face(0.76))
            self.assertEqual(result.state, "calibrating")
            self.assertIsNone(result.position)
            self.assertIsNone(result.click)
        self.assert_centered(tracker.update(1.01, face(0.76)))
        self.assert_centered(tracker.update(1.05, face(0.76)))

    def test_face_jump_uses_euclidean_displacement_and_configured_threshold(self):
        tracker = self.ready_tracker()
        self.assertEqual(tracker.update(0.08, face(0.65, 0.65)).state, "face_jump")
        self.assertEqual(tracker.update(0.16, face()).state, "face_jump")

        tolerant = self.ready_tracker(max_nose_jump=0.25)
        self.assertEqual(tolerant.update(0.08, face(0.75)).state, "tracking")
        for invalid in (0, -0.1, math.inf, math.nan):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    Settings(max_nose_jump=invalid)

    def test_missing_invalid_or_stale_samples_still_check_a_calibrated_face_jump(self):
        for gap in ("missing", "invalid", "stale"):
            with self.subTest(gap=gap):
                tracker = self.ready_tracker()
                if gap == "missing":
                    tracker.update(0.10, None)
                if gap == "invalid":
                    tracker.update(0.10, face(left=math.nan))
                now = 0.31 if gap == "stale" else 0.15
                result = tracker.update(now, face(0.76))
                self.assertEqual(result.state, "face_jump")
                self.assertFalse(result.calibrated)
                self.assertIsNone(result.position)
                self.assertIsNone(result.click)

    def test_reset_accepts_a_new_neutral_and_new_timeline(self):
        tracker = self.ready_tracker(mirror=False)
        self.assertGreater(tracker.update(0.1, face(0.7)).position[0], 0.5)
        tracker.reset()
        self.assert_centered(tracker.update(0.0, face(0.7)))
        self.assert_centered(tracker.update(0.1, face(0.7)))


if __name__ == "__main__":
    unittest.main()
