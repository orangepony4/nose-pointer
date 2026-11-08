from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import camera
from nose_pointer import DWELL_MODE, PointerApp
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
        self.camera = Mock()
        self.camera.thread.is_alive.return_value = True
        self.camera.stop_event.is_set.return_value = False
        self.clock = self.enterContext(patch("nose_pointer.monotonic"))

        pad = Mock()
        pad.winfo_width.return_value = 200
        pad.winfo_height.return_value = 150
        self.buttons = [Mock(), Mock()]
        with (
            patch.multiple("nose_pointer.tk", Frame=Mock(), Label=Mock(),
                           Canvas=Mock(return_value=pad), StringVar=StringValue),
            patch.multiple("nose_pointer.ttk", Style=Mock(), Button=Mock(side_effect=self.buttons),
                           Combobox=Mock(), Progressbar=Mock()),
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
        self.calibrate(2.1)
        for time in (2.5, 2.7, 2.9, 3.1, 3.3, 3.5, 3.72, 3.9):
            self.feed(time, MOVED_FACE)
        self.mouse.click.assert_called_once_with("left")
        self.app.pause()
        self.app.mode_picker.configure.assert_called_with(state="readonly")
        self.app.dwell_bar.configure.assert_called_with(value=0)

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
