"""Windows webcam pointer with an explicit preview and an emergency pause."""

import argparse
import sys
import tkinter as tk
from dataclasses import replace
from time import monotonic
from tkinter import ttk

from camera import AMBIGUOUS_FACE, Camera, CameraError, check_inference, download_model
from i18n import LANGUAGES, load_language, save_language, translate
from preferences import load_text_preference, save_preference
from tracking import Settings, Tracker


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

def dwell_label(milliseconds, language):
    value = f"{milliseconds / 1000:g}"
    return value.replace(".", ",") if language == "ru" else value


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
        self.active = False
        self.recenter_held = False
        self.last_frame = None
        self.last_ready_frame_at: float | None = None
        self.last_active_face_at: float | None = None
        self.last_applied_position = None
        self.recovery_pending = False
        self.right_dwell_armed_at: float | None = None
        self.feed_stale = False
        self.can_enable = False
        self.safety_notice = ""
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
        tk.Label(header, text="Nose Pointer", font=("Segoe UI", 26, "bold"),
                 bg=BACKGROUND, fg=INK, anchor="w").pack(side="left")
        self.language_choice = tk.StringVar(value=LANGUAGES[self.language])
        self.language_picker = ttk.Combobox(header, textvariable=self.language_choice,
                                            values=tuple(LANGUAGES.values()), width=9, state="readonly")
        self.language_picker.pack(side="right")
        self.language_picker.bind("<<ComboboxSelected>>", self.change_language)
        self.make_label(header, "language", font=("Segoe UI", 10), fg=INK).pack(side="right", padx=(0, 7))
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
        self.make_label(sensitivity_row, "sensitivity", font=("Segoe UI", 10), fg=INK).pack(side="left", padx=(0, 9))
        self.sensitivity_presets = SENSITIVITY_PRESETS.copy()
        initial_range = (settings.range_x, settings.range_y, settings.dead_zone)
        selected_sensitivity = next((label for label, preset in self.sensitivity_presets.items()
                                     if preset == initial_range), "sensitivity_custom")
        self.sensitivity_presets[selected_sensitivity] = initial_range
        self.sensitivity = tk.StringVar(value=self.text(selected_sensitivity))
        self.sensitivity_picker = ttk.Combobox(sensitivity_row, textvariable=self.sensitivity,
                                               values=self.choice_labels(self.sensitivity_presets), width=12, state="readonly")
        self.sensitivity_picker.pack(side="left")
        self.sensitivity_picker.bind("<<ComboboxSelected>>", self.change_sensitivity)

        click_row = tk.Frame(settings_controls, bg=BACKGROUND)
        click_row.pack(fill="x")
        self.make_label(click_row, "click_mode", font=("Segoe UI", 10), fg=INK).pack(side="left", padx=(0, 9))
        self.click_mode = tk.StringVar(value=self.text(self.selected_click_mode()))
        self.mode_picker = ttk.Combobox(click_row, textvariable=self.click_mode,
                                       values=self.choice_labels(CLICK_MODES), width=18,
                                       state="disabled" if args.no_clicks else "readonly")
        self.mode_picker.pack(side="left")
        self.mode_picker.bind("<<ComboboxSelected>>", self.change_click_mode)
        current_delay = round(settings.dwell_seconds * 1000) if settings.dwell_seconds is not None else initial_dwell_ms
        self.dwell_presets = tuple(sorted({*DWELL_PRESETS_MS, current_delay}))
        self.dwell_durations = self.delay_choices()
        self.dwell_time = tk.StringVar(value=dwell_label(current_delay, self.language))
        self.dwell_controls = tk.Frame(settings_controls, bg=BACKGROUND)
        self.make_label(self.dwell_controls, "dwell_delay", font=("Segoe UI", 10), fg=INK).pack(side="left", padx=(0, 9))
        self.delay_picker = ttk.Combobox(self.dwell_controls, textvariable=self.dwell_time,
                                        values=tuple(self.dwell_durations), width=6, state="readonly")
        self.delay_picker.pack(side="left")
        self.delay_picker.bind("<<ComboboxSelected>>", self.change_click_mode)
        self.dwell_bar = ttk.Progressbar(self.dwell_controls, length=65, maximum=100, mode="determinate")
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
        self.right_dwell_button = ttk.Button(self.dwell_controls, command=self.toggle_right_dwell)
        self.right_dwell_button.bind("<ButtonRelease-3>", self.cancel_right_dwell)
        self.show_click_instructions()
        hotkey_label = self.make_label(footer, "hotkeys", font=("Segoe UI", 10, "bold"), fg=INK,
                                       anchor="w", justify="left", wraplength=430)
        hotkey_label.pack(fill="x", pady=(9, 0))
        hotkey_label.bind("<Configure>", lambda event: hotkey_label.configure(wraplength=event.width))
        privacy_key = "privacy_no_clicks" if args.no_clicks else "privacy"
        privacy_label = self.make_label(footer, privacy_key, font=("Segoe UI", 9), fg=MUTED,
                                        anchor="w", justify="left", wraplength=430)
        privacy_label.pack(fill="x", pady=(4, 0))
        privacy_label.bind("<Configure>", lambda event: privacy_label.configure(wraplength=event.width))
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
        self.camera_button.focus_set()
        root.after(16, self.poll)

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
        if self.footer_notice.get() and compact:
            if not notice.winfo_manager():
                notice.pack(fill="x", before=self.footer_controls)
        elif notice.winfo_manager():
            notice.pack_forget()

    def in_workspace(self, widget):
        while widget is not None:
            if widget is self.workspace:
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
        top = widget.winfo_rooty() - viewport.winfo_rooty()
        bottom = top + widget.winfo_height()
        if top < 0:
            offset = top
        elif bottom > view_height:
            offset = bottom - view_height
        else:
            return
        content_height = self.workspace_body.winfo_height()
        viewport.yview_moveto((scroll_top + offset) / content_height)

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
        getattr(self, target).configure(text=self.text(key), **options)

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
        for target, key in self.button_labels.items():
            getattr(self, target).configure(text=self.text(key))
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
            self.set_message("last_gesture", "instruction_dwell")
        else:
            self.dwell_controls.pack_forget()
            self.right_dwell_button.pack_forget()
            instruction = "instruction_motion" if self.settings.motion_only or self.args.no_clicks else "instruction_wink"
            self.set_message("last_gesture", instruction)
        self.refresh_right_dwell_button()

    def refresh_right_dwell_button(self):
        armed = self.right_dwell_armed_at is not None
        available = self.settings.dwell_seconds is not None and not self.args.no_clicks
        self.right_dwell_button.configure(
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
        self.pointer_button.configure(state="disabled")
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
        choice = self.camera_index.get().strip()
        index = int(choice) if 0 < len(choice) <= 10 and choice.isascii() and choice.isdecimal() else -1
        if not 0 <= index <= MAX_CAMERA_INDEX:
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
            self.camera = Camera(index)
            self.camera.start()
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
        self.safety_notice = ""
        self.set_footer_notice()
        self.recenter_held = self.mouse.recenter_requested()
        self.last_active_face_at = now
        self.active = True
        self.language_picker.configure(state="disabled")
        self.sensitivity_picker.configure(state="disabled")
        self.mode_picker.configure(state="disabled")
        self.delay_picker.configure(state="disabled")
        self.set_message("mode", "mode_active")
        self.set_button("pointer_button", "pause")
        self.recenter()

    def request_recenter(self, _event=None):
        if not self.active or self.recenter_held:
            return
        if self.mouse.emergency_requested():
            self.pause()
            return
        self.recenter_held = True
        self.recenter()

    def recenter(self):
        self.reset_calibration()
        self.set_message("status", "status_recenter_motion" if self.settings.motion_only else "status_recenter")

    def reset_calibration(self):
        self.tracker.reset()
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

    def disable_input(self):
        self.active = False
        self.last_active_face_at = None
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

    def cancel_unsafe_click(self):
        if self.mouse.button_held():
            self.pause_for_safety("safety_mouse_button")
            return True
        if self.mouse.position() == self.last_applied_position:
            return False
        self.pause_for_safety("safety_pointer_moved")
        return True

    def update_tracking(self, now, sample):
        calibrating = not self.tracker.calibrated
        anchor = self.mouse.position() if self.active and calibrating and sample is not None else None
        result = self.tracker.update(now, sample, calibration_position=anchor)
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
            self.pointer_button.configure(state="normal" if self.can_enable else "disabled")
        hint = f"hint_{result.state}"
        if self.settings.motion_only and result.state in ("calibrating", "rearming"):
            hint += "_motion"
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
        if result.position is not None:
            # Check before a dwell frame can interfere with manual input.
            if system_click and self.cancel_unsafe_click():
                return
            if self.position != result.position:
                self.position = result.position
                self.draw_pad()
            if self.active:
                self.last_applied_position = anchor if calibrating else self.mouse.move(*result.position)
        if click is not None:
            if system_click and self.cancel_unsafe_click():
                return
            button = click
            if self.settings.dwell_seconds is not None and self.right_dwell_armed_at is not None:
                button = "right"
                self.clear_right_dwell(message=None)
            elif self.args.swap_buttons and self.settings.dwell_seconds is None:
                button = "right" if button == "left" else "left"
            if system_click:
                self.mouse.click(button)
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
            latest, error = self.camera.snapshot()
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
                try:
                    if sample is AMBIGUOUS_FACE:
                        if self.last_frame != captured_at:
                            self.last_frame = captured_at
                            self.pause_for_safety("safety_multiple")
                    elif now - captured_at > self.settings.max_sample_gap_seconds:
                        if not self.feed_stale:
                            self.feed_stale = True
                            self.update_tracking(captured_at, None)
                    elif self.last_frame != captured_at:
                        self.feed_stale = False
                        if (self.last_frame is not None
                                and captured_at - self.last_frame > self.settings.max_sample_gap_seconds):
                            self.clear_right_dwell()
                            if self.active and self.tracker.calibrated:
                                self.recovery_pending = True
                        self.last_frame = captured_at
                        self.update_tracking(captured_at, sample)
                except OSError as error:
                    self.pause()
                    self.set_message("last_gesture", "input_stopped", detail=str(error))
                    self.set_footer_notice("input_stopped_brief")
        self.root.after(16, self.poll)

    def close(self):
        self.active = False
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
        mode = MOTION_MODE if args.no_clicks else load_text_preference("click-mode")
        saved_delay = load_text_preference("dwell-ms")
        dwell_ms = int(saved_delay) if saved_delay.isdecimal() else DEFAULT_DWELL_MS
        if not MIN_DWELL_MS <= dwell_ms <= MAX_DWELL_MS:
            dwell_ms = DEFAULT_DWELL_MS

    settings = Settings(mirror=not args.no_mirror, range_x=range_x, range_y=range_y,
                        dead_zone=dead_zone, wink_min_seconds=args.wink_ms / 1000,
                        dwell_seconds=dwell_ms / 1000 if mode == DWELL_MODE else None,
                        motion_only=mode == MOTION_MODE)
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
    parser.add_argument("--camera", type=int, default=0, help=text("cli_camera"))
    parser.add_argument("--range-x", type=float, help=text("cli_range_x"))
    parser.add_argument("--range-y", type=float, help=text("cli_range_y"))
    parser.add_argument("--wink-ms", type=int, default=220, help=text("cli_wink"))
    parser.add_argument("--no-mirror", action="store_true", help=text("cli_no_mirror"))
    parser.add_argument("--swap-buttons", action="store_true", help=text("cli_swap"))
    clicks = parser.add_mutually_exclusive_group()
    clicks.add_argument("--no-clicks", action="store_true", help=text("cli_no_clicks"))
    clicks.add_argument("--dwell-ms", type=int, help=text("cli_dwell"))
    args = parser.parse_args(argv)
    if args.lang is None and not (args.download_model or args.check):
        args.lang = load_language()
    language = args.lang or "en"
    if args.dwell_ms is not None and not MIN_DWELL_MS <= args.dwell_ms <= MAX_DWELL_MS:
        parser.error(text("cli_dwell_invalid"))
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
