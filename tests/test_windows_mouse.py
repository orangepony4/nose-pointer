import ctypes
from ctypes import wintypes
import unittest
from unittest.mock import Mock, call, patch

from windows_mouse import WindowsMouse


class WindowsMouseTests(unittest.TestCase):
    def setUp(self):
        # Bypass DLL binding. Every Win32 call used here is a Python mock.
        self.mouse = object.__new__(WindowsMouse)
        self.mouse._monitor_rectangles = Mock(return_value=[
            (-1280, -200, 0, 824),
            (0, 0, 1920, 1080),
        ])
        self.mouse._get_cursor_pos = Mock()
        self.mouse._set_cursor_pos = Mock(return_value=True)
        self.mouse._key_state = Mock()
        self.enterContext(patch.object(ctypes, "set_last_error", create=True))

    def fake_cursor(self, x, y):
        def get_cursor(pointer):
            point = ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT)).contents
            point.x, point.y = x, y
            return True

        self.mouse._get_cursor_pos.side_effect = get_cursor

    def test_position_round_trips_pixels_across_negative_desktop_origin(self):
        cases = [
            ((-1280, -200), (0.0, 0.0)),
            ((-629, 325), (651 / 3199, 525 / 1279)),
            ((1670, 490), (2950 / 3199, 690 / 1279)),
            ((1919, 1079), (1.0, 1.0)),
        ]
        for pixels, expected in cases:
            with self.subTest(pixels=pixels):
                self.fake_cursor(*pixels)
                self.mouse._set_cursor_pos.reset_mock()
                position = self.mouse.position()
                self.assertEqual(position, expected)
                self.mouse._set_cursor_pos.assert_not_called()
                self.mouse.move(*position)
                self.mouse._set_cursor_pos.assert_called_once_with(*pixels)

    def test_position_clamps_outside_reported_bounds_and_handles_one_pixel(self):
        self.fake_cursor(-2000, 1200)
        self.assertEqual(self.mouse.position(), (0.0, 1.0))
        self.mouse._monitor_rectangles.return_value = [(-8, -4, -7, -3)]
        self.fake_cursor(-8, -4)
        self.assertEqual(self.mouse.position(), (0.0, 0.0))

    def test_position_surfaces_a_failed_cursor_read(self):
        self.mouse._get_cursor_pos.return_value = False
        with patch.object(ctypes, "get_last_error", return_value=0, create=True):
            with self.assertRaisesRegex(OSError, "GetCursorPos"):
                self.mouse.position()
        self.mouse._set_cursor_pos.assert_not_called()

    def test_recenter_requested_checks_only_f9_key_down_bit(self):
        self.mouse._key_state.side_effect = [0, 1, -32768, -32767]
        self.assertEqual(
            [self.mouse.recenter_requested() for _ in range(4)],
            [False, False, True, True],
        )
        self.assertEqual(self.mouse._key_state.call_args_list, [call(0x78)] * 4)


if __name__ == "__main__":
    unittest.main()
