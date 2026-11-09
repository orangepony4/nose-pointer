"""Windows cursor and click adapter. Importing this module sends no input."""

import ctypes
import math
import sys
from ctypes import wintypes


_VK_LBUTTON = 0x01
_VK_RBUTTON = 0x02
_VK_MBUTTON = 0x04
_VK_F8 = 0x77
_VK_F9 = 0x78
_KEY_IS_DOWN = 0x8000
_ERROR_ACCESS_DENIED = 5
_E_ACCESSDENIED = 0x80070005
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
_PROCESS_PER_MONITOR_DPI_AWARE = 2

_INPUT_MOUSE = 0
_BUTTON_FLAGS = {
    "left": (0x0002, 0x0004),
    "right": (0x0008, 0x0010),
}
_ULONG_PTR = ctypes.c_size_t


class _MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _KeyboardInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _InputPayload(ctypes.Union):
    _fields_ = [
        ("mi", _MouseInput),
        ("ki", _KeyboardInput),
        ("hi", _HardwareInput),
    ]


class _Input(ctypes.Structure):
    _anonymous_ = ("payload",)
    _fields_ = [("type", wintypes.DWORD), ("payload", _InputPayload)]


def _bind(library, name, result_type, *argument_types):
    function = getattr(library, name)
    function.restype = result_type
    function.argtypes = argument_types
    return function


def _input_error(operation, error_code):
    if error_code:
        return ctypes.WinError(error_code, f"{operation}: {ctypes.FormatError(error_code).strip()}")
    return OSError(f"{operation}. Windows may be blocking input on the current desktop.")


def enable_dpi_awareness() -> bool:
    """Enable process-local DPI awareness before creating any windows."""
    if sys.platform != "win32":
        return False

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    is_aware = _bind(user32, "IsProcessDPIAware", wintypes.BOOL)
    try:
        set_context = _bind(user32, "SetProcessDpiAwarenessContext", wintypes.BOOL, ctypes.c_void_p)
    except AttributeError:
        pass
    else:
        ctypes.set_last_error(0)
        if set_context(ctypes.c_void_p(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)):
            return True
        if ctypes.get_last_error() == _ERROR_ACCESS_DENIED:
            return bool(is_aware())

    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        set_awareness = _bind(shcore, "SetProcessDpiAwareness", ctypes.c_long, ctypes.c_int)
    except (AttributeError, OSError):
        pass
    else:
        result = set_awareness(_PROCESS_PER_MONITOR_DPI_AWARE)
        if result == 0:
            return True
        if result & 0xFFFFFFFF == _E_ACCESSDENIED:
            return bool(is_aware())

    set_legacy_awareness = _bind(user32, "SetProcessDPIAware", wintypes.BOOL)
    return bool(set_legacy_awareness() or is_aware())


class WindowsMouse:
    """Read, move and click the cursor in the active Windows desktop."""

    def __init__(self):
        if sys.platform != "win32":
            raise OSError("System mouse control is available only on Windows.")

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._set_cursor_pos = _bind(user32, "SetCursorPos", wintypes.BOOL, ctypes.c_int, ctypes.c_int)
        self._get_cursor_pos = _bind(user32, "GetCursorPos", wintypes.BOOL, ctypes.POINTER(wintypes.POINT))
        self._monitor_callback = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HANDLE, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
        )
        self._enum_monitors = _bind(
            user32, "EnumDisplayMonitors", wintypes.BOOL,
            wintypes.HDC, ctypes.POINTER(wintypes.RECT), self._monitor_callback, wintypes.LPARAM
        )
        self._send_input = _bind(
            user32, "SendInput", wintypes.UINT, wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int
        )
        self._key_state = _bind(user32, "GetAsyncKeyState", wintypes.SHORT, ctypes.c_int)

    def _monitor_rectangles(self):
        rectangles = []

        @self._monitor_callback
        def collect(_monitor, _device_context, rect_pointer, _data):
            rect = rect_pointer.contents
            if rect.right > rect.left and rect.bottom > rect.top:
                rectangles.append((rect.left, rect.top, rect.right, rect.bottom))
            return True

        if not self._enum_monitors(None, None, collect, 0) or not rectangles:
            raise OSError("Windows did not report an active display.")
        return rectangles

    @staticmethod
    def _desktop_bounds(rectangles):
        lefts, tops, rights, bottoms = zip(*rectangles)
        return min(lefts), min(tops), max(rights), max(bottoms)

    @staticmethod
    def _normalize_position(x, y, bounds):
        left, top, right, bottom = bounds
        x = (x - left) / max(1, right - left - 1)
        y = (y - top) / max(1, bottom - top - 1)
        return min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)

    def position(self) -> tuple[float, float]:
        """Read the current cursor in the same coordinates accepted by move()."""
        bounds = self._desktop_bounds(self._monitor_rectangles())
        point = wintypes.POINT()
        ctypes.set_last_error(0)
        if not self._get_cursor_pos(ctypes.byref(point)):
            raise _input_error("GetCursorPos could not read the cursor", ctypes.get_last_error())
        return self._normalize_position(point.x, point.y, bounds)

    def move(self, x: float, y: float) -> tuple[float, float]:
        """Move to a visible pixel and return its normalized coordinates."""
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("Cursor coordinates must be finite.")

        rectangles = self._monitor_rectangles()
        bounds = self._desktop_bounds(rectangles)
        left, top, right, bottom = bounds
        pixel_x = left + round(min(max(x, 0.0), 1.0) * (right - left - 1))
        pixel_y = top + round(min(max(y, 0.0), 1.0) * (bottom - top - 1))

        # Keep the point if it is visible and snap to the nearest edge in gaps.
        candidates = (
            (min(max(pixel_x, x0), x1 - 1), min(max(pixel_y, y0), y1 - 1))
            for x0, y0, x1, y1 in rectangles
        )
        target_x, target_y = min(
            candidates, key=lambda point: (point[0] - pixel_x) ** 2 + (point[1] - pixel_y) ** 2
        )

        ctypes.set_last_error(0)
        if not self._set_cursor_pos(target_x, target_y):
            raise _input_error("SetCursorPos could not move the cursor", ctypes.get_last_error())
        return self._normalize_position(target_x, target_y, bounds)

    def click(self, button: str) -> None:
        """Send a down/up pair without leaving a deliberately held button."""
        if button not in _BUTTON_FLAGS:
            raise ValueError("Mouse button must be 'left' or 'right'.")

        events = (_Input * 2)()
        for event, flag in zip(events, _BUTTON_FLAGS[button]):
            event.type = _INPUT_MOUSE
            event.mi.dwFlags = flag

        event_size = ctypes.sizeof(_Input)
        ctypes.set_last_error(0)
        inserted = self._send_input(2, events, event_size)
        if inserted == 2:
            return
        if inserted == 1:
            # The down event was inserted. Retry only the release.
            release = (_Input * 1)(events[1])
            for _ in range(2):
                ctypes.set_last_error(0)
                if self._send_input(1, release, event_size) == 1:
                    return
            raise _input_error("SendInput could not release the mouse button", ctypes.get_last_error())
        raise _input_error("SendInput could not click the mouse button", ctypes.get_last_error())

    def button_held(self) -> bool:
        """Return whether a standard physical mouse button is currently down."""
        return any(self._key_state(key) & _KEY_IS_DOWN for key in (_VK_LBUTTON, _VK_RBUTTON, _VK_MBUTTON))

    def emergency_requested(self) -> bool:
        """Return whether F8 is currently held on the active desktop."""
        return bool(self._key_state(_VK_F8) & _KEY_IS_DOWN)

    def recenter_requested(self) -> bool:
        """Return whether F9 is currently held on the active desktop."""
        return bool(self._key_state(_VK_F9) & _KEY_IS_DOWN)
