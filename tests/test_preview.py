from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, Mock, call, patch

import camera
from nose_pointer import DWELL_MODE, MOTION_MODE, WINK_MODE, PointerApp
from tracking import FaceSample, Settings
from windows_mouse import (
    ControlSessionBusy, DisplayLayoutChanged, EmergencyPauseRequested, InputFrameExpired, PointerMoved, WindowsMouse,
)


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
        self.mouse.button_held.return_value = False
        self.mouse.position.return_value = (0.5, 0.5)

        def move_cursor(x, y, *, valid_until=None):
            self.mouse.position.return_value = (x, y)
            return x, y

        self.mouse.move.side_effect = move_cursor
        self.mouse.visible_position.side_effect = lambda x, y: (x, y)
        self.camera = Mock()
        self.camera.thread.is_alive.return_value = True
        self.camera.stop_event.is_set.return_value = False
        self.clock = self.enterContext(patch("nose_pointer.monotonic"))
        self.clock.return_value = 0.0
        self.save_language = self.enterContext(patch("nose_pointer.save_language"))
        self.save_preference = self.enterContext(patch("nose_pointer.save_preference"))

        self.app = self.create_app(Settings(calibration_seconds=0.3, smoothing_seconds=0))
        with patch("nose_pointer.Camera", return_value=self.camera) as factory:
            self.app.toggle_camera()
        factory.assert_called_once_with(0, max_sample_gap_seconds=self.app.settings.max_sample_gap_seconds)
        self.camera.start.assert_called_once_with()

    def create_app(self, settings, *, no_clicks=False):
        workspace = Mock()
        workspace.winfo_ismapped.return_value = False
        pad = Mock()
        pad.winfo_width.return_value = 200
        pad.winfo_height.return_value = 150
        self.buttons = [Mock(), Mock(), Mock()]
        with (
            patch.multiple("nose_pointer.tk", Frame=Mock(), Label=Mock(),
                           Canvas=Mock(side_effect=[workspace, pad]), StringVar=StringValue),
            patch.multiple("nose_pointer.ttk", Style=Mock(), Button=Mock(side_effect=self.buttons),
                           Combobox=Mock(side_effect=[Mock(), Mock(), Mock(), Mock(), Mock()]), Progressbar=Mock(),
                           Scrollbar=Mock(), Spinbox=Mock()),
        ):
            return PointerApp(self.root, self.mouse, settings,
                              SimpleNamespace(camera=0, no_clicks=no_clicks, swap_buttons=False))

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

    def attach_camera_feed(self):
        source = camera.Camera(0, max_sample_gap_seconds=self.app.settings.max_sample_gap_seconds)
        source.thread = Mock()
        source.thread.is_alive.return_value = True
        self.app.camera = source
        return source

    def test_unpolled_opposite_eye_interrupts_a_pending_wink(self):
        right_wink = replace(LEFT_WINK, left_blink=0.1, right_blink=0.9)
        for wink, interrupted in (
            (LEFT_WINK, replace(LEFT_WINK, right_blink=0.9)),
            (right_wink, replace(right_wink, left_blink=0.25)),
        ):
            with self.subTest(wink=wink):
                self.app.disable_input()
                self.app.camera = self.camera
                self.app.apply_tracking_settings(replace(self.app.settings, open_threshold=0.20))
                self.arm_system_pointer()
                self.feed(0.80, wink)
                self.feed(0.92, wink)
                source = self.attach_camera_feed()
                source.publish(0.98, interrupted)
                source.publish(1.08, OPEN_FACE)
                self.clock.return_value = 1.08
                self.app.poll()
                self.app.poll()
                self.assertTrue(self.app.active)
                self.assert_no_system_input()

    def test_unpolled_eye_closure_resets_dwell_progress(self):
        self.select_quick_dwell()
        self.app.apply_tracking_settings(replace(self.app.settings, closed_threshold=0.60))
        self.arm_system_pointer()
        for now in (0.80, 0.96, 1.12, 1.28):
            self.feed(now, MOVED_FACE)
        source = self.attach_camera_feed()
        source.publish(1.36, replace(MOVED_FACE, right_blink=0.60))
        source.publish(1.42, MOVED_FACE)
        self.clock.return_value = 1.42
        self.app.poll()
        self.app.poll()
        self.assertTrue(self.app.active)
        self.mouse.click.assert_not_called()
        self.assertEqual(self.app.dwell_bar.configure.call_args.kwargs["value"], 0)

        for now in (1.58, 1.74, 1.90, 2.06, 2.20):
            source.publish(now, MOVED_FACE)
            self.clock.return_value = now
            self.app.poll()
        self.mouse.click.assert_called_once_with("left", expected_position=self.app.last_applied_position, valid_until=ANY)

    def test_unpolled_selected_eye_closure_resets_one_eye_dwell(self):
        self.select_quick_dwell()
        self.app.apply_tracking_settings(replace(self.app.settings, dwell_eye="right"))
        self.arm_system_pointer()
        target = replace(MOVED_FACE, left_blink=0.95)
        for now in (0.80, 0.96, 1.12, 1.28):
            self.feed(now, target)
        source = self.attach_camera_feed()
        source.publish(1.36, replace(target, right_blink=0.95))
        source.publish(1.42, target)
        self.clock.return_value = 1.42
        self.app.poll()
        self.app.poll()
        self.assertTrue(self.app.active)
        self.mouse.click.assert_not_called()
        self.assertEqual(self.app.dwell_bar.configure.call_args.kwargs["value"], 0)

    def test_unpolled_nose_displacement_uses_the_calibrated_safety_limit(self):
        self.app.apply_tracking_settings(replace(self.app.settings, max_nose_jump=0.125))
        for nose_x, jumped in ((0.625, False), (0.65625, True)):
            with self.subTest(nose_x=nose_x):
                self.app.disable_input()
                self.app.camera = self.camera
                self.arm_system_pointer()
                self.feed(0.80, LEFT_WINK)
                self.feed(0.92, LEFT_WINK)
                source = self.attach_camera_feed()
                source.publish(0.94, LEFT_WINK)
                source.publish(0.98, replace(LEFT_WINK, nose_x=nose_x))
                source.publish(1.08, OPEN_FACE)
                self.clock.return_value = 1.08
                self.app.poll()
                self.app.poll()

                if jumped:
                    self.assert_no_system_input()
                    self.assertFalse(self.app.active)
                    self.assertEqual(self.app.safety_notice, "safety_jump")
                    self.mouse.end_control.assert_called_once_with()
                else:
                    self.assertTrue(self.app.active)
                    self.mouse.click.assert_called_once_with(
                        "left", expected_position=self.app.last_applied_position, valid_until=ANY,
                    )

    def test_unpolled_nose_displacement_does_not_interrupt_practice(self):
        source = self.attach_camera_feed()
        far = replace(OPEN_FACE, nose_x=0.78)
        for timestamp, sample in ((0.05, OPEN_FACE), (0.10, far), (0.15, OPEN_FACE)):
            source.publish(timestamp, sample)
        self.clock.return_value = 0.15
        self.app.poll()
        self.assertFalse(self.app.tracker.calibrated)
        self.assertEqual(self.app.safety_notice, "")

        for timestamp in (0.25, 0.35, 0.46):
            source.publish(timestamp, OPEN_FACE)
            self.clock.return_value = timestamp
            self.app.poll()
        for timestamp, sample in ((0.50, OPEN_FACE), (0.56, far), (0.64, OPEN_FACE)):
            source.publish(timestamp, sample)
        self.clock.return_value = 0.64
        self.app.poll()
        self.assertTrue(self.app.can_enable)
        self.assertFalse(self.app.active)
        self.assertEqual(self.app.safety_notice, "")
        self.assert_no_system_input()

    def test_motion_only_uses_the_latest_frame_when_unpolled_eyes_close(self):
        self.app.click_mode.set(self.app.text(MOTION_MODE))
        self.app.change_click_mode()
        self.arm_system_pointer()
        source = self.attach_camera_feed()
        source.publish(0.80, replace(OPEN_FACE, nose_x=0.45, left_blink=0.9, right_blink=0.9))
        source.publish(0.92, MOVED_FACE)
        self.clock.return_value = 0.92
        self.app.poll()
        self.app.poll()
        self.assertTrue(self.app.active)
        self.assertEqual(self.app.last_frame, 0.92)
        self.mouse.move.assert_called_once()
        self.mouse.click.assert_not_called()

    def test_recenter_discards_queued_face_interruptions_before_a_new_wink(self):
        self.arm_system_pointer()
        self.feed(0.80, LEFT_WINK)
        self.feed(0.92, LEFT_WINK)
        source = self.attach_camera_feed()
        source.publish(0.94, LEFT_WINK)
        source.publish(0.98, replace(LEFT_WINK, nose_x=0.78, right_blink=0.9))
        source.publish(1.08, OPEN_FACE)
        self.clock.return_value = 1.08
        self.mouse.recenter_requested.return_value = True
        self.app.poll()
        self.mouse.recenter_requested.return_value = False
        self.assertEqual(self.app.last_frame, 1.08)
        self.assert_no_system_input()

        for now, sample in ((1.20, OPEN_FACE), (1.31, OPEN_FACE), (1.40, OPEN_FACE),
                            (1.48, LEFT_WINK), (1.60, LEFT_WINK), (1.72, OPEN_FACE)):
            source.publish(now, sample)
            self.clock.return_value = now
            self.app.poll()
        self.assertTrue(self.app.active)
        self.mouse.click.assert_called_once_with("left", expected_position=self.app.last_applied_position, valid_until=ANY)

    def test_stopping_camera_discards_queued_blink_evidence(self):
        self.arm_system_pointer()
        self.feed(0.80, LEFT_WINK)
        self.feed(0.92, LEFT_WINK)
        source = self.attach_camera_feed()
        source.publish(0.98, replace(LEFT_WINK, right_blink=0.9))
        source.publish(1.08, OPEN_FACE)
        self.app.toggle_camera()
        self.assertTrue(source.stop_event.is_set())
        source.thread.is_alive.return_value = False
        self.clock.return_value = 1.08
        self.app.poll()
        self.assertFalse(self.app.active)
        self.assertIsNone(self.app.camera)
        self.assert_no_system_input()
        self.assertEqual(source.snapshot(interrupts_gesture=lambda sample: sample.right_blink > 0.3),
                         ((1.08, OPEN_FACE), None))

    def test_unpolled_invalid_camera_sample_cancels_wink_before_reopen(self):
        self.arm_system_pointer()
        self.feed(0.8, LEFT_WINK)
        self.feed(0.92, LEFT_WINK)
        camera_feed = camera.Camera(0)
        camera_feed.thread = Mock()
        camera_feed.thread.is_alive.return_value = True
        self.app.camera = camera_feed
        camera_feed.publish(0.98, replace(LEFT_WINK, nose_x=float("nan")))
        camera_feed.publish(1.07, OPEN_FACE)
        self.clock.return_value = 1.07
        self.app.poll()
        self.app.poll()
        self.assert_no_system_input()
        self.assertTrue(self.app.active)

    def select_quick_dwell(self):
        self.app.click_mode.set(self.app.text(DWELL_MODE))
        self.app.dwell_time.set("0.6")
        self.app.change_click_mode()

    def choose_dwell_eye(self, side):
        picker = self.app.dwell_eye_picker
        self.app.dwell_eye.set(self.app.text(f"dwell_eye_{side}"))
        selected = next(binding.args[1] for binding in picker.bind.call_args_list
                        if binding.args[0] == "<<ComboboxSelected>>")
        selected(SimpleNamespace(widget=picker))

    def test_gui_eye_choice_clears_pending_dwell_and_uses_fresh_frames(self):
        self.select_quick_dwell()
        self.calibrate(0)
        self.app.toggle_right_dwell()
        self.feed(0.40)
        self.feed(0.50, MOVED_FACE)
        self.feed(0.65, MOVED_FACE)
        self.assertIsNotNone(self.app.right_dwell_armed_at)
        self.assertGreater(self.app.dwell_bar.configure.call_args.kwargs["value"], 0)
        self.save_preference.reset_mock()

        self.clock.return_value = 0.70
        self.choose_dwell_eye("right")
        self.assertEqual(self.app.settings.dwell_eye, "right")
        self.assertIsNone(self.app.right_dwell_armed_at)
        self.assertEqual(self.app.dwell_bar.configure.call_args.kwargs["value"], 0)
        self.assertFalse(self.app.can_enable)
        self.save_preference.assert_not_called()

        right_open = replace(OPEN_FACE, left_blink=0.95)
        self.feed(0.68, right_open, wall_time=0.71)
        for now in (0.72, 0.82, 0.92, 1.00):
            self.feed(now, right_open)
        self.assertFalse(self.app.can_enable)
        self.feed(1.03, right_open)
        self.assertTrue(self.app.can_enable)
        self.assert_no_system_input()

    def test_gui_eye_choice_is_locked_while_mouse_control_is_enabled(self):
        self.select_quick_dwell()
        self.choose_dwell_eye("left")
        self.arm_system_pointer()
        self.app.dwell_eye_picker.configure.assert_called_with(state="disabled")
        self.choose_dwell_eye("right")
        self.assertEqual(self.app.settings.dwell_eye, "left")
        self.assertEqual(self.app.dwell_eye.get(), self.app.text("dwell_eye_left"))
        self.assertTrue(self.app.tracker.calibrated)

        self.app.pause()
        self.app.dwell_eye_picker.configure.assert_called_with(state="readonly")
        self.choose_dwell_eye("both")
        self.assertIsNone(self.app.settings.dwell_eye)
        self.assert_no_system_input()

    def test_mode_choice_recalibrates_from_fresh_frames(self):
        self.calibrate(0)
        self.clock.return_value = 0.40
        self.select_quick_dwell()
        self.feed(0.39, wall_time=0.41)
        for now in (0.42, 0.52, 0.62, 0.70):
            self.feed(now)
        self.assertFalse(self.app.can_enable)
        self.feed(0.73)
        self.assertTrue(self.app.can_enable)
        self.assert_no_system_input()

    def test_settings_choosers_save_only_the_value_explicitly_changed(self):
        self.app.sensitivity.set(self.app.text("sensitivity_high"))
        self.app.change_sensitivity()
        self.select_quick_dwell()
        self.app.dwell_time.set("0.8")
        self.app.change_click_mode(SimpleNamespace(widget=self.app.delay_picker))
        self.app.language_choice.set("Русский")
        self.app.change_language()
        self.assertEqual(self.save_preference.mock_calls, [
            call("sensitivity", "sensitivity_high"), call("click-mode", DWELL_MODE), call("dwell-ms", 800)
        ])

    def test_custom_launch_sensitivity_is_never_saved_as_a_preset(self):
        app = self.create_app(Settings(range_x=0.08))
        app.sensitivity.set(app.text("sensitivity_high"))
        app.change_sensitivity()
        self.save_preference.reset_mock()
        app.sensitivity.set(app.text("sensitivity_custom"))
        app.change_sensitivity()
        self.assertEqual(app.settings.range_x, 0.08)
        self.save_preference.assert_not_called()

    def test_calibration_status_shows_progress_and_resets_on_interruption(self):
        self.feed(0)
        self.assertIn("Calibration 0%", self.app.status.get())
        self.feed(0.1)
        self.assertIn("Calibration 30%", self.app.status.get())
        self.assertFalse(self.app.can_enable)
        self.app.language_choice.set("Русский")
        self.app.change_language()
        self.assertIn("Калибровка 30%", self.app.status.get())

        self.feed(0.15, LEFT_WINK)
        self.assertIn("Калибровка 0%", self.app.status.get())
        self.calibrate(0.2)
        self.assertTrue(self.app.can_enable)
        self.assertIn("Лицо в кадре", self.app.status.get())
        self.assert_no_system_input()

    def test_language_switch_preserves_tracking_and_preview_selections(self):
        self.select_quick_dwell()
        self.app.sensitivity.set("High")
        self.app.change_sensitivity()
        self.calibrate(0)
        self.feed(0.4, MOVED_FACE)
        self.app.toggle_right_dwell()
        tracker, settings = self.app.tracker, self.app.settings
        position, armed_at = self.app.position, self.app.right_dwell_armed_at

        self.app.language_choice.set("Русский")
        self.app.change_language()
        self.assertEqual(self.app.language, "ru")
        self.assertEqual(self.app.click_mode.get(), "Задержка курсора")
        self.assertEqual(self.app.sensitivity.get(), "Высокая")
        self.assertEqual(self.app.dwell_time.get(), "0,6")
        self.assertIn("Следующий клик — правый", self.app.last_gesture.get())
        self.assertIs(self.app.tracker, tracker)
        self.assertIs(self.app.settings, settings)
        self.assertEqual((self.app.position, self.app.right_dwell_armed_at), (position, armed_at))
        self.assertTrue(self.app.can_enable)
        self.assert_no_system_input()

        self.app.language_choice.set("English")
        self.app.change_language()
        self.assertEqual(self.app.language, "en")
        self.assertEqual(self.app.dwell_time.get(), "0.6")
        self.assertIn("Next click is right", self.app.last_gesture.get())
        self.assertEqual(self.save_language.call_args_list, [call("ru"), call("en")])
        self.assert_no_system_input()

    def test_language_control_is_locked_during_system_input(self):
        self.arm_system_pointer()
        self.app.language_picker.configure.assert_called_with(state="disabled")
        self.app.language_choice.set("Русский")
        self.app.change_language()
        self.assertEqual(self.app.language, "en")
        self.assertEqual(self.app.language_choice.get(), "English")
        self.save_language.assert_not_called()

        self.app.pause()
        self.app.language_picker.configure.assert_called_with(state="readonly")
        self.app.language_choice.set("Русский")
        self.app.change_language()
        self.assertEqual(self.app.language, "ru")
        self.assertIn("Пауза", self.app.status.get())
        self.assert_no_system_input()

    def test_language_switch_retranslates_a_safety_notice_and_a_camera_error(self):
        self.calibrate(0)
        self.feed(0.4, camera.AMBIGUOUS_FACE)
        self.feed(0.5)
        self.assertIn("Multiple faces detected", self.app.status.get())
        self.assertEqual(self.app.footer_notice.get(), "Multiple faces detected.")
        self.app.language_choice.set("Русский")
        self.app.change_language()
        self.assertIn("В кадре несколько лиц", self.app.status.get())
        self.assertIn("Смотрите прямо", self.app.status.get())
        self.assertEqual(self.app.footer_notice.get(), "В кадре несколько лиц.")

        self.camera.snapshot.return_value = (None, camera.CameraFailure("camera_unavailable"))
        self.camera.thread.is_alive.return_value = False
        self.app.poll()
        self.assertIn("Камеру открыть не удалось", self.app.status.get())
        self.assertEqual(self.app.footer_notice.get(), "Камеру открыть не удалось.")
        self.app.language_choice.set("English")
        self.app.change_language()
        self.assertIn("Could not open the camera", self.app.status.get())
        self.assertEqual(self.app.footer_notice.get(), "Could not open the camera.")
        self.assert_no_system_input()

    def test_sensitivity_increases_travel_and_clears_pending_gestures(self):
        self.select_quick_dwell()
        self.calibrate(0)
        self.feed(0.4, MOVED_FACE)
        standard_x = self.app.position[0]
        self.app.toggle_right_dwell()
        self.assertIsNotNone(self.app.right_dwell_armed_at)

        self.app.sensitivity.set("High")
        self.app.change_sensitivity()
        self.assertIsNone(self.app.right_dwell_armed_at)
        self.assertEqual(self.app.settings.dwell_seconds, 0.6)
        self.assertFalse(self.app.can_enable)
        self.assertEqual(self.app.position, (0.5, 0.5))
        self.calibrate(0.5)
        self.feed(0.9, MOVED_FACE)
        self.assertLess(self.app.position[0], standard_x)
        self.assert_no_system_input()

    def test_sensitivity_is_locked_while_the_system_pointer_is_active(self):
        self.arm_system_pointer()
        self.app.sensitivity_picker.configure.assert_called_with(state="disabled")
        tracker = self.app.tracker
        self.app.sensitivity.set("Low")
        self.app.change_sensitivity()
        self.assertIs(self.app.tracker, tracker)
        self.app.pause()
        self.app.sensitivity_picker.configure.assert_called_with(state="readonly")

    def test_custom_ranges_are_selectable_again_even_with_clicks_disabled(self):
        settings = replace(self.app.settings, range_x=0.045, range_y=0.075, motion_only=True)
        self.app = self.create_app(settings, no_clicks=True)
        self.assertEqual(self.app.sensitivity.get(), "Custom")
        self.app.sensitivity.set("Standard")
        self.app.change_sensitivity()
        self.assertEqual(self.app.settings.range_x, Settings.range_x)
        self.assertEqual(self.app.settings.range_y, Settings.range_y)
        self.app.sensitivity.set("Custom")
        self.app.change_sensitivity()
        self.assertEqual(self.app.settings, settings)

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
        self.assertIn("Left click", self.app.last_gesture.get())
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
        self.mouse.move.assert_called_once_with(0.3, 0.6, valid_until=ANY)

    def test_enable_accepts_a_ready_frame_at_the_freshness_boundary(self):
        self.calibrate(0)
        self.clock.return_value = 0.31 + self.app.settings.max_sample_gap_seconds
        self.app.toggle_pointer()
        self.assertTrue(self.app.active)
        self.assert_no_system_input()

    def test_stale_preview_enable_requires_new_calibration_and_explicit_retry(self):
        self.calibrate(0)
        self.assertTrue(self.app.can_enable)
        self.clock.return_value = 0.31 + self.app.settings.max_sample_gap_seconds + 0.001
        self.app.toggle_pointer()
        self.assertFalse(self.app.active)
        self.assertFalse(self.app.can_enable)
        self.assertFalse(self.app.tracker.calibrated)
        self.assertEqual(self.app.safety_notice, "safety_stale_preview")
        self.assert_no_system_input()

        self.feed(0.31, wall_time=0.6)
        self.app.toggle_pointer()
        self.assertFalse(self.app.active)
        self.calibrate(0.7)
        self.assertTrue(self.app.can_enable)
        self.assertFalse(self.app.active)
        self.assert_no_system_input()
        self.mouse.position.assert_not_called()

        self.app.toggle_pointer()
        self.assertTrue(self.app.active)
        self.assertFalse(self.app.safety_notice)
        self.calibrate(1.1)
        self.feed(1.5, MOVED_FACE)
        self.mouse.move.assert_called_once()
        self.mouse.click.assert_not_called()

    def test_enable_requires_a_tracking_face_and_stays_off_after_loss(self):
        self.app.toggle_pointer()
        self.assertFalse(self.app.active)
        self.calibrate(0)
        self.assertTrue(self.app.can_enable)
        self.feed(0.4, None)
        self.app.toggle_pointer()
        self.assertFalse(self.app.active)
        self.assertFalse(self.app.can_enable)
        self.assert_no_system_input()

    def test_f9_cancels_pending_wink_and_a_held_key_does_not_restart_calibration(self):
        self.arm_system_pointer()
        self.feed(0.80, LEFT_WINK)
        self.feed(0.92, LEFT_WINK)
        self.mouse.recenter_requested.return_value = True
        self.mouse.position.return_value = (0.25, 0.8)
        for now, y in [(1.08, 0.50), (1.18, 0.52), (1.28, 0.57), (1.4, 0.60)]:
            self.feed(now, replace(OPEN_FACE, nose_y=y))
        self.assert_no_system_input()
        self.assertTrue(self.app.tracker.calibrated)
        self.feed(1.5, replace(OPEN_FACE, nose_y=0.60))
        self.mouse.move.assert_called_once_with(0.25, 0.8, valid_until=ANY)
        self.mouse.click.assert_not_called()

    def test_enabling_mouse_and_f9_wait_for_frames_captured_during_calibration(self):
        self.calibrate(0)
        self.feed(0.50)
        self.feed(0.67)
        self.feed(0.76)
        self.clock.return_value = 1.0
        self.app.toggle_pointer()
        self.assertTrue(self.app.active)
        self.assert_calibration_starts_at_request(1.0)

        self.feed(1.59)
        self.feed(1.76)
        self.clock.return_value = 2.0
        shortcut = next(binding.args[1] for binding in self.root.bind.call_args_list if binding.args[0] == "<F9>")
        shortcut(None)
        self.assertTrue(self.app.active)
        self.assert_calibration_starts_at_request(2.0)

    def assert_calibration_starts_at_request(self, requested_at):
        self.mouse.reset_mock()
        self.feed(requested_at - 0.20, MOVED_FACE, wall_time=requested_at + 0.01)
        self.feed(requested_at, wall_time=requested_at + 0.02)
        self.feed(requested_at + 0.11)
        self.feed(requested_at + 0.13)
        self.assertFalse(self.app.tracker.calibrated)
        self.assert_no_system_input()

        self.feed(requested_at + self.app.settings.calibration_seconds)
        self.assertTrue(self.app.tracker.calibrated)
        self.assert_no_system_input()
        self.feed(requested_at + 0.39, MOVED_FACE)
        self.mouse.move.assert_called_once()
        self.mouse.click.assert_not_called()

    def test_focused_f9_recalibrates_once_and_does_not_send_the_pending_wink(self):
        shortcut = next(binding.args[1] for binding in self.root.bind.call_args_list if binding.args[0] == "<F9>")
        self.calibrate(0)
        shortcut(None)
        self.assertTrue(self.app.can_enable)
        self.assertTrue(self.app.tracker.calibrated)
        self.app.toggle_pointer()
        self.calibrate(0.4)
        self.mouse.reset_mock()

        self.feed(0.80, LEFT_WINK)
        self.feed(0.92, LEFT_WINK)
        with patch.object(self.app, "recenter", wraps=self.app.recenter) as recenter:
            shortcut(None)
            shortcut(None)
            self.mouse.recenter_requested.return_value = True
            self.feed(1.07)
            self.feed(1.18)
        recenter.assert_called_once_with()
        self.assertTrue(self.app.active)
        self.assertFalse(self.app.tracker.calibrated)
        self.assert_no_system_input()

    def test_focused_f9_honors_a_held_emergency_key(self):
        self.arm_system_pointer()
        self.feed(0.80, LEFT_WINK)
        self.feed(0.92, LEFT_WINK)
        shortcut = next(binding.args[1] for binding in self.root.bind.call_args_list if binding.args[0] == "<F9>")
        self.mouse.emergency_requested.return_value = True
        with patch.object(self.app, "recenter", wraps=self.app.recenter) as recenter:
            shortcut(None)
        recenter.assert_not_called()
        self.assertFalse(self.app.active)
        self.feed(1.07)
        self.assert_no_system_input()

    def test_empty_camera_error_disarms_and_reopening_returns_to_preview(self):
        self.arm_system_pointer()
        self.camera.snapshot.return_value = (None, camera.CameraFailure("camera_error"))
        self.camera.thread.is_alive.return_value = False
        self.app.poll()
        self.assertIsNone(self.app.camera)
        self.assertFalse(self.app.active)
        self.assertFalse(self.app.can_enable)
        self.assertIn("error", self.app.status.get())

        self.camera.thread.is_alive.return_value = True
        with patch("nose_pointer.Camera", return_value=self.camera):
            self.app.toggle_camera()
        self.calibrate(1.0)
        self.feed(1.4, MOVED_FACE)
        self.assertTrue(self.app.can_enable)
        self.assertFalse(self.app.active)
        self.assert_no_system_input()

    def test_camera_number_can_change_after_a_failed_open_or_a_completed_stop(self):
        self.app.camera_picker.configure.assert_called_with(state="disabled")
        self.camera.snapshot.return_value = (None, camera.CameraFailure("camera_unavailable"))
        self.camera.thread.is_alive.return_value = False
        self.app.poll()
        self.app.camera_picker.configure.assert_called_with(state="normal")
        self.assertIsNone(self.app.camera)
        self.assertIn("Try another camera number", self.app.status.get())

        other_camera = Mock()
        other_camera.thread.is_alive.return_value = True
        other_camera.snapshot.return_value = (None, None)
        self.app.camera_index.set(" 1 ")
        with patch("nose_pointer.Camera", return_value=other_camera) as factory:
            self.app.toggle_camera()
            factory.assert_called_once_with(1, max_sample_gap_seconds=self.app.settings.max_sample_gap_seconds)
            other_camera.start.assert_called_once_with()
            self.assertEqual(self.app.camera_index.get(), "1")
            self.app.camera_picker.configure.assert_called_with(state="disabled")
            self.app.toggle_camera()
            other_camera.stop.assert_called_once_with()
            factory.assert_called_once_with(1, max_sample_gap_seconds=self.app.settings.max_sample_gap_seconds)
            self.app.camera_picker.configure.assert_called_with(state="disabled")

        other_camera.thread.is_alive.return_value = False
        self.app.poll()
        self.app.camera_picker.configure.assert_called_with(state="normal")
        self.assertIsNone(self.app.camera)
        self.assert_no_system_input()
        self.save_preference.assert_not_called()

    def test_remembers_a_changed_camera_only_after_it_calibrates_in_practice(self):
        def finish_camera(error=None):
            self.camera.snapshot.return_value = (None, error)
            self.camera.thread.is_alive.return_value = False
            self.app.poll()
            self.assertIsNone(self.app.camera)

        def open_camera(index):
            self.camera.thread.is_alive.return_value = True
            self.app.camera_index.set(str(index))
            with patch("nose_pointer.Camera", return_value=self.camera) as factory:
                self.app.toggle_camera()
            factory.assert_called_once_with(index, max_sample_gap_seconds=self.app.settings.max_sample_gap_seconds)

        self.calibrate(0)
        finish_camera()
        open_camera(1)
        finish_camera(camera.CameraFailure("camera_unavailable"))
        self.save_preference.assert_not_called()

        open_camera(1)
        self.feed(1.0)
        self.save_preference.assert_not_called()
        self.calibrate(1.1)
        self.save_preference.assert_called_once_with("camera", 1)
        self.feed(1.5)
        self.save_preference.assert_called_once_with("camera", 1)

        finish_camera()
        open_camera(0)
        self.calibrate(2.0)
        self.assertEqual(self.save_preference.call_args_list, [call("camera", 1), call("camera", 0)])
        self.assert_no_system_input()

    def test_keyboard_action_activates_once_on_release_and_respects_button_changes(self):
        button = self.app.camera_button
        self.root.focus_get.return_value = button
        button.instate.return_value = True
        button.cget.return_value = "Open camera"
        bindings = dict(call.args for call in button.bind.call_args_list)
        for key in ("Return", "KP_Enter", "space"):
            with self.subTest(key=key):
                press = bindings[f"<KeyPress-{key}>"]
                release = bindings[f"<KeyRelease-{key}>"]
                event = SimpleNamespace(widget=button, keysym=key)
                press(event)
                press(event)
                button.invoke.assert_not_called()
                release(event)
                release(event)
                button.invoke.assert_called_once_with()
                button.invoke.reset_mock()

                press(event)
                button.instate.return_value = False
                release(event)
                button.invoke.assert_not_called()
                button.instate.return_value = True
                press(event)
                button.cget.return_value = "Turn off camera"
                release(event)
                button.invoke.assert_not_called()
                button.cget.return_value = "Open camera"

                press(event)
                self.app.configure_action_button(button, state="disabled")
                self.app.configure_action_button(button, state="normal")
                press(event)
                release(event)
                button.invoke.assert_not_called()

                button.instate.return_value = False
                press(event)
                button.instate.return_value = True
                press(event)
                release(event)
                button.invoke.assert_not_called()

    def test_keyboard_action_focus_change_disarms_the_original_press_and_any_repeat(self):
        camera_button, pointer_button = self.app.camera_button, self.app.pointer_button
        self.root.tk.call.return_value = "."
        pointer_button.master = None
        for button in (camera_button, pointer_button):
            button.instate.return_value = True
        for key in ("Return", "space"):
            with self.subTest(key=key):
                self.root.focus_get.return_value = camera_button
                self.app.press_button_key(SimpleNamespace(widget=camera_button, keysym=key))
                self.app.cancel_button_key(SimpleNamespace(widget=camera_button))
                self.root.after_idle.call_args.args[0]()
                self.root.focus_get.return_value = pointer_button
                event = SimpleNamespace(widget=pointer_button, keysym=key)
                for binding in self.root.bind.call_args_list:
                    if binding.args[0] == "<FocusIn>":
                        binding.args[1](event)
                self.app.press_button_key(event)
                self.app.release_button_key(event)
                camera_button.invoke.assert_not_called()
                pointer_button.invoke.assert_not_called()
                self.app.press_button_key(event)
                self.app.release_button_key(event)
                pointer_button.invoke.assert_called_once_with()
                pointer_button.invoke.reset_mock()
        self.mouse.action_key_held.assert_not_called()

    def test_action_keys_recover_after_focus_leaves_the_window(self):
        button = self.app.camera_button
        button.instate.return_value = True
        button.cget.return_value = "Turn off camera"
        button.master = None
        self.root.tk.call.return_value = ""

        for key in ("Return", "KP_Enter", "space"):
            for still_held in (True, False):
                with self.subTest(key=key, still_held=still_held):
                    button.invoke.reset_mock()
                    self.mouse.action_key_held.reset_mock()
                    event = SimpleNamespace(widget=button, keysym=key)
                    self.root.focus_get.return_value = button
                    self.app.press_button_key(event)
                    self.root.focus_get.return_value = None
                    self.app.cancel_button_key(event)
                    self.root.after_idle.call_args.args[0]()
                    self.mouse.action_key_held.assert_not_called()

                    self.root.focus_get.return_value = button
                    self.mouse.action_key_held.return_value = still_held
                    for binding in self.root.bind.call_args_list:
                        if binding.args[0] == "<FocusIn>":
                            binding.args[1](event)

                    self.app.press_button_key(event)
                    self.app.release_button_key(event)
                    if still_held:
                        button.invoke.assert_not_called()
                        self.app.press_button_key(event)
                        self.app.release_button_key(event)
                    button.invoke.assert_called_once_with()
                    self.mouse.action_key_held.assert_called_once_with(key)

    def test_action_key_held_from_a_picker_does_not_activate_a_button(self):
        button = self.app.camera_button
        button.instate.return_value = True
        self.root.focus_get.return_value = button
        bindings = {call.args[0]: call.args[1] for call in self.app.camera_picker.bind.call_args_list}
        for key in ("Return", "space"):
            with self.subTest(key=key):
                event = SimpleNamespace(widget=button, keysym=key)
                picker_press = bindings[f"<KeyPress-{key}>"]
                self.assertIsNone(picker_press(SimpleNamespace(widget=self.app.camera_picker, keysym=key)))
                self.app.press_button_key(event)
                self.app.release_button_key(event)
                button.invoke.assert_not_called()
                self.app.press_button_key(event)
                self.app.release_button_key(event)
                button.invoke.assert_called_once_with()
                button.invoke.reset_mock()

    def test_space_pauses_system_control_once_and_a_new_press_is_needed_to_resume(self):
        self.arm_system_pointer()
        button = self.app.pointer_button
        button.invoke.side_effect = self.app.toggle_pointer
        button.instate.return_value = True
        button.cget.return_value = "Pause"
        self.root.focus_get.return_value = button
        event = SimpleNamespace(widget=button, keysym="space")
        bindings = dict(call.args for call in button.bind.call_args_list)
        press = bindings["<KeyPress-space>"]
        release = bindings["<KeyRelease-space>"]

        for _ in range(5):
            self.assertEqual(press(event), "break")
        self.assertTrue(self.app.active)
        button.invoke.assert_not_called()
        release(event)
        self.assertFalse(self.app.active)
        button.invoke.assert_called_once_with()
        self.assert_no_system_input()

        self.calibrate(0.9)
        self.assertTrue(self.app.can_enable)
        button.cget.return_value = "Enable mouse"
        release(event)
        self.assertFalse(self.app.active)
        button.invoke.assert_called_once_with()
        press(event)
        release(event)
        self.assertTrue(self.app.active)
        self.assertEqual(button.invoke.call_count, 2)
        self.assert_no_system_input()

    def test_overlapping_enter_and_space_cannot_rearm_a_changed_action(self):
        self.arm_system_pointer()
        button = self.app.pointer_button
        button.invoke.side_effect = self.app.toggle_pointer
        button.instate.return_value = True
        button.cget.return_value = "Pause"
        self.root.focus_get.return_value = button
        enter = SimpleNamespace(widget=button, keysym="Return")
        space = SimpleNamespace(widget=button, keysym="space")

        self.app.press_button_key(enter)
        self.app.press_button_key(space)
        self.app.release_button_key(enter)
        self.assertFalse(self.app.active)
        self.calibrate(0.9)
        self.assertTrue(self.app.can_enable)
        button.cget.return_value = "Enable mouse"
        self.app.press_button_key(space)
        self.app.release_button_key(space)
        self.assertFalse(self.app.active)
        button.invoke.assert_called_once_with()

        self.app.press_button_key(space)
        self.app.release_button_key(space)
        self.assertTrue(self.app.active)
        self.assert_no_system_input()

    def test_invalid_camera_number_never_starts_a_camera(self):
        self.camera.snapshot.return_value = (None, None)
        self.camera.thread.is_alive.return_value = False
        self.app.poll()
        with patch("nose_pointer.Camera") as factory:
            for invalid in ("", "-1", "1.5", "another", "2147483648", "1" * 100):
                with self.subTest(invalid=invalid):
                    self.app.camera_index.set(invalid)
                    self.app.toggle_camera()
                    self.assertEqual(self.app.status.get(), self.app.text("camera_index_invalid"))
                    self.assertIsNone(self.app.camera)
            factory.assert_not_called()
        self.app.camera_picker.focus_set.assert_called()
        self.app.camera_picker.selection_range.assert_called_with(0, "end")
        self.assert_no_system_input()

    def test_explicit_camera_stop_finishes_even_if_the_driver_reports_a_late_error(self):
        self.arm_system_pointer()
        self.app.toggle_camera()
        self.assertEqual(self.app.status.get(), self.app.text("status_stopping"))
        self.camera.stop_event.is_set.return_value = True
        self.camera.thread.is_alive.return_value = False
        self.camera.snapshot.return_value = (None, camera.CameraFailure("camera_error_detail", "late read error"))
        self.app.poll()

        self.assertIsNone(self.app.camera)
        self.assertFalse(self.app.active)
        self.assertEqual(self.app.mode.get(), self.app.text("mode_camera_off"))
        self.assertEqual(self.app.status.get(), self.app.text("status_camera_off"))
        self.app.camera_picker.configure.assert_called_with(state="normal")
        self.assert_no_system_input()

    def test_camera_start_error_reenables_the_number_picker(self):
        self.camera.snapshot.return_value = (None, None)
        self.camera.thread.is_alive.return_value = False
        self.app.poll()
        with patch("nose_pointer.Camera") as factory:
            factory.return_value.start.side_effect = RuntimeError("synthetic start failure")
            self.app.toggle_camera()
        self.assertIsNone(self.app.camera)
        self.app.camera_picker.configure.assert_called_with(state="normal")
        self.assertIn("synthetic start failure", self.app.status.get())
        self.assert_no_system_input()

    def test_cursor_read_failure_disarms_without_moving_or_clicking(self):
        self.calibrate(0)
        self.app.toggle_pointer()
        self.mouse.position.side_effect = OSError("Desktop unavailable")
        self.feed(0.4)
        self.assertFalse(self.app.active)
        self.assertIn("Desktop unavailable", self.app.last_gesture.get())
        self.assertEqual(self.app.footer_notice.get(), "System input stopped.")
        self.assert_no_system_input()

    def test_switching_to_dwell_keeps_preview_local_and_clicks_left_only_when_enabled(self):
        self.calibrate(0)
        self.app.args.swap_buttons = True
        self.app.click_mode.set(self.app.text(DWELL_MODE))
        self.app.change_click_mode()
        self.assertFalse(self.app.can_enable)
        self.app.toggle_pointer()
        self.assertFalse(self.app.active)
        self.calibrate(0.4)
        self.feed(0.80, MOVED_FACE)
        for time in (1.00, 1.20, 1.40, 1.60, 1.80, 2.02):
            self.feed(time, MOVED_FACE)
        self.app.dwell_bar.configure.assert_called_with(value=100)
        self.assertIn("Left click", self.app.last_gesture.get())
        self.assert_no_system_input()

        self.app.toggle_pointer()
        self.assertTrue(self.app.active)
        self.app.mode_picker.configure.assert_called_with(state="disabled")
        self.app.delay_picker.configure.assert_called_with(state="disabled")
        self.calibrate(2.1)
        for time in (2.5, 2.7, 2.9, 3.1, 3.3, 3.5, 3.72, 3.9):
            self.feed(time, MOVED_FACE)
        self.mouse.click.assert_called_once_with("left", expected_position=self.app.last_applied_position, valid_until=ANY)
        self.app.pause()
        self.app.mode_picker.configure.assert_called_with(state="readonly")
        self.app.delay_picker.configure.assert_called_with(state="readonly")
        self.app.dwell_bar.configure.assert_called_with(value=0)

    def test_dwell_delay_changes_in_preview_and_is_kept_when_switching_modes(self):
        self.app.click_mode.set(self.app.text(DWELL_MODE))
        self.app.change_click_mode()
        self.calibrate(0)
        self.feed(0.4, MOVED_FACE)
        self.feed(0.6, MOVED_FACE)
        self.app.dwell_time.set("0.8")
        self.app.change_click_mode()
        self.assertEqual(self.app.settings.dwell_seconds, 0.8)
        self.assertFalse(self.app.can_enable)
        self.app.dwell_bar.configure.assert_called_with(value=0)
        self.calibrate(0.7)
        for time in (1.1, 1.28, 1.46, 1.64, 1.82):
            self.feed(time, MOVED_FACE)
        self.assertNotIn("Left click", self.app.last_gesture.get())
        self.feed(1.91, MOVED_FACE)
        self.assertIn("Left click", self.app.last_gesture.get())
        self.assert_no_system_input()

        self.app.click_mode.set(self.app.text(WINK_MODE))
        self.app.change_click_mode()
        self.assertIsNone(self.app.settings.dwell_seconds)
        self.app.click_mode.set(self.app.text(DWELL_MODE))
        self.app.change_click_mode()
        self.assertEqual(self.app.settings.dwell_seconds, 0.8)

    def test_one_eye_dwell_has_bilingual_guidance_and_keeps_emergency_pause(self):
        self.select_quick_dwell()
        self.app.apply_tracking_settings(replace(self.app.settings, dwell_eye="left"))
        neutral = replace(OPEN_FACE, right_blink=0.95)
        target = replace(MOVED_FACE, right_blink=0.95)
        self.feed(0.0, neutral)
        self.assertEqual(self.app.status.get(), self.app.text("hint_calibrating_left", progress=0))
        self.assertIn("left eye", self.app.last_gesture.get())
        self.app.language_choice.set("Русский")
        self.app.change_language()
        self.assertIn("левый глаз", self.app.status.get())
        self.assertIn("левый глаз", self.app.last_gesture.get())
        for now in (0.10, 0.20, 0.31):
            self.feed(now, neutral)
        self.assertTrue(self.app.can_enable)
        self.assert_no_system_input()

        self.app.toggle_pointer()
        self.assertTrue(self.app.active)
        self.assertEqual(self.app.status.get(), self.app.text("status_recenter_left"))
        for now in (0.40, 0.50, 0.60, 0.71):
            self.feed(now, neutral)
        for now in (0.80, 0.96, 1.12, 1.28, 1.42):
            self.feed(now, target)
        self.mouse.click.assert_called_once_with(
            "left", expected_position=self.app.last_applied_position, valid_until=ANY,
        )

        for now in (1.58, 1.74, 1.90, 2.06):
            self.feed(now, neutral)
        self.mouse.reset_mock()
        self.mouse.emergency_requested.return_value = True
        self.feed(2.20, neutral)
        self.assertFalse(self.app.active)
        self.mouse.end_control.assert_called_once_with()
        self.assert_no_system_input()

    def test_switching_away_from_one_eye_dwell_clears_progress(self):
        self.select_quick_dwell()
        self.app.apply_tracking_settings(replace(self.app.settings, dwell_eye="right"))
        neutral = replace(OPEN_FACE, left_blink=0.95)
        target = replace(MOVED_FACE, left_blink=0.95)
        for now in (0.0, 0.10, 0.20, 0.31):
            self.feed(now, neutral)
        for now in (0.40, 0.58, 0.76):
            self.feed(now, target)
        self.assertGreater(self.app.dwell_bar.configure.call_args.kwargs["value"], 0)

        self.app.click_mode.set(self.app.text(WINK_MODE))
        self.app.change_click_mode()
        self.assertIsNone(self.app.settings.dwell_seconds)
        self.assertEqual(self.app.dwell_bar.configure.call_args.kwargs["value"], 0)
        self.feed(0.90, neutral)
        self.assertEqual(self.app.status.get(), self.app.text("hint_calibrating", progress=0))
        self.assertFalse(self.app.can_enable)
        self.select_quick_dwell()
        self.assertEqual(self.app.settings.dwell_eye, "right")
        self.feed(1.05, target)
        self.assertEqual(self.app.status.get(), self.app.text("hint_calibrating_right", progress=0))
        self.assertEqual(self.app.dwell_bar.configure.call_args.kwargs["value"], 0)
        self.assert_no_system_input()

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
        self.assertIn("Right click", self.app.last_gesture.get())
        self.assertIsNone(self.app.right_dwell_armed_at)
        self.assert_no_system_input()

    def test_active_right_dwell_is_consumed_once_then_default_left_click_resumes(self):
        self.select_quick_dwell()
        self.arm_system_pointer()
        self.app.toggle_right_dwell()
        self.feed(0.8)
        for time in (0.9, 1.08, 1.26, 1.44, 1.52, 1.7):
            self.feed(time, MOVED_FACE)
        right_target = self.app.last_applied_position
        self.mouse.click.assert_called_once_with("right", expected_position=right_target, valid_until=ANY)
        self.assertIsNone(self.app.right_dwell_armed_at)

        for time in (1.8, 1.98, 2.16, 2.34, 2.42):
            self.feed(time)
        self.assertEqual(self.mouse.click.call_args_list, [
            call("right", expected_position=right_target, valid_until=ANY),
            call("left", expected_position=self.app.last_applied_position, valid_until=ANY),
        ])
        self.assertEqual(self.mouse.position.call_count, 4)

    def test_unpolled_invalid_camera_sample_clears_a_pending_right_dwell(self):
        self.select_quick_dwell()
        self.arm_system_pointer()
        self.app.toggle_right_dwell()
        self.feed(0.8)
        for now in (0.9, 1.08, 1.26, 1.44):
            self.feed(now, MOVED_FACE)
        self.assertIsNotNone(self.app.right_dwell_armed_at)
        self.mouse.reset_mock()
        camera_feed = camera.Camera(0)
        camera_feed.thread = Mock()
        camera_feed.thread.is_alive.return_value = True
        self.app.camera = camera_feed
        camera_feed.publish(1.48, replace(MOVED_FACE, right_blink=1.01))
        camera_feed.publish(1.52, MOVED_FACE)
        self.clock.return_value = 1.52
        self.app.poll()
        self.app.poll()
        self.assert_no_system_input()
        self.assertIsNone(self.app.right_dwell_armed_at)
        self.assertTrue(self.app.active)

    def test_dwell_uses_visible_motion_near_a_display_gap(self):
        displays = ((0, 0, 100, 100), (100, 0, 200, 200))
        adapter = object.__new__(WindowsMouse)
        adapter._control_lease = object()
        adapter._control_layout = displays
        adapter._monitor_rectangles = Mock(return_value=displays)
        adapter._key_state = Mock(return_value=0)
        self.mouse.position.return_value = (120 / 199, 150 / 199)
        self.enterContext(patch("windows_mouse.ctypes.set_last_error", create=True))
        self.enterContext(patch("windows_mouse.monotonic", self.clock))

        def move_cursor(x, y):
            self.mouse.position.return_value = (x / 199, y / 199)
            return True

        adapter._set_cursor_pos = Mock(side_effect=move_cursor)
        self.mouse.move.side_effect = adapter.move
        self.mouse.visible_position.side_effect = lambda x, y: adapter.visible_position(x, y)
        self.select_quick_dwell()
        self.arm_system_pointer()

        for now in (0.80, 0.96, 1.12, 1.28, 1.41):
            self.feed(now, replace(OPEN_FACE, nose_x=0.536))
        at_edge = (100 / 199, 150 / 199)
        self.assertEqual(self.app.last_applied_position, at_edge)
        self.mouse.click.assert_called_once_with("left", expected_position=at_edge, valid_until=ANY)

        for now in (1.58, 1.74, 1.90, 2.06, 2.19):
            self.feed(now, replace(OPEN_FACE, nose_x=0.549))
        self.assertEqual(self.app.last_applied_position, at_edge)
        self.mouse.click.assert_called_once()
        self.assertEqual(self.app.dwell_bar.configure.call_args.kwargs["value"], 0)

        for now in (2.33, 2.49, 2.65, 2.81, 2.94):
            self.feed(now, OPEN_FACE)
        self.assertEqual(self.mouse.click.call_args_list, [
            call("left", expected_position=at_edge, valid_until=ANY),
            call("left", expected_position=(120 / 199, 150 / 199), valid_until=ANY),
        ])

        adapter._monitor_rectangles.return_value = ((0, 0, 100, 90), displays[1])
        adapter._set_cursor_pos.reset_mock()
        self.mouse.click.reset_mock()
        self.feed(3.10, OPEN_FACE)
        self.assertFalse(self.app.active)
        self.assertEqual(self.app.safety_notice, "safety_display_changed")
        adapter._set_cursor_pos.assert_not_called()
        self.mouse.click.assert_not_called()

    def test_dwell_click_is_cancelled_when_windows_clamps_the_pointer(self):
        self.select_quick_dwell()
        self.arm_system_pointer()
        self.app.toggle_right_dwell()
        self.feed(0.8)

        def clipped_move(x, y, *, valid_until=None):
            self.mouse.position.return_value = (0.25, 0.25)
            return x, y

        for time in (0.9, 1.08, 1.26, 1.44):
            self.feed(time, MOVED_FACE)
        self.mouse.position.assert_not_called()
        self.mouse.move.side_effect = clipped_move
        self.feed(1.52, MOVED_FACE)

        self.assertEqual(self.mouse.position.call_count, 2)
        self.mouse.click.assert_not_called()
        self.assertFalse(self.app.active)
        self.assertIsNone(self.app.right_dwell_armed_at)
        self.assertEqual(self.app.safety_notice, "safety_pointer_moved")
        self.assertIn("Click cancelled", self.app.status.get())
        self.assertIn("Right click cancelled", self.app.last_gesture.get())
        self.app.dwell_bar.configure.assert_called_with(value=0)

    def test_dwell_click_does_not_move_back_to_target_after_external_cursor_movement(self):
        self.select_quick_dwell()
        self.arm_system_pointer()
        self.app.toggle_right_dwell()
        self.feed(0.8)
        for time in (0.9, 1.08, 1.26, 1.44):
            self.feed(time, MOVED_FACE)
        self.mouse.position.assert_not_called()
        self.mouse.click.assert_not_called()
        self.mouse.reset_mock()
        external_position = (0.25, 0.25)
        self.mouse.position.return_value = external_position

        self.feed(1.52, MOVED_FACE)

        self.mouse.position.assert_called_once()
        self.assert_no_system_input()
        self.assertEqual(self.mouse.position.return_value, external_position)
        self.assertFalse(self.app.active)
        self.assertIsNone(self.app.right_dwell_armed_at)
        self.assertEqual(self.app.safety_notice, "safety_pointer_moved")
        self.app.dwell_bar.configure.assert_called_with(value=0)

    def test_dwell_click_checks_for_a_held_mouse_button_before_and_after_moving(self):
        for button_held_at_start in (True, False):
            with self.subTest(button_held_at_start=button_held_at_start):
                self.app.disable_input()
                self.select_quick_dwell()
                self.arm_system_pointer()
                self.app.toggle_right_dwell()
                self.feed(0.8)
                for now in (0.9, 1.08, 1.26, 1.44):
                    self.feed(now, MOVED_FACE)
                self.mouse.button_held.assert_not_called()
                self.mouse.reset_mock()
                self.mouse.button_held.side_effect = [True] if button_held_at_start else [False, True]
                self.feed(1.52, MOVED_FACE)

                self.assertEqual(self.mouse.button_held.call_count, 1 if button_held_at_start else 2)
                self.assertEqual(self.mouse.move.call_count, 0 if button_held_at_start else 1)
                self.mouse.click.assert_not_called()
                self.assertFalse(self.app.active)
                self.assertIsNone(self.app.right_dwell_armed_at)
                self.assertEqual(self.app.safety_notice, "safety_mouse_button")
                self.mouse.button_held.side_effect = None

    def test_wink_click_does_not_send_mouse_events_while_an_external_button_is_held(self):
        self.arm_system_pointer()
        for now in (0.80, 0.92, 1.03):
            self.feed(now, LEFT_WINK)
        self.mouse.button_held.return_value = True
        self.feed(1.08)

        self.mouse.button_held.assert_called_once_with()
        self.mouse.position.assert_not_called()
        self.assert_no_system_input()
        self.assertFalse(self.app.active)
        self.assertEqual(self.app.safety_notice, "safety_mouse_button")

    def test_wink_click_is_cancelled_after_another_device_moves_the_pointer(self):
        self.arm_system_pointer()
        self.feed(0.80, MOVED_FACE)
        self.feed(0.90, LEFT_WINK)
        self.feed(1.02, LEFT_WINK)
        self.mouse.position.assert_not_called()
        self.mouse.position.return_value = (0.9, 0.8)
        self.feed(1.17)

        self.mouse.position.assert_called_once()
        self.mouse.click.assert_not_called()
        self.assertFalse(self.app.active)
        self.assertEqual(self.app.safety_notice, "safety_pointer_moved")
        for time in (1.25, 1.35, 1.45, 1.56):
            self.feed(time)
        self.assertTrue(self.app.can_enable)
        self.assertFalse(self.app.active)
        self.mouse.move.assert_called_once()
        self.mouse.click.assert_not_called()

    def test_wink_click_accepts_the_last_applied_snapped_pixel(self):
        self.arm_system_pointer()
        snapped = (0.29, 0.67)
        self.mouse.move.side_effect = None
        self.mouse.move.return_value = snapped
        self.mouse.position.return_value = snapped
        self.feed(0.80, MOVED_FACE)
        self.assertNotEqual(self.app.position, snapped)
        self.feed(0.90, LEFT_WINK)
        self.feed(1.02, LEFT_WINK)
        self.mouse.position.assert_not_called()
        self.feed(1.17)

        self.assertTrue(self.app.active)
        self.mouse.position.assert_called_once()
        self.mouse.move.assert_called_once()
        self.mouse.click.assert_called_once_with("left", expected_position=self.app.last_applied_position, valid_until=ANY)

    def test_pointer_movement_detected_at_dispatch_pauses_system_control(self):
        self.arm_system_pointer()
        target = self.app.last_applied_position
        self.mouse.click.side_effect = PointerMoved
        for now in (0.80, 0.92):
            self.feed(now, LEFT_WINK)
        self.feed(1.08)
        self.mouse.click.assert_called_once_with("left", expected_position=target, valid_until=ANY)
        self.assertFalse(self.app.active)
        self.assertEqual(self.app.safety_notice, "safety_pointer_moved")
        self.mouse.end_control.assert_called_once()

    def test_cursor_read_failure_at_click_disarms_without_input(self):
        self.arm_system_pointer()
        self.feed(0.80, LEFT_WINK)
        self.feed(0.92, LEFT_WINK)
        self.mouse.position.side_effect = OSError("Desktop unavailable")
        self.feed(1.07)

        self.mouse.position.assert_called_once()
        self.assert_no_system_input()
        self.assertFalse(self.app.active)
        self.assertIn("Desktop unavailable", self.app.last_gesture.get())

    def test_display_layout_change_cancels_wink_and_requires_explicit_reenable(self):
        self.arm_system_pointer()
        self.feed(0.80, LEFT_WINK)
        self.feed(0.92, LEFT_WINK)
        self.mouse.position.side_effect = DisplayLayoutChanged
        self.feed(1.07)

        self.assert_no_system_input()
        self.assertFalse(self.app.active)
        self.mouse.end_control.assert_called_once()
        self.assertIn("Display layout changed", self.app.status.get())
        self.mouse.position.side_effect = None
        self.calibrate(1.2)
        self.assertFalse(self.app.active)
        self.app.toggle_pointer()
        self.mouse.begin_control.assert_called_once()
        self.assertTrue(self.app.active)

    def test_unavailable_display_during_enable_leaves_system_input_off(self):
        self.calibrate(0)
        self.mouse.begin_control.side_effect = OSError("No active display")
        self.app.toggle_pointer()

        self.assertFalse(self.app.active)
        self.assert_no_system_input()
        self.assertIn("No active display", self.app.last_gesture.get())

    def test_busy_session_keeps_camera_in_practice_until_explicit_retry(self):
        self.arm_system_pointer()
        other_root = Mock()
        other_root.winfo_fpixels.return_value = 96
        other_root.winfo_screenwidth.return_value = 1920
        other_root.winfo_screenheight.return_value = 1080
        with patch.object(self, "root", other_root):
            other = self.create_app(self.app.settings)
        other.mouse = Mock()
        other.mouse.emergency_requested.return_value = False
        other.mouse.recenter_requested.return_value = False

        def begin_other_control():
            if self.app.active:
                raise ControlSessionBusy

        other.mouse.begin_control.side_effect = begin_other_control
        other_camera = Mock()
        with patch("nose_pointer.Camera", return_value=other_camera):
            other.toggle_camera()
        other_camera.start.assert_called_once_with()
        for now in (1, 1.1, 1.2, 1.31):
            other.update_tracking(now, OPEN_FACE)
        self.clock.return_value = 1.32
        other.toggle_pointer()

        self.assertTrue(self.app.active)
        self.assertFalse(other.active)
        self.assertEqual(other.safety_notice, "safety_control_busy")
        self.assertIn("Another Nose Pointer window", other.status.get())
        other_camera.stop.assert_not_called()
        other.mouse.end_control.assert_not_called()
        other.mouse.move.assert_not_called()
        other.mouse.click.assert_not_called()

        self.app.pause()
        self.mouse.end_control.assert_called_once_with()
        for now in (1.4, 1.5, 1.6, 1.71):
            other.update_tracking(now, OPEN_FACE)
        self.assertTrue(other.can_enable)
        self.assertFalse(other.active)
        self.clock.return_value = 1.72
        other.toggle_pointer()
        self.assertTrue(other.active)
        other.mouse.move.assert_not_called()
        other.mouse.click.assert_not_called()

    def test_activation_error_releases_acquired_session_without_sending_input(self):
        self.calibrate(0)
        with patch.object(self.app, "recenter", side_effect=RuntimeError("Setup failed")):
            with self.assertRaisesRegex(RuntimeError, "Setup failed"):
                self.app.toggle_pointer()
        self.mouse.begin_control.assert_called_once_with()
        self.mouse.end_control.assert_called_once_with()
        self.assertFalse(self.app.active)
        self.assertIsNone(self.app.last_active_face_at)
        self.assert_no_system_input()

    def test_closing_active_window_releases_session_before_stopping_camera(self):
        self.arm_system_pointer()
        events = Mock()
        events.attach_mock(self.mouse.end_control, "release")
        events.attach_mock(self.camera.stop, "stop")
        self.app.close()
        self.assertEqual(events.mock_calls, [call.release(), call.stop()])
        self.root.destroy.assert_called_once_with()
        self.assertFalse(self.app.active)

    def test_stopping_active_camera_releases_session(self):
        self.arm_system_pointer()
        self.app.toggle_camera()
        self.camera.stop.assert_called_once_with()
        self.mouse.end_control.assert_called_once_with()
        self.assertFalse(self.app.active)
        self.assert_no_system_input()

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

    def test_selecting_motion_only_tracks_closed_eyes_without_clicking(self):
        self.app.click_mode.set(self.app.text(MOTION_MODE))
        self.app.change_click_mode()
        self.assertTrue(self.app.settings.motion_only)
        closed = FaceSample(0.5, 0.5, 0.95, 0.95)
        moved = FaceSample(0.45, 0.54, 0.95, 0.95)
        for time in (0, 0.1, 0.2, 0.31):
            self.feed(time, closed)
        self.assertTrue(self.app.can_enable)
        self.assert_no_system_input()
        self.app.toggle_pointer()
        for time in (0.4, 0.5, 0.6, 0.71):
            self.feed(time, closed)
        self.feed(0.8, moved)
        self.mouse.move.assert_called_once()
        self.assertGreater(self.mouse.move.call_args.args[0], 0.5)
        self.mouse.click.assert_not_called()

        self.app.pause()
        self.app.click_mode.set(self.app.text(WINK_MODE))
        self.app.change_click_mode()
        self.assertFalse(self.app.settings.motion_only)
        for time in (0.9, 1, 1.1, 1.21):
            self.feed(time, closed)
        self.assertFalse(self.app.can_enable)

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
        self.mouse.click.assert_called_once_with("left", expected_position=self.app.last_applied_position, valid_until=ANY)

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
        self.mouse.move.assert_called_once_with(0.22, 0.72, valid_until=ANY)
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

    def test_far_face_after_short_tracking_loss_disarms_until_explicit_reenable(self):
        self.arm_system_pointer()
        self.feed(0.80)
        self.mouse.reset_mock()
        self.feed(0.90, None)
        self.assertTrue(self.app.active)

        replacement = FaceSample(0.76, 0.5, 0.1, 0.1)
        self.feed(0.99, replacement)
        self.feed(1.15, replacement)
        self.assert_no_system_input()
        self.assertFalse(self.app.active)
        self.assertEqual(self.app.safety_notice, "safety_jump")

        for now in (1.25, 1.35, 1.46):
            self.feed(now, replacement)
        self.assertTrue(self.app.can_enable)
        self.assertFalse(self.app.active)
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
        self.assertTrue(self.app.active)
        self.assertTrue(self.app.tracker.calibrated)
        self.mouse.position.assert_called_once()
        self.mouse.move.assert_called_once()
        self.mouse.click.assert_not_called()

    def test_repeated_missing_or_stale_snapshot_expires_from_capture_time(self):
        self.arm_system_pointer()
        self.feed(0.75, wall_time=0.95)
        self.mouse.reset_mock()
        self.feed(0.9, None, wall_time=1.0)
        self.feed(0.9, None, wall_time=5.74)
        self.assertTrue(self.app.active)
        self.assert_no_system_input()

        self.feed(0.9, None, wall_time=5.75)
        self.assertFalse(self.app.active)
        self.assertFalse(self.app.can_enable)
        self.assertIs(self.app.camera, self.camera)
        self.assertIn("Face out of view too long", self.app.status.get())
        self.assert_no_system_input()

    def test_fresh_face_after_skipped_polls_does_not_renew_expired_input(self):
        self.arm_system_pointer()
        self.feed(0.75)
        self.mouse.reset_mock()
        replacement = FaceSample(0.76, 0.5, 0.1, 0.1)
        self.feed(6.0, replacement)
        self.assertFalse(self.app.active)
        self.assert_no_system_input()

        for now in (6.1, 6.2, 6.31):
            self.feed(now, replacement)
        self.assertTrue(self.app.can_enable)
        self.assertFalse(self.app.active)
        self.assert_no_system_input()

    def test_active_start_expires_even_without_a_first_camera_sample(self):
        self.calibrate(0)
        self.app.toggle_pointer()
        self.assertTrue(self.app.active)
        self.camera.snapshot.return_value = (None, None)
        self.clock.return_value = 5.32
        self.app.poll()
        self.assertFalse(self.app.active)
        self.assertIs(self.app.camera, self.camera)
        self.assert_no_system_input()

    def test_fresh_samples_with_closed_eyes_do_not_expire_input(self):
        self.arm_system_pointer()
        closed_eyes = FaceSample(0.5, 0.5, 0.9, 0.9)
        for index in range(4, 35):
            self.feed(index / 5, closed_eyes)
        self.assertTrue(self.app.active)
        self.assert_no_system_input()
        self.feed(6.85)
        self.feed(7.02)
        self.assertTrue(self.app.active)
        self.mouse.move.assert_called_once()
        self.mouse.click.assert_not_called()

    def test_emergency_pause_precedes_a_valid_wink_reopen(self):
        self.arm_system_pointer()
        self.feed(0.80, LEFT_WINK)
        self.feed(0.92, LEFT_WINK)
        self.mouse.emergency_requested.return_value = True
        self.mouse.recenter_requested.return_value = True
        with patch.object(self.app, "recenter", wraps=self.app.recenter) as recenter:
            self.feed(1.07)
        recenter.assert_not_called()
        self.assertFalse(self.app.active)
        self.assert_no_system_input()

    def test_emergency_pause_at_dispatch_releases_control_in_each_mode(self):
        scenarios = {
            WINK_MODE: ((0.80, LEFT_WINK), (0.92, LEFT_WINK), (1.08, OPEN_FACE)),
            DWELL_MODE: tuple((now, MOVED_FACE) for now in (0.80, 0.96, 1.12, 1.28, 1.42)),
            MOTION_MODE: ((0.80, MOVED_FACE),),
        }
        for mode, samples in scenarios.items():
            with self.subTest(mode=mode):
                self.clock.return_value = 0.0
                if mode == DWELL_MODE:
                    self.select_quick_dwell()
                else:
                    self.app.click_mode.set(self.app.text(mode))
                    self.app.change_click_mode()
                self.arm_system_pointer()
                action = "move" if mode == MOTION_MODE else "click"
                with patch.object(self.mouse, action, side_effect=EmergencyPauseRequested) as dispatch:
                    for now, sample in samples:
                        self.feed(now, sample)
                dispatch.assert_called_once()
                self.assertFalse(self.app.active)
                self.assertFalse(self.app.can_enable)
                self.assertEqual(self.app.mode.get(), self.app.text("mode_preview"))
                self.assertEqual(self.app.status.get(), self.app.text("status_paused"))
                self.mouse.end_control.assert_called_once_with()

    def test_frame_expiring_at_dispatch_temporarily_holds_input_in_each_mode(self):
        scenarios = {
            WINK_MODE: ("click", ((0.80, LEFT_WINK), (0.92, LEFT_WINK)), (1.08, OPEN_FACE)),
            DWELL_MODE: ("click", ((0.80, OPEN_FACE), (0.90, MOVED_FACE), (1.08, MOVED_FACE),
                                   (1.26, MOVED_FACE), (1.44, MOVED_FACE)), (1.52, MOVED_FACE)),
            MOTION_MODE: ("move", (), (0.80, MOVED_FACE)),
        }
        for mode, (action, preparation, (captured_at, sample)) in scenarios.items():
            with self.subTest(mode=mode):
                self.app.disable_input()
                self.clock.return_value = 0.0
                if mode == DWELL_MODE:
                    self.select_quick_dwell()
                else:
                    self.app.click_mode.set(self.app.text(mode))
                    self.app.change_click_mode()
                self.arm_system_pointer()
                if mode == DWELL_MODE:
                    self.app.toggle_right_dwell()
                for now, earlier_sample in preparation:
                    self.feed(now, earlier_sample)
                previous_position = self.app.last_applied_position
                previous_face_at = self.app.last_active_face_at
                deadline = captured_at + self.app.settings.max_sample_gap_seconds

                def expire_at_dispatch(*_args, valid_until, **_kwargs):
                    self.assertEqual(valid_until, deadline)
                    self.clock.return_value = deadline + 0.01
                    raise InputFrameExpired

                with patch.object(self.mouse, action, side_effect=expire_at_dispatch) as dispatch:
                    self.feed(captured_at, sample)
                    self.app.poll()
                    dispatch.assert_called_once()
                self.assertTrue(self.app.active)
                self.assertTrue(self.app.feed_stale)
                self.assertTrue(self.app.recovery_pending)
                self.assertEqual(self.app.status.get(), self.app.text("hint_paused"))
                self.assertEqual(self.app.last_applied_position, previous_position)
                self.assertEqual(self.app.last_active_face_at, previous_face_at)
                self.mouse.end_control.assert_not_called()
                if mode == DWELL_MODE:
                    self.assertIsNone(self.app.right_dwell_armed_at)
                    self.assertEqual(self.app.last_gesture.get(), self.app.text("right_cancelled"))

                self.mouse.reset_mock()
                recovery_sample = MOVED_FACE if mode == DWELL_MODE else OPEN_FACE
                self.feed(deadline + 0.02, recovery_sample)
                self.feed(deadline + 0.18, recovery_sample)
                self.assertTrue(self.app.active)
                self.assertFalse(self.app.feed_stale)
                self.assertFalse(self.app.recovery_pending)
                self.mouse.move.assert_called_once()
                self.mouse.click.assert_not_called()

    def test_frame_at_exact_age_limit_is_still_passed_to_the_adapter(self):
        self.arm_system_pointer()
        captured_at = 0.80
        deadline = captured_at + self.app.settings.max_sample_gap_seconds
        self.feed(captured_at, MOVED_FACE, wall_time=deadline)
        self.assertTrue(self.app.active)
        self.assertFalse(self.app.feed_stale)
        self.mouse.move.assert_called_once_with(*self.app.position, valid_until=deadline)

    def test_short_wink_with_slow_reopening_does_not_send_system_input(self):
        self.arm_system_pointer()
        self.feed(0.80, LEFT_WINK)
        self.feed(0.84, LEFT_WINK)
        for now in (0.88, 0.97, 1.05):
            self.feed(now, replace(LEFT_WINK, left_blink=0.5))
        self.feed(1.06)
        self.assertTrue(self.app.active)
        self.assert_no_system_input()

    def test_focused_f8_tap_cancels_a_pending_wink_and_held_f8_prevents_reenable(self):
        self.arm_system_pointer()
        self.feed(0.80, LEFT_WINK)
        self.feed(0.92, LEFT_WINK)
        pause = next(binding.args[1] for binding in self.root.bind.call_args_list if binding.args[0] == "<F8>")
        pause(None)
        pause(None)
        self.feed(1.07)
        self.assertFalse(self.app.active)
        self.assert_no_system_input()
        self.calibrate(1.18)
        self.assertTrue(self.app.can_enable)
        self.mouse.emergency_requested.return_value = True
        self.app.toggle_pointer()
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
