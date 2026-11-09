from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from i18n import load_language, save_language
from nose_pointer import main


class LanguageTests(unittest.TestCase):
    def test_preferences_store_only_the_selected_locale(self):
        with TemporaryDirectory() as folder, patch.dict("os.environ", {"LOCALAPPDATA": folder}):
            path = Path(folder) / "NosePointer" / "language.txt"
            self.assertEqual(load_language(), "en")
            save_language("ru")
            self.assertEqual(path.read_bytes(), b"ru\n")
            self.assertEqual(load_language(), "ru")
            with patch("pathlib.Path.replace", side_effect=PermissionError):
                save_language("en")
            self.assertEqual(load_language(), "ru")
            self.assertEqual(list(path.parent.iterdir()), [path])
            save_language("en")
            self.assertEqual(path.read_bytes(), b"en\n")
            path.write_bytes(b"ru\ninvalid")
            self.assertEqual(load_language(), "en")

    def test_blocked_preferences_keep_english_fallback(self):
        with TemporaryDirectory() as folder, patch.dict("os.environ", {"LOCALAPPDATA": folder}):
            (Path(folder) / "NosePointer").touch()
            self.assertEqual(load_language(), "en")
            save_language("ru")
            self.assertEqual(load_language(), "en")

    def test_explicit_launch_language_overrides_saved_choice_without_saving(self):
        with (
            patch("nose_pointer.sys.platform", "win32"),
            patch("nose_pointer.tk.Tk"),
            patch("windows_mouse.WindowsMouse"),
            patch("windows_mouse.enable_dpi_awareness"),
            patch("nose_pointer.PointerApp") as app,
            patch("nose_pointer.load_language", return_value="ru") as load,
            patch("nose_pointer.load_text_preference", return_value=""),
            patch("nose_pointer.save_language") as save,
        ):
            main([])
            self.assertEqual(app.call_args.args[-1].lang, "ru")
            main(["--lang", "en"])
            self.assertEqual(app.call_args.args[-1].lang, "en")
            load.assert_called_once_with()
            save.assert_not_called()

    def test_model_commands_use_no_language_preferences(self):
        with (
            patch("nose_pointer.download_model") as download,
            patch("nose_pointer.check_inference") as check,
            patch("nose_pointer.load_language") as load,
            patch("nose_pointer.load_text_preference") as load_tracking,
            patch("nose_pointer.save_language") as save,
            redirect_stdout(StringIO()) as stdout,
        ):
            main(["--download-model"])
            main(["--check", "--lang", "ru"])
            self.assertIn("Model ready.", stdout.getvalue())
            self.assertIn("Камера оставалась выключенной.", stdout.getvalue())
            download.assert_called_once_with()
            check.assert_called_once_with()
            load.assert_not_called()
            load_tracking.assert_not_called()
            save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
