import unittest

from tracking import FaceSample, Settings, Tracker


def face(x=0.50, *, left=0.1, right=0.1):
    return FaceSample(x, 0.50, left, right)


class DwellTests(unittest.TestCase):
    def tracker(self, **overrides):
        options = {
            "mirror": False,
            "range_x": 0.2,
            "range_y": 0.2,
            "dead_zone": 0,
            "smoothing_seconds": 0,
            "calibration_seconds": 0,
            "rearm_seconds": 0,
            "dwell_seconds": 0.6,
            "dwell_radius": 0.02,
        }
        options.update(overrides)
        return Tracker(Settings(**options))

    def hold_without_click(self, tracker, sample, first_time, *times):
        for now in (first_time, *times):
            output = tracker.update(now, sample)
            self.assertIsNone(output.click, f"Unexpected click at {now:.2f}s")
        return output

    def begin_hold(self, tracker):
        self.hold_without_click(tracker, face(), 0.0)
        self.hold_without_click(tracker, face(0.54), 0.10, 0.11, 0.28, 0.46, 0.62)

    def test_startup_and_small_motion_do_not_arm_dwell(self):
        tracker = self.tracker()
        self.hold_without_click(tracker, face(), 0.0, 0.17, 0.34, 0.51, 0.68)
        # Maps to 0.025 desktop units, short of the twice-radius arm distance.
        output = self.hold_without_click(tracker, face(0.51), 0.85, 1.02, 1.19, 1.36, 1.53, 1.70)
        self.assertEqual(output.dwell_progress, 0)

    def test_finishing_calibration_away_from_its_average_does_not_arm_dwell(self):
        tracker = self.tracker(calibration_seconds=0.3)
        self.hold_without_click(tracker, face(0.49), 0.0, 0.10, 0.20)
        output = self.hold_without_click(tracker, face(0.55), 0.31, 0.48, 0.65, 0.82, 0.99, 1.16)
        self.assertTrue(output.calibrated)
        self.assertEqual(output.dwell_progress, 0)

    def test_jitter_inside_radius_clicks_once_and_rearms_only_after_enough_motion(self):
        tracker = self.tracker()
        self.hold_without_click(tracker, face(), 0.0)
        self.hold_without_click(tracker, face(0.54), 0.10, 0.11)
        self.hold_without_click(tracker, face(0.536), 0.29)
        progress = self.hold_without_click(tracker, face(0.544), 0.47).dwell_progress
        self.assertGreater(progress, 0)
        self.assertLess(progress, 1)
        self.hold_without_click(tracker, face(0.536), 0.65)

        clicked = tracker.update(0.72, face(0.54))
        self.assertEqual(clicked.click, "left")
        self.assertEqual(clicked.state, "tracking")
        self.assertEqual(clicked.dwell_progress, 1)
        self.assertIsNotNone(clicked.position)
        self.hold_without_click(tracker, face(0.54), 0.89, 1.06, 1.23, 1.40)

        # This movement leaves the click radius but stays within twice it.
        self.hold_without_click(tracker, face(0.551), 1.57, 1.74, 1.91, 2.08, 2.25)
        self.hold_without_click(tracker, face(0.57), 2.35, 2.36, 2.54, 2.72, 2.90)
        self.assertEqual(tracker.update(2.98, face(0.57)).click, "left")

    def test_cumulative_drift_restarts_the_timer_at_a_new_anchor(self):
        tracker = self.tracker()
        self.hold_without_click(tracker, face(), 0.0)
        self.hold_without_click(tracker, face(0.54), 0.10, 0.11)
        self.hold_without_click(tracker, face(0.546), 0.28)
        # Each increment fits the radius, but the second leaves the original anchor.
        self.hold_without_click(tracker, face(0.552), 0.46, 0.47, 0.64, 0.72, 0.89, 1.04)
        self.assertEqual(tracker.update(1.08, face(0.552)).click, "left")

    def test_stable_raw_target_does_not_click_before_the_smoothed_pointer_arrives(self):
        tracker = self.tracker(smoothing_seconds=1.2, dwell_seconds=0.3)
        self.hold_without_click(tracker, face(), 0.0)
        output = self.hold_without_click(tracker, face(0.56), 0.10, 0.27, 0.44, 0.61, 0.78)
        self.assertEqual(output.dwell_progress, 0)
        clicks = [tracker.update(0.95 + step * 0.17, face(0.56)).click for step in range(21)]
        self.assertEqual([click for click in clicks if click is not None], ["left"])

    def test_eye_closure_cancels_progress_and_reopening_is_never_a_wink_click(self):
        for closed in (face(0.54, left=0.9), face(0.54, right=0.9), face(0.54, left=0.9, right=0.9)):
            with self.subTest(closed=closed):
                tracker = self.tracker()
                self.begin_hold(tracker)
                output = self.hold_without_click(tracker, closed, 0.66, 0.80, 0.95)
                self.assertIsNone(output.position)
                self.assertEqual(output.dwell_progress, 0)
                self.hold_without_click(tracker, face(0.54), 0.98, 0.99, 1.15, 1.32, 1.49)
                self.assertEqual(tracker.update(1.61, face(0.54)).click, "left")

    def test_uncertain_eye_scores_do_not_block_dwell_calibration_or_click(self):
        tracker = self.tracker()
        baseline = face(left=0.42, right=0.38)
        target = face(0.54, left=0.55, right=0.39)
        self.assertTrue(tracker.update(0.0, baseline).calibrated)
        self.hold_without_click(tracker, target, 0.10, 0.28, 0.46, 0.62)
        self.assertEqual(tracker.update(0.72, target).click, "left")

    def test_loss_stale_frames_jump_and_reset_require_new_motion(self):
        for interruption in ("loss", "invalid", "stale", "jump", "reset"):
            with self.subTest(interruption=interruption):
                tracker = self.tracker()
                self.begin_hold(tracker)
                resume_x, resume_at = 0.54, 0.74
                if interruption == "loss":
                    self.assertEqual(tracker.update(0.66, None).state, "paused")
                elif interruption == "invalid":
                    self.assertEqual(tracker.update(0.66, face(float("nan"))).state, "paused")
                elif interruption == "stale":
                    resume_at = 0.94
                elif interruption == "jump":
                    resume_x = 0.80
                    jumped = tracker.update(0.66, face(resume_x))
                    self.assertEqual(jumped.state, "face_jump")
                    self.assertIsNone(jumped.click)
                else:
                    tracker.reset()

                output = self.hold_without_click(
                    tracker, face(resume_x), *(resume_at + delta for delta in (0, 0.17, 0.34, 0.51, 0.68, 0.85))
                )
                self.assertEqual(output.dwell_progress, 0)
                target = face(resume_x - 0.05)
                self.hold_without_click(
                    tracker, target, *(resume_at + delta for delta in (0.95, 0.96, 1.13, 1.30, 1.47))
                )
                self.assertEqual(tracker.update(resume_at + 1.58, target).click, "left")


if __name__ == "__main__":
    unittest.main()
