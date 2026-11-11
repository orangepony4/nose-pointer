from types import SimpleNamespace
import sys
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, call, patch

from nose_pointer import ACCENT, DWELL_MODE, EDGE, MOTION_MODE, WINK_MODE, PointerApp
from tracking import FaceSample, Settings


@unittest.skipUnless(sys.platform == "win32", "Checks Windows Tk widgets")
class DwellEyeWidgetTests(unittest.TestCase):
    def setUp(self):
        self.clock = self.enterContext(patch("nose_pointer.monotonic", return_value=0.0))
        self.save_preference = self.enterContext(patch("nose_pointer.save_preference"))
        self.enterContext(patch("nose_pointer.save_language"))

    def open_app(self, settings, *, no_clicks=False, swap_buttons=False):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"No Tk display: {error}")
        self.addCleanup(root.destroy)
        root.withdraw()
        root.tk.call("tk", "scaling", 96 / 72)
        mouse = Mock()
        mouse.emergency_requested.return_value = False
        mouse.recenter_requested.return_value = False
        mouse.button_held.return_value = False
        args = SimpleNamespace(camera=0, lang="en", no_clicks=no_clicks, swap_buttons=swap_buttons)
        with patch.object(tk.Misc, "focus_set"), patch.object(PointerApp, "poll"):
            app = PointerApp(root, mouse, settings, args)
        root.update_idletasks()
        return app, mouse

    def choose(self, picker, index):
        picker.current(index)
        picker.event_generate("<<ComboboxSelected>>", when="now")

    def test_eye_picker_localizes_cli_choice_and_locks_during_mouse_control(self):
        app, mouse = self.open_app(Settings(calibration_seconds=0, dwell_seconds=0.6, dwell_eye="right"))
        picker = app.dwell_eye_picker
        self.assertEqual(picker.cget("values"), ("Both eyes", "Left eye", "Right eye"))
        self.assertEqual(picker.current(), 2)
        self.assertEqual(app.dwell_controls.winfo_manager(), "pack")

        self.choose(app.language_picker, 1)
        self.assertEqual(picker.cget("values"), ("Оба глаза", "Левый глаз", "Правый глаз"))
        self.assertEqual(picker.get(), "Правый глаз")
        self.choose(picker, 1)
        self.assertEqual(app.settings.dwell_eye, "left")
        self.save_preference.assert_called_once_with("dwell-eye", "left")

        app.update_tracking(0.1, FaceSample(0.5, 0.5, 0.1, 0.95))
        self.clock.return_value = 0.1
        app.toggle_pointer()
        self.assertTrue(app.active)
        self.assertTrue(picker.instate(["disabled"]))
        self.choose(picker, 0)
        self.assertEqual(picker.current(), 1)
        self.assertEqual(app.settings.dwell_eye, "left")
        app.pause()
        self.assertTrue(picker.instate(["readonly", "!disabled"]))
        self.choose(app.mode_picker, 0)
        self.assertEqual(app.dwell_controls.winfo_manager(), "")
        self.assertEqual(app.dwell_eye_row.winfo_manager(), "")
        self.choose(app.mode_picker, 1)
        self.assertEqual(app.dwell_controls.winfo_manager(), "pack")
        self.assertEqual(app.dwell_eye_row.winfo_manager(), "grid")
        self.assertEqual(picker.get(), "Левый глаз")
        self.choose(picker, 0)
        self.assertIsNone(app.settings.dwell_eye)
        self.assertEqual(self.save_preference.call_args_list, [
            call("dwell-eye", "left"), call("click-mode", WINK_MODE),
            call("click-mode", DWELL_MODE), call("dwell-eye", "both"),
        ])
        self.assertEqual(app.root.state(), "withdrawn")
        self.assertFalse(app.root.winfo_viewable())
        mouse.move.assert_not_called()
        mouse.click.assert_not_called()

    def test_motion_only_lock_keeps_eye_picker_hidden_and_disabled(self):
        app, mouse = self.open_app(Settings(motion_only=True), no_clicks=True)
        self.assertEqual(app.dwell_controls.winfo_manager(), "")
        self.assertEqual(app.dwell_eye_row.winfo_manager(), "")
        self.assertTrue(app.dwell_eye_picker.instate(["disabled"]))
        self.assertEqual(app.wink_eye_row.winfo_manager(), "")
        self.assertTrue(app.wink_eye_picker.instate(["disabled"]))
        self.choose(app.dwell_eye_picker, 2)
        self.assertIsNone(app.settings.dwell_eye)
        self.assertEqual(app.dwell_eye_picker.current(), 0)
        self.assertFalse(app.root.winfo_viewable())
        self.save_preference.assert_not_called()
        self.assertEqual(mouse.mock_calls, [])

    def test_wink_eye_picker_localizes_locks_and_returns_after_switching_modes(self):
        app, mouse = self.open_app(Settings(calibration_seconds=0), swap_buttons=True)
        picker = app.wink_eye_picker
        self.assertEqual(picker.cget("values"), ("Left eye", "Right eye"))
        self.assertEqual(picker.get(), "Right eye")
        self.assertEqual(app.wink_eye_row.winfo_manager(), "grid")
        self.assertEqual(app.dwell_eye_row.winfo_manager(), "")
        self.assertEqual(app.status.get(), app.text("status_welcome"))

        self.choose(app.language_picker, 1)
        self.assertEqual(picker.cget("values"), ("Левый глаз", "Правый глаз"))
        self.assertEqual(picker.get(), "Правый глаз")
        self.choose(picker, 0)
        self.assertEqual(app.wink_left_eye, "left")
        self.assertEqual(app.status.get(), app.text("status_welcome"))
        self.save_preference.assert_called_once_with("wink-left-eye", "left")

        app.update_tracking(0.1, FaceSample(0.5, 0.5, 0.1, 0.1))
        self.clock.return_value = 0.1
        app.toggle_pointer()
        self.assertTrue(app.active)
        self.assertTrue(picker.instate(["disabled"]))
        self.choose(picker, 1)
        self.assertEqual(picker.current(), 0)
        self.assertEqual(app.wink_left_eye, "left")
        app.pause()
        self.assertTrue(picker.instate(["readonly", "!disabled"]))
        self.choose(app.mode_picker, 1)
        self.assertEqual(app.wink_eye_row.winfo_manager(), "")
        self.assertEqual(app.dwell_eye_row.winfo_manager(), "grid")
        self.choose(app.mode_picker, 2)
        self.assertEqual(app.wink_eye_row.winfo_manager(), "")
        self.assertEqual(app.dwell_eye_row.winfo_manager(), "")
        self.choose(app.mode_picker, 0)
        self.assertEqual(app.wink_eye_row.winfo_manager(), "grid")
        self.assertEqual(picker.get(), "Левый глаз")
        self.assertEqual(self.save_preference.call_args_list, [
            call("wink-left-eye", "left"), call("click-mode", DWELL_MODE),
            call("click-mode", MOTION_MODE), call("click-mode", WINK_MODE),
        ])
        mouse.move.assert_not_called()
        mouse.click.assert_not_called()

    def test_wink_hold_picker_keeps_custom_value_and_locks_during_system_control(self):
        app, mouse = self.open_app(Settings(calibration_seconds=0, wink_min_seconds=0.35))
        picker = app.wink_hold_picker
        self.assertEqual(picker.cget("values"), ("220", "300", "350", "400", "500", "600"))
        self.assertEqual(picker.get(), "350")
        self.assertEqual(app.wink_hold_row.winfo_manager(), "pack")
        self.choose(app.language_picker, 1)
        self.assertEqual(picker.get(), "350")
        self.choose(picker, 3)
        self.assertEqual(app.settings.wink_min_seconds, 0.4)
        self.save_preference.assert_called_once_with("wink-hold-ms", 400)

        app.update_tracking(0.1, FaceSample(0.5, 0.5, 0.1, 0.1))
        self.clock.return_value = 0.1
        app.toggle_pointer()
        self.assertTrue(app.active)
        self.assertTrue(picker.instate(["disabled"]))
        self.choose(picker, 1)
        self.assertEqual(picker.get(), "400")
        self.assertEqual(app.settings.wink_min_seconds, 0.4)
        app.pause()
        self.assertTrue(picker.instate(["readonly", "!disabled"]))
        for mode in (1, 2):
            self.choose(app.mode_picker, mode)
            self.assertEqual(app.wink_hold_row.winfo_manager(), "")
        self.choose(app.mode_picker, 0)
        self.assertEqual(app.wink_hold_row.winfo_manager(), "pack")
        self.assertEqual(picker.get(), "400")
        mouse.move.assert_not_called()
        mouse.click.assert_not_called()

    def test_eye_picker_uses_spare_mode_row_space_and_stacks_at_narrow_widths(self):
        app, mouse = self.open_app(Settings(dwell_seconds=1.2))
        for language in (0, 1):
            self.choose(app.language_picker, language)
            app.root.update_idletasks()
            for width, expected_row in ((490, 0), (320, 1)):
                with self.subTest(language=app.language, width=width):
                    app.click_controls.event_generate("<Configure>", width=width, height=24, when="now")
                    self.assertEqual(int(app.dwell_eye_row.grid_info()["row"]), expected_row)
        self.assertFalse(app.root.winfo_viewable())
        self.assertEqual(mouse.mock_calls, [])

    def test_dwell_indicator_uses_palette_and_keeps_determinate_progress(self):
        app, mouse = self.open_app(Settings(calibration_seconds=0, smoothing_seconds=0, dwell_seconds=0.6))
        bar = app.dwell_bar
        style = ttk.Style(app.root)
        style_name = bar.cget("style")
        self.assertEqual(bar.winfo_class(), "TProgressbar")
        self.assertEqual(str(bar.cget("mode")), "determinate")
        self.assertEqual(float(bar.cget("maximum")), 100)
        self.assertIn("background", style.element_options("Dwell.Progressbar.pbar"))
        self.assertIn("troughcolor", style.element_options("Dwell.Progressbar.trough"))
        self.assertEqual(style.lookup(style_name, "background"), ACCENT)
        self.assertEqual(style.lookup(style_name, "troughcolor"), EDGE)
        self.assertEqual(float(bar.cget("value")), 0)

        app.update_tracking(0.0, FaceSample(0.5, 0.5, 0.1, 0.1))
        moved = FaceSample(0.58, 0.5, 0.1, 0.1)
        for now in (0.1, 0.3, 0.4):
            app.update_tracking(now, moved)
        self.assertAlmostEqual(float(bar.cget("value")), 50)
        app.update_tracking(0.5, FaceSample(0.58, 0.5, 0.95, 0.1))
        self.assertEqual(float(bar.cget("value")), 0)
        self.assertFalse(app.root.winfo_viewable())
        self.assertEqual(mouse.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
