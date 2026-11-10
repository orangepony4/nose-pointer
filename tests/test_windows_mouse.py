import ctypes
from ctypes import wintypes
import unittest
from unittest.mock import Mock, call, patch

from windows_mouse import ControlSessionBusy, DisplayLayoutChanged, MouseButtonHeld, PointerMoved, WindowsMouse


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
        self.mouse._create_mutex = Mock(return_value=1)
        self.mouse._close_handle = Mock(return_value=True)
        self.mouse._control_lease = None
        self.mouse.end_control()
        self.enterContext(patch.object(ctypes, "set_last_error", create=True))
        self.last_error = self.enterContext(patch.object(ctypes, "get_last_error", return_value=0, create=True))

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

    def test_visible_position_matches_move_using_the_reserved_display_order(self):
        displays = [(0, 0, 100, 200), (201, 0, 300, 200)]
        self.mouse._monitor_rectangles.return_value = displays
        self.mouse.begin_control()
        self.mouse._monitor_rectangles.reset_mock()
        self.mouse._monitor_rectangles.return_value = displays[::-1]

        equidistant = (150 / 299, 100 / 199)
        visible = self.mouse.visible_position(*equidistant)
        self.assertEqual(visible, (99 / 299, 100 / 199))
        self.mouse._monitor_rectangles.assert_not_called()
        self.mouse._set_cursor_pos.assert_not_called()
        self.assertEqual(self.mouse.move(*equidistant), visible)
        self.mouse._monitor_rectangles.assert_called_once_with()
        self.mouse._set_cursor_pos.assert_called_once_with(99, 100)

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

    def test_click_cancels_if_the_pointer_moves_during_the_final_layout_check(self):
        self.fake_cursor(-629, 325)
        self.mouse.begin_control()
        expected = self.mouse.position()

        def enumerate_after_external_motion():
            self.fake_cursor(1670, 490)
            return self.mouse._monitor_rectangles.return_value

        self.mouse._monitor_rectangles.side_effect = enumerate_after_external_motion
        with self.assertRaises(PointerMoved):
            self.mouse.click("left", expected_position=expected)
        self.mouse._send_input.assert_not_called()

    def test_click_checks_buttons_after_reading_the_current_cursor(self):
        self.fake_cursor(-629, 325)
        self.mouse.begin_control()
        expected = self.mouse.position()
        read_cursor = self.mouse._get_cursor_pos.side_effect
        self.mouse._key_state.return_value = 0

        def read_as_side_button_is_pressed(pointer):
            self.mouse._key_state.side_effect = lambda key: -32768 if key == 0x06 else 0
            return read_cursor(pointer)

        self.mouse._get_cursor_pos.side_effect = read_as_side_button_is_pressed
        with self.assertRaises(MouseButtonHeld):
            self.mouse.click("right", expected_position=expected)
        self.mouse._send_input.assert_not_called()

        self.mouse._key_state.side_effect = None
        self.mouse._get_cursor_pos.side_effect = read_cursor
        self.mouse.click("right", expected_position=expected)
        self.mouse._send_input.assert_called_once()
        events = self.mouse._send_input.call_args.args[1]
        self.assertEqual([event.mi.dwFlags for event in events], [0x0008, 0x0010])

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

    def test_session_lease_blocks_a_second_controller_until_pause_or_process_exit(self):
        handles = {}

        def create_mutex(attributes, initial_owner, name):
            self.assertIsNone(attributes)
            self.assertFalse(initial_owner)
            self.assertTrue(name.startswith("Local\\"))
            self.last_error.return_value = 183 if name in handles.values() else 0
            handle = object()
            handles[handle] = name
            return handle

        def close_handle(handle):
            del handles[handle]
            return True

        first = self.mouse
        second = object.__new__(WindowsMouse)
        second._monitor_rectangles = first._monitor_rectangles
        second._control_lease = second._control_layout = None
        for adapter in (first, second):
            adapter._create_mutex = Mock(side_effect=create_mutex)
            adapter._close_handle = Mock(side_effect=close_handle)

        first.begin_control()
        first.begin_control()
        first._create_mutex.assert_called_once()
        with self.assertRaises(ControlSessionBusy):
            second.begin_control()
        second._close_handle.assert_called_once()
        self.assertIsNone(second._control_lease)
        self.assertEqual(len(handles), 1)

        first.end_control()
        first.end_control()
        first._close_handle.assert_called_once()
        second.begin_control()
        self.assertEqual(len(handles), 1)
        # The kernel drops the second process's handle when that process exits.
        close_handle(second._control_lease)
        first.begin_control()
        self.assertEqual(len(handles), 1)
        first.end_control()
        self.assertEqual(handles, {})

    def test_failed_control_start_leaves_no_session_lease(self):
        self.mouse._monitor_rectangles.side_effect = OSError("No active display")
        with self.assertRaisesRegex(OSError, "No active display"):
            self.mouse.begin_control()
        self.mouse._create_mutex.assert_not_called()
        self.mouse._monitor_rectangles.side_effect = None
        self.mouse._create_mutex.return_value = None
        with self.assertRaisesRegex(OSError, "CreateMutexW"):
            self.mouse.begin_control()
        self.mouse.end_control()
        self.mouse._close_handle.assert_not_called()
        self.assertIsNone(self.mouse._control_layout)

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

    def test_action_key_held_checks_the_high_bit_and_maps_both_enter_keys(self):
        for keysym, virtual_key in (("Return", 0x0D), ("KP_Enter", 0x0D), ("space", 0x20)):
            with self.subTest(keysym=keysym):
                self.mouse._key_state.reset_mock()
                self.mouse._key_state.side_effect = [0, 1, -32768, -32767]
                self.assertEqual([self.mouse.action_key_held(keysym) for _ in range(4)],
                                 [False, False, True, True])
                self.assertEqual(self.mouse._key_state.call_args_list, [call(virtual_key)] * 4)


if __name__ == "__main__":
    unittest.main()
