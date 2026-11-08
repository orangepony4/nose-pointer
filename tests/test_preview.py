from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

import camera
from nose_pointer import DWELL_MODE, WINK_MODE, PointerApp
from tracking import FaceSample, Settings


OPEN_FACE = FaceSample(0.50, 0.50, 0.1, 0.1)
MOVED_FACE = FaceSample(0.55, 0.53, 0.1, 0.1)
LEFT_WINK = FaceSample(0.50, 0.50, 0.9, 0.1)


class StringValue:
    def __init__(self, value):
        self.value = value

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.root = Mock()
        self.root.winfo_fpixels.return_value = 96
        self.root.winfo_screenwidth.return_value = 1920
        self.root.winfo_screenheight.return_value = 1080
        self.mouse = Mock()
        self.mouse.emergency_requested.return_value = False
        self.mouse.recenter_requested.return_value = False
        self.mouse.position.return_value = (0.5, 0.5)

        def move_cursor(x, y):
            self.mouse.position.return_value = (x, y)
            return x, y

        self.mouse.move.side_effect = move_cursor
        self.camera = Mock()
        self.camera.thread.is_alive.return_value = True
        self.camera.stop_event.is_set.return_value = False
        self.clock = self.enterContext(patch("nose_pointer.monotonic"))

        pad = Mock()
        pad.winfo_width.return_value = 200
        pad.winfo_height.return_value = 150
        self.buttons = [Mock(), Mock(), Mock()]
        with (
            patch.multiple("nose_pointer.tk", Frame=Mock(), Label=Mock(),
                           Canvas=Mock(return_value=pad), StringVar=StringValue),
            patch.multiple("nose_pointer.ttk", Style=Mock(), Button=Mock(side_effect=self.buttons),
                           Combobox=Mock(side_effect=[Mock(), Mock()]), Progressbar=Mock()),
        ):
            self.app = PointerApp(self.root, self.mouse,
                                  Settings(calibration_seconds=0.3, smoothing_seconds=0),
                                  SimpleNamespace(camera=0, no_clicks=False, swap_buttons=False))
        with patch("nose_pointer.Camera", return_value=self.camera) as factory:
            self.app.toggle_camera()
        factory.assert_called_once_with(0)
        self.camera.start.assert_called_once_with()

    def feed(self, captured_at, sample=OPEN_FACE, *, wall_time=None):
        self.camera.snapshot.return_value = ((captured_at, sample), None)
        self.clock.return_value = captured_at if wall_time is None else wall_time
        self.app.poll()

    def calibrate(self, start):
        for offset in (0, 0.1, 0.2, 0.31):
            self.feed(start + offset)

    def arm_system_pointer(self):
        self.calibrate(0)
        self.app.toggle_pointer()
        self.assertTrue(self.app.active)
        self.calibrate(0.4)
        self.mouse.reset_mock()

    def assert_no_system_input(self):
        self.mouse.move.assert_not_called()
        self.mouse.click.assert_not_called()

    def select_quick_dwell(self):
        self.app.click_mode.set(DWELL_MODE)
        self.app.dwell_time.set("0,6")
        self.app.change_click_mode()

    def test_preview_tracks_and_recognizes_a_wink_without_system_input(self):
        self.app.toggle_pointer()
        self.assertFalse(self.app.active)
        self.calibrate(0)
        self.assertTrue(self.app.can_enable)
        self.feed(0.4, MOVED_FACE)
        self.assertNotEqual(self.app.position, (0.5, 0.5))
        self.feed(0.5, LEFT_WINK)
        self.feed(0.62, LEFT_WINK)
        self.feed(0.77)
        self.assertIn("Левый клик", self.app.last_gesture.get())
        self.assert_no_system_input()
        self.mouse.position.assert_not_called()

    def test_activation_uses_the_cursor_position_at_the_end_of_calibration(self):
        self.calibrate(0)
        self.app.toggle_pointer()
        self.mouse.position.return_value = (0.2, 0.7)
        for now in (0.4, 0.5, 0.6):
            self.feed(now)
        self.assert_no_system_input()
        self.mouse.position.return_value = (0.3, 0.6)
        self.feed(0.71)
        self.assert_no_system_input()
        self.feed(0.8)
        self.mouse.move.assert_called_once_with(0.3, 0.6)

    def test_f9_cancels_pending_wink_and_a_held_key_does_not_restart_calibration(self):
        self.arm_system_pointer()
        self.feed(0.80, LEFT_WINK)
        self.feed(0.92, LEFT_WINK)
        self.mouse.recenter_requested.return_value = True
        self.mouse.position.return_value = (0.25, 0.8)
        for now in (1.08, 1.18, 1.28, 1.4):
            self.feed(now)
        self.assert_no_system_input()
        self.assertTrue(self.app.tracker.calibrated)
        self.feed(1.5)
        self.mouse.move.assert_called_once_with(0.25, 0.8)
        self.mouse.click.assert_not_called()

    def test_empty_camera_error_disarms_and_reopening_returns_to_preview(self):
        self.arm_system_pointer()
        self.camera.snapshot.return_value = (None, "")
        self.camera.thread.is_alive.return_value = False
        self.app.poll()
        self.assertIsNone(self.app.camera)
        self.assertFalse(self.app.active)
        self.assertFalse(self.app.can_enable)
        self.assertIn("ошибкой", self.app.status.get())

        self.camera.thread.is_alive.return_value = True
        with patch("nose_pointer.Camera", return_value=self.camera):
            self.app.toggle_camera()
        self.calibrate(1.0)
        self.feed(1.4, MOVED_FACE)
        self.assertTrue(self.app.can_enable)
        self.assertFalse(self.app.active)
        self.assert_no_system_input()

    def test_cursor_read_failure_disarms_without_moving_or_clicking(self):
        self.calibrate(0)
        self.app.toggle_pointer()
        self.mouse.position.side_effect = OSError("Desktop unavailable")
        self.feed(0.4)
        self.assertFalse(self.app.active)
        self.assertIn("Desktop unavailable", self.app.last_gesture.get())
        self.assert_no_system_input()

    def test_switching_to_dwell_keeps_preview_local_and_clicks_left_only_when_enabled(self):
        self.calibrate(0)
        self.app.args.swap_buttons = True
        self.app.click_mode.set(DWELL_MODE)
        self.app.change_click_mode()
        self.assertFalse(self.app.can_enable)
        self.app.toggle_pointer()
        self.assertFalse(self.app.active)
        self.calibrate(0.4)
        self.feed(0.80, MOVED_FACE)
        for time in (1.00, 1.20, 1.40, 1.60, 1.80, 2.02):
            self.feed(time, MOVED_FACE)
        self.app.dwell_bar.configure.assert_called_with(value=100)
        self.assertIn("Левый клик", self.app.last_gesture.get())
        self.assert_no_system_input()

        self.app.toggle_pointer()
        self.assertTrue(self.app.active)
        self.app.mode_picker.configure.assert_called_with(state="disabled")
        self.app.delay_picker.configure.assert_called_with(state="disabled")
        self.calibrate(2.1)
        for time in (2.5, 2.7, 2.9, 3.1, 3.3, 3.5, 3.72, 3.9):
            self.feed(time, MOVED_FACE)
        self.mouse.click.assert_called_once_with("left")
        self.app.pause()
        self.app.mode_picker.configure.assert_called_with(state="readonly")
        self.app.delay_picker.configure.assert_called_with(state="readonly")
        self.app.dwell_bar.configure.assert_called_with(value=0)

    def test_dwell_delay_changes_in_preview_and_is_kept_when_switching_modes(self):
        self.app.click_mode.set(DWELL_MODE)
        self.app.change_click_mode()
        self.calibrate(0)
        self.feed(0.4, MOVED_FACE)
        self.feed(0.6, MOVED_FACE)
        self.app.dwell_time.set("0,8")
        self.app.change_click_mode()
        self.assertEqual(self.app.settings.dwell_seconds, 0.8)
        self.assertFalse(self.app.can_enable)
        self.app.dwell_bar.configure.assert_called_with(value=0)
        self.calibrate(0.7)
        for time in (1.1, 1.28, 1.46, 1.64, 1.82):
            self.feed(time, MOVED_FACE)
        self.assertNotIn("Левый клик", self.app.last_gesture.get())
        self.feed(1.91, MOVED_FACE)
        self.assertIn("Левый клик", self.app.last_gesture.get())
        self.assert_no_system_input()

        self.app.click_mode.set(WINK_MODE)
        self.app.change_click_mode()
        self.assertIsNone(self.app.settings.dwell_seconds)
        self.app.click_mode.set(DWELL_MODE)
        self.app.change_click_mode()
        self.assertEqual(self.app.settings.dwell_seconds, 0.8)

    def test_preview_right_dwell_discards_a_partial_timer_and_requires_fresh_motion(self):
        self.select_quick_dwell()
        self.calibrate(0)
        self.feed(0.4, MOVED_FACE)
        self.feed(0.6, MOVED_FACE)
        self.clock.return_value = 0.7
        self.app.toggle_right_dwell()
        self.assertIsNotNone(self.app.right_dwell_armed_at)
        self.feed(0.65, OPEN_FACE, wall_time=0.72)
        for time in (0.8, 0.98, 1.16, 1.34, 1.52):
            self.feed(time, MOVED_FACE)
        self.assertIsNotNone(self.app.right_dwell_armed_at)
        self.assert_no_system_input()

        for time in (1.7, 1.88, 2.06, 2.24, 2.32):
            self.feed(time, OPEN_FACE)
        self.assertIn("Правый клик", self.app.last_gesture.get())
        self.assertIsNone(self.app.right_dwell_armed_at)
        self.assert_no_system_input()

    def test_active_right_dwell_is_consumed_once_then_default_left_click_resumes(self):
        self.select_quick_dwell()
        self.arm_system_pointer()
        self.app.toggle_right_dwell()
        self.feed(0.8)
        for time in (0.9, 1.08, 1.26, 1.44, 1.52, 1.7):
            self.feed(time, MOVED_FACE)
        self.mouse.click.assert_called_once_with("right")
        self.assertIsNone(self.app.right_dwell_armed_at)

        for time in (1.8, 1.98, 2.16, 2.34, 2.42):
            self.feed(time)
        self.assertEqual(self.mouse.click.call_args_list, [call("right"), call("left")])

    def test_right_dwell_is_cleared_by_explicit_cancel_loss_gap_and_pause(self):
        self.select_quick_dwell()
        self.arm_system_pointer()
        self.app.toggle_right_dwell()
        self.app.toggle_right_dwell()
        self.assertIsNone(self.app.right_dwell_armed_at)

        self.app.toggle_right_dwell()
        self.feed(0.8)
        self.feed(0.91, None)
        self.assertIsNone(self.app.right_dwell_armed_at)

        for time in (1.03, 1.13, 1.23):
            self.feed(time)
        self.app.toggle_right_dwell()
        self.assertIsNotNone(self.app.right_dwell_armed_at)
        self.feed(1.61)
        self.assertIsNone(self.app.right_dwell_armed_at)

        self.feed(1.8)
        self.app.toggle_right_dwell()
        self.assertIsNotNone(self.app.right_dwell_armed_at)
        self.mouse.emergency_requested.return_value = True
        self.feed(1.9)
        self.assertFalse(self.app.active)
        self.assertIsNone(self.app.right_dwell_armed_at)
        self.mouse.click.assert_not_called()

    def test_right_button_release_cannot_arm_and_enable_clears_a_preview_choice(self):
        self.calibrate(0)
        self.app.toggle_right_dwell()
        self.assertIsNone(self.app.right_dwell_armed_at)
        self.select_quick_dwell()
        self.calibrate(0.4)

        self.app.toggle_right_dwell()
        self.assertIsNotNone(self.app.right_dwell_armed_at)
        self.assertEqual(self.app.cancel_right_dwell(), "break")
        self.assertIsNone(self.app.right_dwell_armed_at)
        self.app.cancel_right_dwell()
        self.assertIsNone(self.app.right_dwell_armed_at)

        self.app.toggle_right_dwell()
        self.app.toggle_pointer()
        self.assertTrue(self.app.active)
        self.assertIsNone(self.app.right_dwell_armed_at)
        self.assert_no_system_input()

    def test_duplicate_frames_and_stale_reopen_cannot_send_input(self):
        self.arm_system_pointer()
        self.feed(0.8, MOVED_FACE)
        self.feed(0.8, MOVED_FACE, wall_time=0.81)
        self.mouse.move.assert_called_once()
        self.mouse.reset_mock()

        self.feed(0.90, LEFT_WINK)
        self.feed(1.02, LEFT_WINK)
        self.feed(1.17, wall_time=1.43)
        self.assertTrue(self.app.feed_stale)
        self.assertFalse(self.app.can_enable)
        self.assert_no_system_input()

        self.feed(1.48)
        self.feed(1.58)
        self.assert_no_system_input()
        self.feed(1.65)
        self.mouse.move.assert_called_once()
        self.mouse.click.assert_not_called()
        self.feed(1.73, LEFT_WINK)
        self.feed(1.84, LEFT_WINK)
        self.feed(2.00)
        self.mouse.click.assert_called_once_with("left")

    def test_recovery_after_loss_keeps_an_externally_moved_cursor_in_place(self):
        self.arm_system_pointer()
        self.feed(0.80, MOVED_FACE)
        self.mouse.reset_mock()
        self.feed(0.90, None)
        self.mouse.position.return_value = (0.17, 0.78)
        self.feed(1.00)
        self.assert_no_system_input()
        self.mouse.position.assert_not_called()
        self.feed(1.16)
        self.assert_no_system_input()
        self.mouse.position.assert_called_once()
        self.assertTrue(self.app.active)
        self.assertFalse(self.app.tracker.calibrated)

        for now in (1.2, 1.3, 1.4):
            self.feed(now)
        self.mouse.position.return_value = (0.22, 0.72)
        self.feed(1.51)
        self.assertTrue(self.app.tracker.calibrated)
        self.assert_no_system_input()
        self.feed(1.6)
        self.mouse.move.assert_called_once_with(0.22, 0.72)
        self.mouse.click.assert_not_called()

    def test_frame_gap_without_a_paused_poll_also_checks_cursor(self):
        self.arm_system_pointer()
        self.feed(0.80, MOVED_FACE)
        self.mouse.reset_mock()
        self.mouse.position.return_value = (0.17, 0.78)
        self.feed(1.10)
        self.assertTrue(self.app.tracker.calibrated)
        self.assert_no_system_input()
        self.feed(1.26)
        self.assertFalse(self.app.tracker.calibrated)
        self.assert_no_system_input()

    def test_recovery_is_immediate_at_the_last_applied_pixel(self):
        self.arm_system_pointer()
        applied = (0.29, 0.67)
        self.mouse.move.side_effect = None
        self.mouse.move.return_value = applied
        self.feed(0.80, MOVED_FACE)
        self.assertNotEqual(self.app.position, applied)
        self.mouse.position.return_value = applied
        self.mouse.reset_mock()
        self.feed(0.90, None)
        self.feed(1.00)
        self.assert_no_system_input()
        self.feed(1.16)
        self.assertTrue(self.app.tracker.calibrated)
        self.mouse.position.assert_called_once()
        self.mouse.move.assert_called_once()
        self.mouse.click.assert_not_called()

    def test_emergency_pause_precedes_a_valid_wink_reopen(self):
        self.arm_system_pointer()
        self.feed(0.80, LEFT_WINK)
        self.feed(0.92, LEFT_WINK)
        self.mouse.emergency_requested.return_value = True
        self.feed(1.07)
        self.assertFalse(self.app.active)
        self.assert_no_system_input()

    def test_ambiguous_faces_disarm_until_calibrated_and_enabled_again(self):
        self.arm_system_pointer()
        self.feed(0.80, LEFT_WINK)
        self.feed(0.92, LEFT_WINK)
        self.feed(1.07, camera.AMBIGUOUS_FACE)
        self.assertFalse(self.app.active)
        self.assertFalse(self.app.can_enable)
        self.app.toggle_pointer()
        self.assertFalse(self.app.active)
        self.assert_no_system_input()

        self.calibrate(1.18)
        self.assertTrue(self.app.can_enable)
        self.assertFalse(self.app.active)
        self.assert_no_system_input()
        self.app.toggle_pointer()
        self.assertTrue(self.app.active)

    def test_abrupt_face_displacement_disarms_before_input(self):
        self.arm_system_pointer()
        self.feed(0.80, LEFT_WINK)
        self.feed(0.92, LEFT_WINK)
        self.feed(1.07, FaceSample(0.8, 0.5, 0.1, 0.1))
        self.assertFalse(self.app.active)
        self.assertFalse(self.app.can_enable)
        self.assert_no_system_input()


if __name__ == "__main__":
    unittest.main()
