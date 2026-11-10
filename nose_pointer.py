"""Windows webcam pointer with an explicit preview and an emergency pause."""

import argparse
import sys
import tkinter as tk
from dataclasses import replace
from time import monotonic
from tkinter import ttk

from camera import AMBIGUOUS_FACE, FACE_JUMP, Camera, CameraError, check_inference, download_model
from i18n import LANGUAGES, load_language, save_language, translate
from preferences import load_text_preference, save_preference
from tracking import Settings, Tracker
from windows_mouse import (
    ControlSessionBusy, DisplayLayoutChanged, EmergencyPauseRequested, InputFrameExpired, MouseButtonHeld, PointerMoved,
)


BACKGROUND = "#f7f5ef"
PAPER = "#fffdf7"
INK = "#23271f"
MUTED = "#565c50"
EDGE = "#dedbd1"
ACCENT = "#315538"
ALERT = "#81261b"
WINK_MODE = "wink"
DWELL_MODE = "dwell"
MOTION_MODE = "motion"
CLICK_MODES = (WINK_MODE, DWELL_MODE, MOTION_MODE)
SENSITIVITY_PRESETS = {
    "sensitivity_low": (0.18, 0.15, Settings.dead_zone),
    "sensitivity_standard": (Settings.range_x, Settings.range_y, Settings.dead_zone),
    "sensitivity_high": (0.065, 0.054, Settings.dead_zone),
}
DEFAULT_DWELL_MS = 1200
MIN_DWELL_MS = 600
MAX_DWELL_MS = 5000
DWELL_PRESETS_MS = (MIN_DWELL_MS, 800, 1000, DEFAULT_DWELL_MS, 1500, 2000, 2500, 3000, 4000, MAX_DWELL_MS)
FACE_LOSS_GRACE_SECONDS = 5.0
MAX_CAMERA_INDEX = 2_147_483_647
CAMERA_BRIEF_MESSAGES = {
    "camera_error_detail": "camera_error",
    "camera_unavailable": "camera_unavailable_brief",
    "model_missing": "model_missing_brief",
}
COMPACT_ACTION_LABELS = {"open_camera": "open_camera_short", "stop_camera": "stop_camera_short",
                         "enable_mouse": "enable_mouse_short"}
BUTTON_ACTION_KEYS = ("Return", "KP_Enter", "space")

def dwell_label(milliseconds, language):
    value = f"{milliseconds / 1000:g}"
    return value.replace(".", ",") if language == "ru" else value


def parse_camera_index(value: str) -> int | None:
    value = value.strip()
    if 0 < len(value) <= 10 and value.isascii() and value.isdecimal():
        index = int(value)
        if index <= MAX_CAMERA_INDEX:
            return index
    return None


class PointerApp:
    def __init__(self, root, mouse, settings, args, *, initial_dwell_ms=DEFAULT_DWELL_MS):
        self.root = root
        self.mouse = mouse
        self.settings = settings
        self.args = args
        self.language = getattr(args, "lang", "en")
        self.static_labels = []
        self.messages = {}
        self.button_labels = {"camera_button": "open_camera", "pointer_button": "enable_mouse"}
        self.tracker = Tracker(settings)
        self.camera = None
        self.last_camera_index = args.camera
        self.camera_index_to_save: int | None = None
        self.active = False
        self.recenter_held = False
        self.last_frame = None
        self.last_ready_frame_at: float | None = None
        self.last_active_face_at: float | None = None
        self.calibration_requested_at: float | None = None
        self.last_applied_position = None
        self.recovery_pending = False
        self.right_dwell_armed_at: float | None = None
        self.button_key_presses = {}
        self.unfocused_button_keys: tuple[str, ...] = ()
        self.feed_stale = False
        self.can_enable = False
        self.safety_notice = ""
        self.compact_footer = False
        self.tight_footer = False
        self.position = (0.5, 0.5)

        root.title("Nose Pointer")
        root.configure(bg=BACKGROUND)
        extra_scale = max(0.0, root.winfo_fpixels("1i") / 96 - 1)
        width = min(round(580 + 160 * extra_scale), root.winfo_screenwidth() - 32)
        height = min(round(626 + 405 * extra_scale), root.winfo_screenheight() - 64)
        root.geometry(f"{width}x{height}")
        root.minsize(width - 20, height - 25)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Escape>", self.pause)
        root.bind("<F8>", self.pause)
        root.bind("<F9>", self.request_recenter)

        style = ttk.Style(root)
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 8))
        style.configure("Compact.TButton", padding=(6, 6))
        style.configure("Tight.TButton", font=("Segoe UI", 8), padding=(6, 6))
        shell = tk.Frame(root, bg=BACKGROUND, padx=26, pady=22)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)
        self.workspace = tk.Canvas(shell, bg=BACKGROUND, highlightthickness=0, takefocus=False)
        self.workspace.grid(row=0, column=0, sticky="nsew")
        self.workspace_scrollbar = ttk.Scrollbar(shell, orient="vertical", command=self.workspace.yview,
                                                 takefocus=False)
        self.workspace_scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self.workspace_scrollbar.grid_remove()
        self.workspace.configure(yscrollcommand=self.workspace_scrollbar.set)
        self.workspace_body = tk.Frame(self.workspace, bg=BACKGROUND)
        self.workspace_body.columnconfigure(0, weight=1)
        self.workspace_body.rowconfigure(0, weight=1)
        self.workspace_window = self.workspace.create_window(0, 0, anchor="nw", window=self.workspace_body)
        frame = tk.Frame(self.workspace_body, bg=BACKGROUND)
        frame.grid(row=0, column=0, sticky="nsew")
        header = tk.Frame(frame, bg=BACKGROUND)
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)
        title = tk.Label(header, text="Nose Pointer", font=("Segoe UI", 26, "bold"),
                         bg=BACKGROUND, fg=INK, anchor="w", justify="left")
        title.grid(row=0, column=0, sticky="w")
        language_controls = tk.Frame(header, bg=BACKGROUND)
        language_controls.grid(row=0, column=1, sticky="e")
        self.language_choice = tk.StringVar(value=LANGUAGES[self.language])
        self.language_picker = ttk.Combobox(language_controls, textvariable=self.language_choice,
                                            values=tuple(LANGUAGES.values()), width=9, state="readonly")
        self.language_picker.pack(side="right")
        self.language_picker.bind("<<ComboboxSelected>>", self.change_language)
        self.make_label(language_controls, "language", font=("Segoe UI", 10), fg=INK).pack(side="right", padx=(0, 7))
        header.bind("<Configure>", lambda event: self.resize_header(event, title, language_controls))
        self.make_label(frame, "subtitle", font=("Segoe UI", 11), fg=MUTED, anchor="w",
                        justify="left", wraplength=430).pack(fill="x", pady=(2, 17))

        self.mode = tk.StringVar(value="")
        self.set_message("mode", "mode_camera_off")
        tk.Label(frame, textvariable=self.mode, font=("Segoe UI", 11, "bold"),
                 bg=BACKGROUND, fg=ACCENT, anchor="w", justify="left", wraplength=430).pack(fill="x")
        self.status = tk.StringVar(value="")
        self.set_message("status", "status_welcome")
        self.status_label = tk.Label(frame, textvariable=self.status, font=("Segoe UI", 10),
                                     bg=BACKGROUND, fg=INK, anchor="nw", justify="left",
                                     wraplength=430, height=3)
        self.status_label.pack(fill="x", pady=(4, 4))
        self.status_label.bind("<Configure>", lambda event: self.status_label.configure(wraplength=event.width))

        self.pad = tk.Canvas(frame, bg=PAPER, width=400, height=48,
                             highlightthickness=1, highlightbackground=EDGE)
        self.pad.pack(fill="both", expand=True)
        self.pad.bind("<Configure>", self.draw_pad)
        self.last_gesture = tk.StringVar(value="")
        gesture_label = tk.Label(frame, textvariable=self.last_gesture, font=("Segoe UI", 10),
                                 bg=BACKGROUND, fg=MUTED, anchor="nw", justify="left",
                                 wraplength=430, height=2)
        gesture_label.pack(fill="x", pady=(8, 10))
        gesture_label.bind("<Configure>", lambda event: gesture_label.configure(wraplength=event.width))

        settings_controls = tk.Frame(frame, bg=BACKGROUND)
        settings_controls.pack(fill="x", pady=(0, 4))
        sensitivity_row = tk.Frame(settings_controls, bg=BACKGROUND)
        sensitivity_row.pack(fill="x", pady=(0, 8))
        sensitivity_label = self.make_label(sensitivity_row, "sensitivity", font=("Segoe UI", 10), fg=INK)
        self.sensitivity_presets = SENSITIVITY_PRESETS.copy()
        initial_range = (settings.range_x, settings.range_y, settings.dead_zone)
        selected_sensitivity = next((label for label, preset in self.sensitivity_presets.items()
                                     if preset == initial_range), "sensitivity_custom")
        self.sensitivity_presets[selected_sensitivity] = initial_range
        self.sensitivity = tk.StringVar(value=self.text(selected_sensitivity))
        self.sensitivity_picker = ttk.Combobox(sensitivity_row, textvariable=self.sensitivity,
                                               values=self.choice_labels(self.sensitivity_presets), width=12, state="readonly")
        self.layout_choice(sensitivity_row, sensitivity_label, self.sensitivity_picker)
        self.sensitivity_picker.bind("<<ComboboxSelected>>", self.change_sensitivity)

        click_row = tk.Frame(settings_controls, bg=BACKGROUND)
        click_row.pack(fill="x")
        click_label = self.make_label(click_row, "click_mode", font=("Segoe UI", 10), fg=INK)
        self.click_mode = tk.StringVar(value=self.text(self.selected_click_mode()))
        self.mode_picker = ttk.Combobox(click_row, textvariable=self.click_mode,
                                       values=self.choice_labels(CLICK_MODES), width=18,
                                       state="disabled" if args.no_clicks else "readonly")
        self.layout_choice(click_row, click_label, self.mode_picker)
        self.mode_picker.bind("<<ComboboxSelected>>", self.change_click_mode)
        current_delay = round(settings.dwell_seconds * 1000) if settings.dwell_seconds is not None else initial_dwell_ms
        self.dwell_presets = tuple(sorted({*DWELL_PRESETS_MS, current_delay}))
        self.dwell_durations = self.delay_choices()
        self.dwell_time = tk.StringVar(value=dwell_label(current_delay, self.language))
        self.dwell_controls = tk.Frame(settings_controls, bg=BACKGROUND)
        self.dwell_controls.columnconfigure(1, weight=1)
        dwell_settings = tk.Frame(self.dwell_controls, bg=BACKGROUND)
        dwell_settings.grid(row=0, column=0, sticky="w")
        dwell_actions = tk.Frame(self.dwell_controls, bg=BACKGROUND)
        dwell_actions.grid(row=0, column=1, sticky="ew")
        self.dwell_controls.bind("<Configure>", lambda event: self.resize_dwell(event, dwell_settings, dwell_actions))
        self.make_label(dwell_settings, "dwell_delay", font=("Segoe UI", 10), fg=INK).pack(side="left", padx=(0, 9))
        self.delay_picker = ttk.Combobox(dwell_settings, textvariable=self.dwell_time,
                                        values=tuple(self.dwell_durations), width=6, state="readonly")
        self.delay_picker.pack(side="left")
        self.delay_picker.bind("<<ComboboxSelected>>", self.change_click_mode)
        self.dwell_bar = ttk.Progressbar(dwell_actions, length=65, maximum=100, mode="determinate")
        self.dwell_bar.pack(side="left", fill="x", expand=True, padx=(12, 9))

        footer = tk.Frame(shell, bg=BACKGROUND)
        footer.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.footer_notice = tk.StringVar(value="")
        self.footer_notice_label = tk.Label(footer, textvariable=self.footer_notice,
                                           bg=BACKGROUND, fg=ALERT, anchor="w", justify="left",
                                           font=("Segoe UI", 10, "bold"), pady=4)
        footer.bind("<Configure>", lambda event: self.footer_notice_label.configure(wraplength=event.width))
        camera_choice = tk.Frame(footer, bg=BACKGROUND)
        camera_choice.pack(fill="x", pady=(0, 4))
        camera_label = self.make_label(camera_choice, "camera_index", font=("Segoe UI", 10), fg=INK)
        camera_label.pack(side="left", padx=(0, 9))
        self.camera_index = tk.StringVar(value=str(args.camera))
        self.camera_picker = ttk.Spinbox(camera_choice, from_=0, to=MAX_CAMERA_INDEX,
                                         textvariable=self.camera_index, width=10)
        self.camera_picker.pack(side="left")
        camera_label.bind("<Button-1>", lambda _event: self.camera_picker.focus_set()
                          if not self.camera_picker.instate(["disabled"]) else None)
        controls = tk.Frame(footer, bg=BACKGROUND)
        self.footer_controls = controls
        controls.pack(fill="x")
        self.camera_button = ttk.Button(controls, text=self.text("open_camera"), command=self.toggle_camera)
        self.camera_button.pack(side="left", padx=(0, 8))
        self.pointer_button = ttk.Button(controls, text=self.text("enable_mouse"), command=self.toggle_pointer, state="disabled")
        self.pointer_button.pack(side="left")
        self.right_dwell_button = ttk.Button(dwell_actions, command=self.toggle_right_dwell)
        self.right_dwell_button.bind("<ButtonRelease-3>", self.cancel_right_dwell)
        self.action_buttons = (self.camera_button, self.pointer_button, self.right_dwell_button)
        for key in BUTTON_ACTION_KEYS:
            root.bind(f"<KeyPress-{key}>", self.remember_other_button_key, add="+")
            root.bind(f"<KeyRelease-{key}>", self.release_button_key, add="+")
            for button in self.action_buttons:
                button.bind(f"<KeyPress-{key}>", self.press_button_key)
                button.bind(f"<KeyRelease-{key}>", self.release_button_key)
        root.bind("<FocusOut>", self.cancel_button_key, add="+")
        root.bind("<FocusIn>", self.restore_button_key_focus, add="+")
        self.show_click_instructions()
        self.hotkey_label = self.make_label(footer, "hotkeys", font=("Segoe UI", 10, "bold"), fg=INK,
                                            anchor="w", justify="left", wraplength=430)
        self.hotkey_label.pack(fill="x", pady=(9, 0))
        self.hotkey_label.bind("<Configure>", lambda event: self.hotkey_label.configure(wraplength=event.width))
        privacy_key = "privacy_no_clicks" if args.no_clicks else "privacy"
        self.footer_privacy = self.make_label(footer, privacy_key, font=("Segoe UI", 9), fg=MUTED,
                                              anchor="w", justify="left", wraplength=430)
        self.footer_privacy.pack(fill="x", pady=(4, 0))
        self.footer_privacy.bind("<Configure>", lambda event: self.footer_privacy.configure(wraplength=event.width))
        self.workspace_privacy = self.make_label(frame, privacy_key, font=("Segoe UI", 9), fg=MUTED,
                                                 anchor="w", justify="left", wraplength=430)
        self.workspace_privacy.bind("<Configure>", lambda event: self.workspace_privacy.configure(wraplength=event.width))
        root.bind("<Configure>", self.resize_footer, add="+")
        self.workspace.bind("<Configure>", self.resize_workspace)
        self.workspace_body.bind("<Configure>", self.resize_workspace)
        root.bind("<FocusIn>", self.reveal_workspace_focus, add="+")
        root.bind("<MouseWheel>", self.scroll_workspace_wheel, add="+")
        root.bind("<Prior>", lambda _event: self.scroll_workspace(-1, "pages"))
        root.bind("<Next>", lambda _event: self.scroll_workspace(1, "pages"))
        # In a scrolling workspace, a wheel over a picker should scroll the view.
        for picker in (self.language_picker, self.sensitivity_picker, self.mode_picker,
                       self.delay_picker, self.camera_picker):
            picker.bind("<MouseWheel>", self.scroll_workspace_wheel, add="+")
            for key in BUTTON_ACTION_KEYS:
                picker.bind(f"<KeyPress-{key}>", self.remember_other_button_key, add="+")
        self.camera_button.focus_set()
        root.after(16, self.poll)

    def press_button_key(self, event):
        if event.keysym not in self.button_key_presses:
            button = event.widget
            if button is self.root.focus_get() and button.instate(["!disabled"]):
                self.button_key_presses[event.keysym] = button, button.cget("text")
            else:
                self.button_key_presses[event.keysym] = None
        return "break"

    def remember_other_button_key(self, event):
        self.button_key_presses.setdefault(event.keysym, None)

    def configure_action_button(self, button, **options):
        for key, press in self.button_key_presses.items():
            if press is not None and press[0] is button:
                _, label = press
                if options.get("state") == "disabled" or options.get("text", label) != label:
                    self.button_key_presses[key] = None
        button.configure(**options)

    def release_button_key(self, event):
        press = self.button_key_presses.pop(event.keysym, None)
        if press is not None:
            button, label = press
            if (button is event.widget and button is self.root.focus_get()
                    and button.instate(["!disabled"]) and button.cget("text") == label):
                button.invoke()
        if event.widget in self.action_buttons:
            return "break"

    def cancel_button_key(self, event):
        if self.button_key_presses:
            for key, press in self.button_key_presses.items():
                if press is not None and press[0] is event.widget:
                    # Keep the key held until release so repeats cannot arm a new button.
                    self.button_key_presses[key] = None
            self.root.after_idle(self.remember_button_keys_outside_window)

    def remember_button_keys_outside_window(self):
        if not self.root.tk.call("focus", "-displayof", self.root):
            self.unfocused_button_keys = tuple(self.button_key_presses)
            for key in self.unfocused_button_keys:
                self.button_key_presses[key] = None

    def restore_button_key_focus(self, _event):
        keys, self.unfocused_button_keys = self.unfocused_button_keys, ()
        for key in keys:
            # A release in another window does not reach Tk.
            if key in self.button_key_presses and not self.mouse.action_key_held(key):
                del self.button_key_presses[key]

    def resize_header(self, event, title, language_controls):
        title.configure(wraplength=event.width)
        stacked = title.winfo_reqwidth() + language_controls.winfo_reqwidth() > event.width
        if stacked:
            language_controls.grid_configure(row=1, column=0, sticky="w", pady=(4, 0))
        else:
            language_controls.grid_configure(row=0, column=1, sticky="e", pady=0)

    def resize_dwell(self, event, settings, actions):
        stacked = settings.winfo_reqwidth() + actions.winfo_reqwidth() > event.width
        if stacked:
            actions.grid_configure(row=1, column=0, columnspan=2, pady=(4, 0))
        else:
            actions.grid_configure(row=0, column=1, columnspan=1, pady=0)

    def layout_choice(self, row, label, picker):
        label.grid(row=0, column=0, sticky="w")
        picker.grid(row=0, column=1, padx=(9, 0), sticky="w")

        def fit(event):
            if label.winfo_reqwidth() + picker.winfo_reqwidth() + 9 > event.width:
                picker.grid_configure(row=1, column=0, padx=0)
            else:
                picker.grid_configure(row=0, column=1, padx=(9, 0))

        row.bind("<Configure>", fit)

    def resize_footer(self, event):
        if event.widget is not self.root:
            return
        scale = self.root.winfo_fpixels("1i") / 96
        compact = event.width < 255 * scale or event.height < 140 * scale
        # Preserve room to scroll on small displays without scaling down the workspace text.
        tight = event.width < 175 * scale and event.height < 115 * scale
        if (compact, tight) == (self.compact_footer, self.tight_footer):
            return
        self.compact_footer, self.tight_footer = compact, tight
        if tight:
            button_style = "Tight.TButton"
        elif compact:
            button_style = "Compact.TButton"
        else:
            button_style = "TButton"
        self.camera_button.configure(style=button_style)
        self.pointer_button.configure(style=button_style)
        self.camera_button.pack_configure(padx=(0, 4 if compact else 8))
        self.workspace.master.configure(padx=12 if tight else 26, pady=8 if tight else 22)
        notice_font = ("Segoe UI", 8 if tight else 10, "bold")
        self.hotkey_label.configure(font=notice_font)
        self.footer_notice_label.configure(font=notice_font)
        if compact:
            self.footer_privacy.pack_forget()
            self.workspace_privacy.pack(fill="x", pady=(4, 0))
        else:
            self.workspace_privacy.pack_forget()
            self.footer_privacy.pack(fill="x", pady=(4, 0))
        self.refresh_action_labels()
        self.refresh_footer_notice()

    def resize_workspace(self, _event=None):
        viewport = self.workspace
        width, visible_height = viewport.winfo_width(), viewport.winfo_height()
        # Allow the natural layout to grow when optional settings appear.
        self.workspace_body.rowconfigure(0, minsize=visible_height)
        height = self.workspace_body.winfo_height()
        viewport.itemconfigure(self.workspace_window, width=width)
        viewport.configure(scrollregion=(0, 0, width, height))
        if height > visible_height:
            self.workspace_scrollbar.grid()
            self.reveal_workspace_focus()
        else:
            self.workspace_scrollbar.grid_remove()
            viewport.yview_moveto(0)
        self.refresh_footer_notice()

    def set_footer_notice(self, *keys):
        self.set_message("footer_notice", *keys)
        self.refresh_footer_notice()

    def refresh_footer_notice(self):
        if not self.workspace.winfo_ismapped():
            return
        notice = self.footer_notice_label
        available = self.workspace.winfo_height()
        if notice.winfo_ismapped():
            # Decide whether the workspace fits without reserving the notice itself.
            available += notice.winfo_height()
        compact = self.workspace_body.winfo_reqheight() > available
        if self.footer_notice.get() and (compact or self.compact_footer):
            if not notice.winfo_manager():
                notice.pack(fill="x", before=self.footer_controls)
        elif notice.winfo_manager():
            notice.pack_forget()
        if self.compact_footer and notice.winfo_manager():
            self.hotkey_label.pack_forget()
        elif not self.hotkey_label.winfo_manager():
            self.hotkey_label.pack(fill="x", pady=(9, 0), after=self.footer_controls)

    def in_workspace(self, widget):
        while widget is not None:
            if widget is self.workspace_body:
                return True
            widget = getattr(widget, "master", None)
        return False

    def reveal_workspace_focus(self, event=None):
        try:
            widget = event.widget if event is not None else self.root.focus_get()
        except KeyError:
            # A native combobox popdown can have focus without a Python widget.
            return
        if not self.in_workspace(widget) or not widget.winfo_ismapped():
            return
        viewport = self.workspace
        scroll_top = viewport.canvasy(0)
        view_height = viewport.winfo_height()
        widget_height = widget.winfo_height()
        # Compute a content coordinate, which does not lag behind canvas scrolling.
        top = 0
        while widget is not self.workspace_body:
            top += widget.winfo_y()
            widget = widget.master
        bottom = top + widget_height
        if top < scroll_top:
            destination = top
        elif bottom > scroll_top + view_height:
            destination = bottom - view_height
        else:
            return
        content_height = self.workspace_body.winfo_height()
        viewport.yview_moveto(destination / content_height)

    def scroll_workspace_wheel(self, event):
        if event.delta:
            direction = -1 if event.delta > 0 else 1
            return self.scroll_workspace(direction * max(1, abs(event.delta) // 120), "units")

    def scroll_workspace(self, amount, units):
        if self.workspace_scrollbar.winfo_ismapped():
            self.workspace.yview_scroll(amount, units)
            return "break"

    def text(self, key, **fields):
        return translate(self.language, key, **fields)

    def make_label(self, parent, key, **options):
        label = tk.Label(parent, text=self.text(key), bg=BACKGROUND, **options)
        self.static_labels.append((label, key))
        return label

    def set_message(self, target, *keys, **fields):
        self.messages[target] = (keys, fields)
        self.render_message(target)

    def render_message(self, target):
        keys, fields = self.messages[target]
        value = "\n".join(self.text(key, **fields) for key in keys)
        variable = getattr(self, target)
        if variable.get() != value:
            variable.set(value)

    def set_button(self, target, key, **options):
        self.button_labels[target] = key
        self.configure_action_button(getattr(self, target), text=self.action_text(key), **options)

    def action_text(self, key):
        return self.text(COMPACT_ACTION_LABELS.get(key, key) if self.compact_footer else key)

    def refresh_action_labels(self):
        self.hotkey_label.configure(text=self.text("hotkeys_short" if self.compact_footer else "hotkeys"))
        for target, key in self.button_labels.items():
            self.configure_action_button(getattr(self, target), text=self.action_text(key))

    def choice_labels(self, keys):
        return tuple(self.text(key) for key in keys)

    def choice_key(self, variable, keys):
        return next((key for key in keys if self.text(key) == variable.get()), None)

    def selected_click_mode(self):
        if self.settings.motion_only or self.args.no_clicks:
            return MOTION_MODE
        return DWELL_MODE if self.settings.dwell_seconds is not None else WINK_MODE

    def delay_choices(self):
        return {dwell_label(delay, self.language): delay for delay in self.dwell_presets}

    def change_language(self, _event=None):
        language = next((key for key, label in LANGUAGES.items() if label == self.language_choice.get()), None)
        if self.active or language is None:
            self.language_choice.set(LANGUAGES[self.language])
            return
        if language == self.language:
            return

        delay = self.dwell_durations[self.dwell_time.get()]
        sensitivity = (self.settings.range_x, self.settings.range_y, self.settings.dead_zone)
        preset = next(key for key, value in self.sensitivity_presets.items() if value == sensitivity)
        self.language = language
        self.dwell_durations = self.delay_choices()
        self.dwell_time.set(dwell_label(delay, self.language))
        self.delay_picker.configure(values=tuple(self.dwell_durations))
        self.sensitivity.set(self.text(preset))
        self.sensitivity_picker.configure(values=self.choice_labels(self.sensitivity_presets))
        self.click_mode.set(self.text(self.selected_click_mode()))
        self.mode_picker.configure(values=self.choice_labels(CLICK_MODES))
        for label, key in self.static_labels:
            label.configure(text=self.text(key))
        self.refresh_action_labels()
        for target in self.messages:
            self.render_message(target)
        self.refresh_right_dwell_button()
        save_language(language)

    def show_click_instructions(self):
        self.dwell_bar.configure(value=0)
        if self.settings.dwell_seconds is not None:
            self.dwell_controls.pack(fill="x", pady=(8, 0))
            if not self.args.no_clicks:
                self.right_dwell_button.pack(side="right")
            self.set_message("last_gesture", self.tracking_text_key("instruction_dwell"))
        else:
            self.dwell_controls.pack_forget()
            self.right_dwell_button.pack_forget()
            instruction = "instruction_motion" if self.settings.motion_only or self.args.no_clicks else "instruction_wink"
            self.set_message("last_gesture", instruction)
        self.refresh_right_dwell_button()

    def tracking_text_key(self, key):
        if self.settings.motion_only:
            return f"{key}_motion"
        if self.settings.dwell_seconds is not None and self.settings.dwell_eye is not None:
            return f"{key}_{self.settings.dwell_eye}"
        return key

    def refresh_right_dwell_button(self):
        armed = self.right_dwell_armed_at is not None
        available = self.settings.dwell_seconds is not None and not self.args.no_clicks
        self.configure_action_button(
            self.right_dwell_button,
            text=self.text("cancel" if armed else "right_click"),
            state="normal" if available and (self.can_enable or armed) else "disabled",
        )

    def clear_right_dwell(self, message="right_cancelled"):
        if self.right_dwell_armed_at is None:
            return
        self.right_dwell_armed_at = None
        self.refresh_right_dwell_button()
        if message is not None:
            self.set_message("last_gesture", message)

    def toggle_right_dwell(self):
        if self.right_dwell_armed_at is not None:
            self.cancel_right_dwell()
            return
        if not self.can_enable or self.settings.dwell_seconds is None or self.args.no_clicks:
            return
        self.right_dwell_armed_at = monotonic()
        self.refresh_right_dwell_button()
        self.set_message("last_gesture", "right_armed")
        self.tracker.reset_dwell()
        self.dwell_bar.configure(value=0)

    def cancel_right_dwell(self, _event=None):
        # A dwell on the cancel control arrives as a right-button release.
        self.clear_right_dwell(message=None)
        self.tracker.reset_dwell()
        self.dwell_bar.configure(value=0)
        self.set_message("last_gesture", "right_cancelled")
        return "break"

    def change_click_mode(self, event=None):
        if self.active or self.args.no_clicks:
            return
        mode = self.choice_key(self.click_mode, CLICK_MODES)
        if mode is None:
            return
        motion_only = mode == MOTION_MODE
        delay = self.dwell_durations[self.dwell_time.get()] if mode == DWELL_MODE else None
        dwell_seconds = delay / 1000 if delay is not None else None
        self.apply_tracking_settings(replace(self.settings, dwell_seconds=dwell_seconds, motion_only=motion_only))
        if event is not None and event.widget is self.delay_picker:
            if delay is not None:
                save_preference("dwell-ms", delay)
        else:
            save_preference("click-mode", mode)

    def change_sensitivity(self, _event=None):
        if self.active:
            return
        preset = self.choice_key(self.sensitivity, self.sensitivity_presets)
        if preset is None:
            return
        range_x, range_y, dead_zone = self.sensitivity_presets[preset]
        self.apply_tracking_settings(replace(self.settings, range_x=range_x, range_y=range_y, dead_zone=dead_zone))
        if preset in SENSITIVITY_PRESETS:
            save_preference("sensitivity", preset)

    def apply_tracking_settings(self, settings):
        if settings == self.settings:
            return
        self.settings = settings
        self.tracker = Tracker(settings)
        self.reset_calibration()
        self.position = (0.5, 0.5)
        self.draw_pad()
        self.configure_action_button(self.pointer_button, state="disabled")
        self.show_click_instructions()

    def draw_pad(self, _event=None):
        width, height = self.pad.winfo_width(), self.pad.winfo_height()
        self.pad.delete("all")
        self.pad.create_line(width / 2, 1, width / 2, height - 1, fill=EDGE)
        self.pad.create_line(1, height / 2, width - 1, height / 2, fill=EDGE)
        x, y = self.position
        px, py = 12 + x * (width - 24), 12 + y * (height - 24)
        self.pad.create_oval(px - 7, py - 7, px + 7, py + 7, fill=ACCENT, outline="")

    def toggle_camera(self):
        if self.camera and self.camera.thread.is_alive():
            self.stop_camera("status_stopping")
            return
        index = parse_camera_index(self.camera_index.get())
        if index is None:
            self.status_label.configure(height=3)
            self.set_message("status", "camera_index_invalid")
            self.set_footer_notice("camera_index_invalid")
            self.camera_picker.focus_set()
            self.camera_picker.selection_range(0, "end")
            return
        self.camera_index.set(str(index))
        self.disable_input()
        self.last_frame = None
        self.feed_stale = False
        self.safety_notice = ""
        self.set_footer_notice()
        self.position = (0.5, 0.5)
        self.draw_pad()
        self.show_click_instructions()
        self.set_message("mode", "mode_preview")
        self.status_label.configure(height=3)
        self.set_message("status", "status_opening")
        self.set_button("camera_button", "stop_camera")
        self.camera_picker.configure(state="disabled")
        try:
            self.camera = Camera(index, max_sample_gap_seconds=self.settings.max_sample_gap_seconds)
            self.camera.start()
            self.camera_index_to_save = index if index != self.last_camera_index else None
        except (OSError, RuntimeError) as error:
            self.finish_camera()
            self.status_label.configure(height=0)
            self.set_message("status", "camera_error_detail", detail=str(error))
            self.set_footer_notice("camera_error")

    def stop_camera(self, message, **fields):
        self.camera.stop()
        self.disable_input()
        self.set_button("camera_button", "open_camera", state="disabled")
        self.set_message("mode", "mode_input_off")
        self.status_label.configure(height=0 if message == "camera_error_detail" else 3)
        self.set_message("status", message, **fields)
        if message == "status_stopping":
            self.set_footer_notice()
        else:
            self.set_footer_notice(CAMERA_BRIEF_MESSAGES.get(message, message))

    def finish_camera(self):
        self.disable_input()
        self.camera = None
        self.camera_index_to_save = None
        self.camera_picker.configure(state="normal")
        self.set_button("camera_button", "open_camera", state="normal")
        self.set_message("mode", "mode_camera_off")

    def toggle_pointer(self):
        if self.active:
            self.pause()
            return
        if not self.can_enable or self.mouse.emergency_requested():
            return
        now = monotonic()
        ready_at = self.last_ready_frame_at
        if ready_at is None or not ready_at <= now <= ready_at + self.settings.max_sample_gap_seconds:
            self.pause_for_safety("safety_stale_preview")
            return
        try:
            self.mouse.begin_control()
        except ControlSessionBusy:
            self.pause_for_safety("safety_control_busy")
            return
        except OSError as error:
            self.stop_on_input_error(error)
            return
        self.active = True
        try:
            self.safety_notice = ""
            self.set_footer_notice()
            self.recenter_held = self.mouse.recenter_requested()
            self.last_active_face_at = now
            self.language_picker.configure(state="disabled")
            self.sensitivity_picker.configure(state="disabled")
            self.mode_picker.configure(state="disabled")
            self.delay_picker.configure(state="disabled")
            self.set_message("mode", "mode_active")
            self.set_button("pointer_button", "pause")
            self.recenter()
        except Exception:
            self._release_system_control()
            raise

    def request_recenter(self, _event=None):
        if not self.active or self.recenter_held:
            return
        if self.mouse.emergency_requested():
            self.pause()
            return
        self.recenter_held = True
        self.recenter()

    def recenter(self):
        requested_at = monotonic()
        self.reset_calibration()
        self.calibration_requested_at = requested_at
        self.set_message("status", self.tracking_text_key("status_recenter"))

    def reset_calibration(self):
        self.tracker.reset()
        self.calibration_requested_at = None
        self.can_enable = False
        self.last_ready_frame_at = None
        self.last_applied_position = None
        self.recovery_pending = False
        self.dwell_bar.configure(value=0)
        self.clear_right_dwell()
        self.refresh_right_dwell_button()

    def pause(self, _event=None):
        if self.active:
            self.reset_to_preview("status_paused")
        elif self.right_dwell_armed_at is not None:
            self.toggle_right_dwell()

    def _release_system_control(self):
        was_active = self.active
        self.active = False
        self.last_active_face_at = None
        if was_active:
            self.mouse.end_control()

    def disable_input(self):
        self._release_system_control()
        self.reset_calibration()
        self.language_picker.configure(state="readonly")
        self.sensitivity_picker.configure(state="readonly")
        self.mode_picker.configure(state="disabled" if self.args.no_clicks else "readonly")
        self.delay_picker.configure(state="readonly")
        self.set_button("pointer_button", "enable_mouse", state="disabled")

    def reset_to_preview(self, message):
        self.disable_input()
        self.set_message("mode", "mode_preview")
        self.set_message("status", message)

    def pause_for_safety(self, message):
        self.safety_notice = message
        self.reset_to_preview(message)
        self.set_footer_notice(f"{message}_brief")

    def stop_on_input_error(self, error):
        self.reset_to_preview("status_paused")
        self.set_message("last_gesture", "input_stopped", detail=str(error))
        self.set_footer_notice("input_stopped_brief")

    def cancel_unsafe_click(self):
        if self.mouse.button_held():
            self.pause_for_safety("safety_mouse_button")
            return True
        if self.mouse.position() == self.last_applied_position:
            return False
        self.pause_for_safety("safety_pointer_moved")
        return True

    def hold_for_stale_frame(self, captured_at):
        if not self.feed_stale:
            self.feed_stale = True
            self.update_tracking(captured_at, None)

    def update_tracking(self, now, sample):
        calibrating = not self.tracker.calibrated
        if calibrating and self.calibration_requested_at is not None and now < self.calibration_requested_at:
            # Inference can publish a frame captured before the new calibration was requested.
            return
        anchor = self.mouse.position() if self.active and calibrating and sample is not None else None
        dwell_projection = self.mouse.visible_position if self.active and self.settings.dwell_seconds is not None else None
        result = self.tracker.update(now, sample, calibration_position=anchor, dwell_projection=dwell_projection)
        if self.right_dwell_armed_at is not None and now < self.right_dwell_armed_at:
            # Frames already captured when the button was pressed cannot arm the next click.
            self.tracker.reset_dwell()
        if result.state == "face_jump":
            self.pause_for_safety("safety_jump")
            return
        if result.state == "paused":
            self.clear_right_dwell()
        elif self.active and self.last_active_face_at is not None:
            # Camera inference may finish after activation for a frame captured before it.
            self.last_active_face_at = max(self.last_active_face_at, now)
        if self.active and not calibrating:
            if result.state == "paused":
                self.recovery_pending = True
            elif self.recovery_pending and (result.position is not None or result.click):
                self.recovery_pending = False
                if self.mouse.position() != self.last_applied_position:
                    self.recenter()
                    return

        can_enable = result.state == "tracking"
        self.last_ready_frame_at = now if can_enable else None
        if self.can_enable != can_enable:
            self.can_enable = can_enable
            self.refresh_right_dwell_button()
        if not self.active:
            if can_enable and self.camera_index_to_save is not None:
                save_preference("camera", self.camera_index_to_save)
                self.last_camera_index = self.camera_index_to_save
                self.camera_index_to_save = None
            self.configure_action_button(self.pointer_button, state="normal" if self.can_enable else "disabled")
        hint = f"hint_{result.state}"
        if result.state in ("calibrating", "rearming"):
            hint = self.tracking_text_key(hint)
        keys = (self.safety_notice, hint) if self.safety_notice else (hint,)
        fields = {}
        if result.state == "calibrating":
            fields["progress"] = int(result.calibration_progress * 10) * 10
        if self.messages.get("status") != (keys, fields):
            self.set_message("status", *keys, **fields)
        if self.settings.dwell_seconds is not None:
            self.dwell_bar.configure(value=result.dwell_progress * 100)
        click = None if self.args.no_clicks or self.settings.motion_only else result.click
        system_click = self.active and click is not None
        valid_until = now + self.settings.max_sample_gap_seconds
        if result.position is not None:
            # Check before a dwell frame can interfere with manual input.
            if system_click and self.cancel_unsafe_click():
                return
            if self.position != result.position:
                self.position = result.position
                self.draw_pad()
            if self.active:
                self.last_applied_position = (
                    anchor if calibrating else self.mouse.move(*result.position, valid_until=valid_until)
                )
        if click is not None:
            if system_click and self.cancel_unsafe_click():
                return
            button = click
            right_dwell = self.settings.dwell_seconds is not None and self.right_dwell_armed_at is not None
            if right_dwell:
                button = "right"
            elif self.args.swap_buttons and self.settings.dwell_seconds is None:
                button = "right" if button == "left" else "left"
            if system_click:
                self.mouse.click(button, expected_position=self.last_applied_position, valid_until=valid_until)
            if right_dwell:
                self.clear_right_dwell(message=None)
            mode = "active" if self.active else "preview"
            self.set_message("last_gesture", f"gesture_{mode}_{button}")

    def poll(self):
        if self.active:
            if self.mouse.emergency_requested():
                self.pause()
            elif self.mouse.recenter_requested():
                self.request_recenter()
            else:
                self.recenter_held = False
        if self.camera:
            jump_limit = self.settings.max_nose_jump if self.active and self.tracker.calibrated else None
            latest, error = self.camera.snapshot(
                interrupts_gesture=self.tracker.interrupts_pending_click, after_capture_at=self.last_frame,
                max_nose_jump=jump_limit,
            )
            now = monotonic()
            if (self.active and self.last_active_face_at is not None
                    and now >= self.last_active_face_at + FACE_LOSS_GRACE_SECONDS):
                self.pause_for_safety("safety_loss")
            if error is not None and not self.camera.stop_event.is_set():
                self.stop_camera(error.key, detail=error.detail)
            if not self.camera.thread.is_alive():
                stopped_by_user = self.messages["status"][0] == ("status_stopping",)
                self.finish_camera()
                if error is None or stopped_by_user:
                    self.status_label.configure(height=3)
                    self.set_message("status", "status_camera_off")
                    self.set_footer_notice()
            elif latest and not self.camera.stop_event.is_set():
                captured_at, sample = latest
                previous_face_at = self.last_active_face_at
                try:
                    if sample is AMBIGUOUS_FACE or sample is FACE_JUMP:
                        if self.last_frame != captured_at:
                            self.last_frame = captured_at
                            reason = "safety_multiple" if sample is AMBIGUOUS_FACE else "safety_jump"
                            self.pause_for_safety(reason)
                    elif now > captured_at + self.settings.max_sample_gap_seconds:
                        self.hold_for_stale_frame(captured_at)
                    elif self.last_frame != captured_at:
                        self.feed_stale = False
                        if (self.last_frame is not None
                                and captured_at - self.last_frame > self.settings.max_sample_gap_seconds):
                            self.clear_right_dwell()
                            if self.active and self.tracker.calibrated:
                                self.recovery_pending = True
                        self.last_frame = captured_at
                        self.update_tracking(captured_at, sample)
                except EmergencyPauseRequested:
                    self.pause()
                except InputFrameExpired:
                    # Rejecting a frame at dispatch also leaves the loss timer unchanged.
                    self.last_active_face_at = previous_face_at
                    self.hold_for_stale_frame(captured_at)
                except DisplayLayoutChanged:
                    self.pause_for_safety("safety_display_changed")
                except PointerMoved:
                    self.pause_for_safety("safety_pointer_moved")
                except MouseButtonHeld:
                    self.pause_for_safety("safety_mouse_button")
                except OSError as error:
                    self.stop_on_input_error(error)
        self.root.after(16, self.poll)

    def close(self):
        self._release_system_control()
        if self.camera:
            self.camera.stop()
        self.root.destroy()


def load_tracking_settings(args):
    if args.range_x is None and args.range_y is None:
        preset = load_text_preference("sensitivity")
        range_x, range_y, dead_zone = SENSITIVITY_PRESETS.get(preset, SENSITIVITY_PRESETS["sensitivity_standard"])
    else:
        range_x = Settings.range_x if args.range_x is None else args.range_x
        range_y = Settings.range_y if args.range_y is None else args.range_y
        dead_zone = Settings.dead_zone

    if args.dwell_ms is not None:
        mode, dwell_ms = DWELL_MODE, args.dwell_ms
    else:
        if args.no_clicks:
            mode = MOTION_MODE
        elif args.dwell_eye is not None:
            mode = DWELL_MODE
        else:
            mode = load_text_preference("click-mode")
        saved_delay = load_text_preference("dwell-ms")
        dwell_ms = int(saved_delay) if saved_delay.isdecimal() else DEFAULT_DWELL_MS
        if not MIN_DWELL_MS <= dwell_ms <= MAX_DWELL_MS:
            dwell_ms = DEFAULT_DWELL_MS

    settings = Settings(mirror=not args.no_mirror, range_x=range_x, range_y=range_y,
                        dead_zone=dead_zone, wink_min_seconds=args.wink_ms / 1000,
                        dwell_seconds=dwell_ms / 1000 if mode == DWELL_MODE else None,
                        motion_only=mode == MOTION_MODE, dwell_eye=args.dwell_eye)
    return settings, dwell_ms


def main(argv=None):
    language_option = argparse.ArgumentParser(add_help=False)
    language_option.add_argument("--lang", choices=LANGUAGES)
    language = language_option.parse_known_args(argv)[0].lang or "en"

    def text(key):
        return translate(language, key)

    parser = argparse.ArgumentParser(description=text("cli_description"), epilog=text("cli_hotkeys"), add_help=False)
    parser.add_argument("-h", "--help", action="help", help=text("cli_help"))
    parser.add_argument("--lang", choices=LANGUAGES, help=text("cli_lang"))
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--download-model", action="store_true", help=text("cli_download"))
    commands.add_argument("--check", action="store_true", help=text("cli_check"))
    parser.add_argument("--camera", type=int, help=text("cli_camera"))
    parser.add_argument("--range-x", type=float, help=text("cli_range_x"))
    parser.add_argument("--range-y", type=float, help=text("cli_range_y"))
    parser.add_argument("--wink-ms", type=int, default=220, help=text("cli_wink"))
    parser.add_argument("--no-mirror", action="store_true", help=text("cli_no_mirror"))
    parser.add_argument("--swap-buttons", action="store_true", help=text("cli_swap"))
    clicks = parser.add_mutually_exclusive_group()
    clicks.add_argument("--no-clicks", action="store_true", help=text("cli_no_clicks"))
    clicks.add_argument("--dwell-ms", type=int, help=text("cli_dwell"))
    parser.add_argument("--dwell-eye", choices=("left", "right"), help=text("cli_dwell_eye"))
    args = parser.parse_args(argv)
    if args.lang is None and not (args.download_model or args.check):
        args.lang = load_language()
    language = args.lang or "en"
    if args.dwell_ms is not None and not MIN_DWELL_MS <= args.dwell_ms <= MAX_DWELL_MS:
        parser.error(text("cli_dwell_invalid"))
    if args.no_clicks and args.dwell_eye is not None:
        parser.error(text("cli_dwell_eye_conflict"))
    try:
        if args.download_model:
            download_model()
            print(text("model_ready"))
            return
        if args.check:
            check_inference()
            print(text("model_check_ok"))
            return
        if sys.platform != "win32":
            parser.error(text("cli_platform"))
        if args.camera is None:
            args.camera = parse_camera_index(load_text_preference("camera")) or 0
        if not 0 <= args.camera <= MAX_CAMERA_INDEX:
            parser.error(text("cli_camera_invalid"))

        from windows_mouse import WindowsMouse, enable_dpi_awareness

        settings, dwell_ms = load_tracking_settings(args)
        enable_dpi_awareness()
        mouse = WindowsMouse()
        root = tk.Tk()
        PointerApp(root, mouse, settings, args, initial_dwell_ms=dwell_ms)
        root.mainloop()
    except CameraError as error:
        parser.exit(1, f"Nose Pointer: {text(error.key)}\n")
    except (ImportError, OSError, RuntimeError, ValueError, tk.TclError) as error:
        parser.exit(1, f"Nose Pointer: {error}\n")


if __name__ == "__main__":
    main()
