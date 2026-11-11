from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nose_pointer import DEFAULT_DWELL_MS, DWELL_MODE, MOTION_MODE, SENSITIVITY_PRESETS, main
from preferences import save_preference
from tracking import Settings


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.dict("os.environ", {"LOCALAPPDATA": folder}))
        self.directory = Path(folder) / "NosePointer"

    def launch(self, *arguments):
        with (
            patch("nose_pointer.sys.platform", "win32"),
            patch("nose_pointer.tk.Tk"),
            patch("windows_mouse.WindowsMouse"),
            patch("windows_mouse.enable_dpi_awareness"),
            patch("nose_pointer.PointerApp") as app,
        ):
            main(list(arguments))
        self.launched_camera = app.call_args.args[-1].camera
        return app.call_args.args[-2], app.call_args.kwargs["initial_dwell_ms"]

    def test_missing_preferences_use_existing_defaults_without_writing(self):
        self.assertEqual(self.launch(), (Settings(), DEFAULT_DWELL_MS))
        self.assertEqual(self.launched_camera, 0)
        self.assertFalse(self.directory.exists())

    def test_remembers_the_camera_and_keeps_cli_overrides_transient(self):
        save_preference("camera", 3)
        self.launch()
        self.assertEqual(self.launched_camera, 3)
        self.launch("--camera", "1")
        self.assertEqual(self.launched_camera, 1)
        self.assertEqual((self.directory / "camera.txt").read_bytes(), b"3\n")

        for invalid in (b"-1", b"1.5", b"2147483648", b"9" * 40, b"\xff"):
            with self.subTest(invalid=invalid):
                (self.directory / "camera.txt").write_bytes(invalid)
                self.launch()
                self.assertEqual(self.launched_camera, 0)

    def test_normal_launch_restores_settings_and_cli_overrides_are_transient(self):
        save_preference("sensitivity", "sensitivity_high")
        save_preference("click-mode", DWELL_MODE)
        save_preference("dwell-ms", 950)
        stored = {path.name: path.read_bytes() for path in self.directory.iterdir()}

        settings, delay = self.launch()
        self.assertEqual((settings.range_x, settings.range_y, settings.dead_zone),
                         SENSITIVITY_PRESETS["sensitivity_high"])
        self.assertEqual((settings.dwell_seconds, delay), (0.95, 950))
        self.assertFalse(settings.motion_only)

        settings, delay = self.launch("--range-x", "0.08", "--dwell-ms", "850")
        self.assertEqual((settings.range_x, settings.range_y), (0.08, Settings.range_y))
        self.assertEqual((settings.dwell_seconds, delay), (0.85, 850))

        settings, delay = self.launch("--range-y", "0.09", "--no-clicks")
        self.assertEqual((settings.range_x, settings.range_y), (Settings.range_x, 0.09))
        self.assertTrue(settings.motion_only)
        self.assertIsNone(settings.dwell_seconds)
        self.assertEqual(delay, 950)
        self.assertEqual({path.name: path.read_bytes() for path in self.directory.iterdir()}, stored)

    def test_dwell_delay_is_kept_while_another_mode_is_selected(self):
        save_preference("click-mode", MOTION_MODE)
        save_preference("dwell-ms", 800)
        settings, delay = self.launch()
        self.assertTrue(settings.motion_only)
        self.assertIsNone(settings.dwell_seconds)
        self.assertEqual(delay, 800)

    def test_saved_horizontal_direction_and_transient_cli_override(self):
        path = self.directory / "horizontal-direction.txt"
        save_preference("horizontal-direction", "direction_direct")
        settings, _ = self.launch()
        self.assertFalse(settings.mirror)
        self.assertEqual(path.read_bytes(), b"direction_direct\n")

        save_preference("horizontal-direction", "direction_mirrored")
        settings, _ = self.launch("--no-mirror")
        self.assertFalse(settings.mirror)
        settings, _ = self.launch()
        self.assertTrue(settings.mirror)
        self.assertEqual(path.read_bytes(), b"direction_mirrored\n")

        for invalid in (b"other", b"Direct", b"\xff", b"x" * 40):
            with self.subTest(invalid=invalid):
                path.write_bytes(invalid)
                settings, _ = self.launch()
                self.assertTrue(settings.mirror)
                self.assertEqual(path.read_bytes(), invalid)

    def test_one_eye_dwell_uses_saved_delay_and_stays_transient(self):
        save_preference("click-mode", MOTION_MODE)
        save_preference("dwell-ms", 950)
        stored = {path.name: path.read_bytes() for path in self.directory.iterdir()}

        settings, delay = self.launch("--dwell-eye", "right")
        self.assertEqual((settings.dwell_eye, settings.dwell_seconds, delay), ("right", 0.95, 950))
        self.assertFalse(settings.motion_only)
        settings, delay = self.launch("--dwell-eye", "left", "--dwell-ms", "850")
        self.assertEqual((settings.dwell_eye, settings.dwell_seconds, delay), ("left", 0.85, 850))

        settings, delay = self.launch()
        self.assertTrue(settings.motion_only)
        self.assertEqual((settings.dwell_eye, settings.dwell_seconds, delay), (None, None, 950))
        self.assertEqual({path.name: path.read_bytes() for path in self.directory.iterdir()}, stored)

    def test_one_eye_dwell_conflicts_with_motion_only(self):
        with redirect_stderr(StringIO()) as stderr, self.assertRaises(SystemExit) as error:
            self.launch("--lang", "ru", "--dwell-eye", "left", "--no-clicks")
        self.assertEqual(error.exception.code, 2)
        self.assertIn("Выберите --dwell-eye для кликов по задержке", stderr.getvalue())

    def test_saved_dwell_eye_is_restored_and_cli_can_override_it_for_one_launch(self):
        save_preference("click-mode", DWELL_MODE)
        save_preference("dwell-eye", "left")
        path = self.directory / "dwell-eye.txt"

        settings, _ = self.launch()
        self.assertEqual((settings.dwell_eye, settings.dwell_seconds), ("left", 1.2))
        for override, expected in (("right", "right"), ("both", None)):
            with self.subTest(override=override):
                settings, _ = self.launch("--dwell-eye", override)
                self.assertEqual((settings.dwell_eye, settings.dwell_seconds), (expected, 1.2))
                self.assertEqual(path.read_bytes(), b"left\n")

        save_preference("click-mode", MOTION_MODE)
        settings, _ = self.launch()
        self.assertTrue(settings.motion_only)
        self.assertEqual((settings.dwell_eye, settings.dwell_seconds), ("left", None))
        settings, _ = self.launch("--dwell-ms", "850")
        self.assertEqual((settings.dwell_eye, settings.dwell_seconds), ("left", 0.85))
        self.assertEqual(path.read_bytes(), b"left\n")

    def test_missing_or_invalid_dwell_eye_uses_both_eyes_without_changing_other_preferences(self):
        save_preference("click-mode", DWELL_MODE)
        save_preference("dwell-ms", 950)
        path = self.directory / "dwell-eye.txt"
        for saved in (None, b"both\n", b"third", b"LEFT", b"right\nleft", b"\xff", b"left" + b"x" * 40):
            with self.subTest(saved=saved):
                if saved is not None:
                    path.write_bytes(saved)
                settings, _ = self.launch()
                self.assertEqual((settings.dwell_eye, settings.dwell_seconds), (None, 0.95))
                if saved is None:
                    self.assertFalse(path.exists())
                else:
                    self.assertEqual(path.read_bytes(), saved)

    def test_bad_preference_does_not_hide_other_valid_choices(self):
        save_preference("sensitivity", "sensitivity_low")
        save_preference("click-mode", DWELL_MODE)
        (self.directory / "dwell-ms.txt").write_bytes(b"0" * 29 + b"850" + b"x" * 10_000)
        settings, delay = self.launch()
        self.assertEqual(settings.range_x, SENSITIVITY_PRESETS["sensitivity_low"][0])
        self.assertEqual((settings.dwell_seconds, delay), (1.2, DEFAULT_DWELL_MS))

        (self.directory / "sensitivity.txt").write_bytes(b"\xff")
        save_preference("click-mode", "invalid")
        save_preference("dwell-ms", 5001)
        self.assertEqual(self.launch(), (Settings(), DEFAULT_DWELL_MS))

    def test_blocked_storage_falls_back_and_failed_replace_keeps_previous_value(self):
        save_preference("click-mode", MOTION_MODE)
        with patch("pathlib.Path.replace", side_effect=PermissionError):
            save_preference("click-mode", DWELL_MODE)
        mode_path = self.directory / "click-mode.txt"
        self.assertEqual(mode_path.read_bytes(), b"motion\n")
        self.assertEqual(list(self.directory.iterdir()), [mode_path])

        mode_path.unlink()
        self.directory.rmdir()
        self.directory.touch()
        save_preference("click-mode", DWELL_MODE)
        self.assertEqual(self.launch(), (Settings(), DEFAULT_DWELL_MS))


if __name__ == "__main__":
    unittest.main()
