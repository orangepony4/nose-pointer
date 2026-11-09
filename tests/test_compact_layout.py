from types import SimpleNamespace
import sys
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import camera
from nose_pointer import DWELL_MODE, WINK_MODE, PointerApp
from tracking import FaceSample, Settings


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

    def test_compact_notice_stays_visible_with_scrolled_settings(self):
        for language in ("en", "ru"):
            for notice in ("safety_multiple_brief", "camera_error"):
                with self.subTest(language=language, notice=notice):
                    app, mouse = self.open_window(192, (1280, 720), language)
                    root = app.root
                    fake_camera = Mock()
                    fake_camera.stop_event.is_set.return_value = False
                    fake_camera.thread.is_alive.return_value = True
                    mouse.emergency_requested.return_value = False
                    mouse.recenter_requested.return_value = False
                    with patch("nose_pointer.Camera", return_value=fake_camera):
                        app.camera_button.invoke()
                    for index in range(6):
                        app.update_tracking(index / 5, FaceSample(0.5, 0.5, 0.1, 0.1))
                    with patch("nose_pointer.monotonic", return_value=1.1):
                        app.pointer_button.invoke()
                    self.assertTrue(app.active)
                    root.update()
                    app.workspace.yview_moveto(1)
                    root.update()
                    footer_top = app.camera_button.winfo_rooty()
                    self.assertGreater(app.workspace.yview()[0], 0)

                    if notice == "safety_multiple_brief":
                        fake_camera.snapshot.return_value = ((1.2, camera.AMBIGUOUS_FACE), None)
                        detailed_status = app.text("safety_multiple")
                    else:
                        detail = "\n".join(f"Synthetic driver detail {number}" for number in range(1, 6))
                        fake_camera.snapshot.return_value = (
                            None, camera.CameraFailure("camera_error_detail", detail)
                        )
                        fake_camera.thread.is_alive.return_value = False
                        detailed_status = app.text("camera_error_detail", detail=detail)
                    with patch("nose_pointer.monotonic", return_value=1.2), patch.object(root, "after"):
                        app.poll()
                    root.update()

                    self.assertFalse(app.active)
                    self.assertTrue(app.pointer_button.instate(["disabled"]))
                    self.assertEqual(app.status.get(), detailed_status)
                    self.assertEqual(app.footer_notice.get(), app.text(notice))
                    self.assert_widget_fits(app.footer_notice_label, root)
                    self.assert_widget_fits(app.pointer_button, root)
                    self.assertEqual(app.camera_button.winfo_rooty(), footer_top)
                    self.assertGreater(app.workspace.yview()[0], 0)
                    if notice == "camera_error":
                        app.workspace.yview_moveto(0)
                        root.update()
                        self.assertEqual(int(app.status_label.cget("height")), 0)
                        self.assert_widget_fits(app.status_label, app.workspace)
                    mouse.move.assert_not_called()
                    mouse.click.assert_not_called()

    def test_growing_window_hides_duplicate_notice_when_workspace_fits(self):
        # Grow a compact window without exceeding a hosted Windows display's resize limit.
        app, mouse = self.open_window(96, (1280, 480), "ru")
        root = app.root
        app.pause_for_safety("safety_multiple")
        root.update()
        self.assertTrue(app.footer_notice_label.winfo_ismapped())
        fixed_height = root.winfo_height() - app.workspace.winfo_height() - app.footer_notice_label.winfo_height()
        (content,) = app.workspace_body.winfo_children()
        root.geometry(f"{root.winfo_width()}x{fixed_height + content.winfo_reqheight() + 16}+0+0")
        root.update()
        self.assertFalse(app.footer_notice_label.winfo_ismapped())
        self.assertFalse(app.workspace_scrollbar.winfo_ismapped())
        self.assert_widget_fits(app.status_label, app.workspace)
        self.assertEqual(app.status.get(), app.text("safety_multiple"))
        self.assertEqual(mouse.mock_calls, [])

    def test_notice_layout_tolerates_focus_in_a_native_popdown(self):
        app, mouse = self.open_window(192, (1280, 720), "en")
        with patch.object(app.root, "focus_get", side_effect=KeyError("popdown")):
            app.pause_for_safety("safety_multiple")
            app.resize_workspace()
        app.root.update()
        self.assert_widget_fits(app.footer_notice_label, app.root)
        self.assertEqual(mouse.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
