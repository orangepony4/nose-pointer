from types import SimpleNamespace
import sys
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from nose_pointer import DWELL_MODE, WINK_MODE, PointerApp
from tracking import Settings


@unittest.skipUnless(sys.platform == "win32", "Checks Windows Tk geometry")
class CompactLayoutTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("nose_pointer.save_language"))

    def open_window(self, dpi, screen, language):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"No Tk display: {error}")
        self.addCleanup(root.destroy)
        root.withdraw()
        root.attributes("-alpha", 0.0)
        root.attributes("-toolwindow", True)
        root.tk.call("tk", "scaling", dpi / 72)
        root.winfo_screenwidth = lambda: screen[0]
        root.winfo_screenheight = lambda: screen[1]
        args = SimpleNamespace(camera=0, lang=language, no_clicks=False, swap_buttons=False)
        mouse = Mock()
        with patch.object(PointerApp, "poll"):
            app = PointerApp(root, mouse, Settings(dwell_seconds=1.2), args)
            width, height = root.minsize()
            root.geometry(f"{width}x{height}+0+0")
            root.deiconify()
            root.update()
        return app, mouse

    def assert_widget_fits(self, widget, container):
        self.assertTrue(widget.winfo_ismapped())
        self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth())
        self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())
        for edge, size in (("rootx", "width"), ("rooty", "height")):
            position = getattr(widget, f"winfo_{edge}")()
            start = getattr(container, f"winfo_{edge}")()
            self.assertGreaterEqual(position, start)
            self.assertLessEqual(position + getattr(widget, f"winfo_{size}")(),
                                 start + getattr(container, f"winfo_{size}")())

    def test_main_actions_stay_visible_and_focused_settings_scroll_into_view(self):
        for dpi, screen in ((144, (1280, 720)), (192, (1366, 768))):
            for language in ("en", "ru"):
                with self.subTest(dpi=dpi, screen=screen, language=language):
                    app, mouse = self.open_window(dpi, screen, language)
                    self.assert_widget_fits(app.camera_button, app.root)
                    self.assert_widget_fits(app.pointer_button, app.root)
                    self.assertTrue(app.workspace_scrollbar.winfo_ismapped())
                    footer_top = app.camera_button.winfo_rooty()
                    app.workspace.yview_moveto(0)
                    app.root.update()
                    current_language = app.language_choice.get()
                    app.language_picker.event_generate("<MouseWheel>", delta=-120)
                    app.root.update()
                    self.assertEqual(app.language_choice.get(), current_language)
                    self.assertGreater(app.workspace.yview()[0], 0)
                    app.workspace.yview_moveto(0)
                    app.root.update()
                    app.delay_picker.event_generate("<FocusIn>")
                    app.root.update()
                    self.assert_widget_fits(app.delay_picker, app.workspace)
                    self.assertGreater(app.workspace.yview()[0], 0)
                    self.assertEqual(app.camera_button.winfo_rooty(), footer_top)
                    app.language_picker.event_generate("<FocusIn>")
                    app.root.update()
                    self.assert_widget_fits(app.language_picker, app.workspace)
                    self.assertEqual(mouse.mock_calls, [])

    def test_spacious_window_expands_practice_area_without_scrollbar(self):
        app, mouse = self.open_window(96, (1920, 1080), "en")
        self.assertFalse(app.workspace_scrollbar.winfo_ismapped())
        self.assertGreater(app.pad.winfo_height(), app.pad.winfo_reqheight())
        self.assert_widget_fits(app.delay_picker, app.workspace)
        self.assert_widget_fits(app.pointer_button, app.root)
        self.assertEqual(mouse.mock_calls, [])

    def test_scrollbar_tracks_optional_dwell_settings(self):
        app, mouse = self.open_window(96, (1920, 1080), "en")
        root = app.root
        fixed_height = root.winfo_height() - app.workspace.winfo_height()
        (content,) = app.workspace_body.winfo_children()
        width = root.winfo_width()
        root.minsize(width, 1)
        root.geometry(f"{width}x{fixed_height + content.winfo_reqheight() - 14}+0+0")
        root.update()
        self.assertTrue(app.workspace_scrollbar.winfo_ismapped())
        app.workspace.yview_moveto(1)
        root.update()
        self.assertGreater(app.workspace.yview()[0], 0)

        app.click_mode.set(app.text(WINK_MODE))
        app.change_click_mode()
        root.update()
        self.assertFalse(app.workspace_scrollbar.winfo_ismapped())
        self.assertEqual(app.workspace.yview(), (0.0, 1.0))

        app.click_mode.set(app.text(DWELL_MODE))
        app.change_click_mode()
        root.update()
        self.assertTrue(app.workspace_scrollbar.winfo_ismapped())
        app.delay_picker.event_generate("<FocusIn>")
        root.update()
        self.assert_widget_fits(app.delay_picker, app.workspace)
        self.assertEqual(mouse.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
