import ctypes
from ctypes import wintypes
import unittest
from unittest.mock import Mock, call, patch

from windows_mouse import DisplayLayoutChanged, WindowsMouse


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
        self.mouse._send_input = Mock(return_value=2)
        self.mouse._key_state = Mock()
        self.mouse.end_control()
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
                self.assertEqual(self.mouse.move(*position), expected)
                self.mouse._set_cursor_pos.assert_called_once_with(*pixels)

    def test_move_returns_the_rounded_or_snapped_pixel(self):
        rounded = self.mouse.move(0.12345, 0.45678)
        self.mouse._set_cursor_pos.assert_called_once_with(-885, 384)
        self.fake_cursor(-885, 384)
        self.assertEqual(rounded, self.mouse.position())

        self.mouse._set_cursor_pos.reset_mock()
        # (-3, 1000) lies below the left display and just left of the right one.
        snapped = self.mouse.move(1277 / 3199, 1200 / 1279)
        self.mouse._set_cursor_pos.assert_called_once_with(0, 1000)
        self.fake_cursor(0, 1000)
        self.assertEqual(snapped, self.mouse.position())

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

    def test_monitor_change_blocks_cursor_reads_movement_and_click_until_reenabled(self):
        self.mouse.begin_control()
        self.mouse._monitor_rectangles.return_value = [(0, 0, 1920, 1080)]
        for action in (self.mouse.position, lambda: self.mouse.move(0.75, 0.5),
                       lambda: self.mouse.click("left")):
            with self.assertRaises(DisplayLayoutChanged):
                action()
        self.mouse._get_cursor_pos.assert_not_called()
        self.mouse._set_cursor_pos.assert_not_called()
        self.mouse._send_input.assert_not_called()

        self.mouse.end_control()
        self.mouse.begin_control()
        self.assertEqual(self.mouse.move(1, 1), (1.0, 1.0))
        self.mouse._set_cursor_pos.assert_called_once_with(1919, 1079)
        self.mouse.click("left")
        self.mouse._send_input.assert_called_once()

    def test_layout_order_is_irrelevant_but_same_bounds_can_have_a_different_layout(self):
        displays = [(0, 0, 100, 100), (100, 0, 200, 100)]
        self.mouse._monitor_rectangles.return_value = displays
        self.mouse.begin_control()
        self.mouse._monitor_rectangles.return_value = displays[::-1]
        self.assertEqual(self.mouse.move(1, 1), (1.0, 1.0))

        self.mouse._monitor_rectangles.return_value = [(0, 0, 110, 100), (110, 0, 200, 100)]
        self.mouse._set_cursor_pos.reset_mock()
        with self.assertRaises(DisplayLayoutChanged):
            self.mouse.move(1, 1)
        self.mouse._set_cursor_pos.assert_not_called()

    def test_recenter_requested_checks_only_f9_key_down_bit(self):
        self.mouse._key_state.side_effect = [0, 1, -32768, -32767]
        self.assertEqual(
            [self.mouse.recenter_requested() for _ in range(4)],
            [False, False, True, True],
        )
        self.assertEqual(self.mouse._key_state.call_args_list, [call(0x78)] * 4)

    def test_button_held_checks_the_high_bit_of_each_physical_button(self):
        buttons = (0x01, 0x02, 0x04, 0x05, 0x06)
        self.mouse._key_state.return_value = 1
        self.assertFalse(self.mouse.button_held())
        self.assertEqual(self.mouse._key_state.call_args_list, [call(button) for button in buttons])
        for button in buttons:
            with self.subTest(button=button):
                self.mouse._key_state.side_effect = lambda key: -32767 if key == button else 0
                self.assertTrue(self.mouse.button_held())


if __name__ == "__main__":
    unittest.main()
