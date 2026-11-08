"""Windows webcam pointer with an explicit preview and an emergency pause."""

import argparse
import sys
import tkinter as tk
from time import monotonic
from tkinter import ttk

from camera import Camera, check_inference, download_model
from tracking import Settings, Tracker


BACKGROUND = "#f7f5ef"
PAPER = "#fffdf7"
INK = "#23271f"
MUTED = "#565c50"
EDGE = "#dedbd1"
ACCENT = "#315538"

TRACKING_HINTS = {
    "calibrating": "Смотрите прямо и держите оба глаза открытыми.",
    "tracking": "Лицо в кадре. Двигайте носом небольшими движениями.",
    "wink": "Подмигивание. Точка ждёт, пока глаз откроется.",
    "rearming": "Держите оба глаза открытыми, чтобы продолжить.",
    "paused": "Лицо потеряно или кадры задерживаются. Ввод приостановлен.",
}


class PointerApp:
    def __init__(self, root, mouse, settings, args):
        self.root = root
        self.mouse = mouse
        self.settings = settings
        self.args = args
        self.tracker = Tracker(settings)
        self.camera = None
        self.active = False
        self.last_frame = None
        self.feed_stale = False
        self.can_enable = False
        self.position = (0.5, 0.5)

        root.title("Nose Pointer")
        root.configure(bg=BACKGROUND)
        root.geometry("580x570")
        root.minsize(490, 535)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Escape>", self.pause)

        style = ttk.Style(root)
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 8))
        frame = tk.Frame(root, bg=BACKGROUND, padx=26, pady=22)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="Nose Pointer", font=("Segoe UI", 26, "bold"),
                 bg=BACKGROUND, fg=INK, anchor="w").pack(fill="x")
        tk.Label(frame, text="Управление указателем через веб-камеру", font=("Segoe UI", 11),
                 bg=BACKGROUND, fg=MUTED, anchor="w").pack(fill="x", pady=(2, 17))

        self.mode = tk.StringVar(value="КАМЕРА ВЫКЛЮЧЕНА")
        tk.Label(frame, textvariable=self.mode, font=("Segoe UI", 11, "bold"),
                 bg=BACKGROUND, fg=ACCENT, anchor="w").pack(fill="x")
        self.status = tk.StringVar(value="Откройте камеру, чтобы проверить управление в режиме пробы.")
        self.status_label = tk.Label(frame, textvariable=self.status, font=("Segoe UI", 10),
                                     bg=BACKGROUND, fg=INK, anchor="nw", justify="left", height=3)
        self.status_label.pack(fill="x", pady=(4, 4))
        self.status_label.bind("<Configure>", lambda event: self.status_label.configure(wraplength=event.width))

        self.pad = tk.Canvas(frame, bg=PAPER, height=170, highlightthickness=1, highlightbackground=EDGE)
        self.pad.pack(fill="both", expand=True)
        self.pad.bind("<Configure>", self.draw_pad)
        self.last_gesture = tk.StringVar(value="Тестовое поле  ·  Подмигните одним глазом и откройте его")
        tk.Label(frame, textvariable=self.last_gesture, font=("Segoe UI", 10),
                 bg=BACKGROUND, fg=MUTED, anchor="w").pack(fill="x", pady=(8, 14))

        controls = tk.Frame(frame, bg=BACKGROUND)
        controls.pack(fill="x")
        self.camera_button = ttk.Button(controls, text="Открыть камеру", command=self.toggle_camera)
        self.camera_button.pack(side="left", padx=(0, 8))
        self.pointer_button = ttk.Button(controls, text="Включить мышь", command=self.toggle_pointer, state="disabled")
        self.pointer_button.pack(side="left")
        tk.Label(controls, text="F8  ·  Пауза", font=("Segoe UI", 10, "bold"),
                 bg=BACKGROUND, fg=INK).pack(side="right")
        privacy = "Кадры обрабатываются на этом компьютере"
        if args.no_clicks:
            privacy = "Клики отключены  ·  " + privacy
        tk.Label(frame, text=privacy, font=("Segoe UI", 9), bg=BACKGROUND,
                 fg=MUTED, anchor="w").pack(fill="x", pady=(12, 0))
        self.camera_button.focus_set()
        root.after(16, self.poll)

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
            self.stop_camera("Камера выключается…")
            return
        self.tracker.reset()
        self.last_frame = None
        self.feed_stale = False
        self.position = (0.5, 0.5)
        self.draw_pad()
        self.last_gesture.set("Тестовое поле  ·  Подмигните одним глазом и откройте его")
        self.mode.set("ПРОБА  ·  СИСТЕМНАЯ МЫШЬ ВЫКЛЮЧЕНА")
        self.status.set("Открываем камеру…")
        self.camera_button.configure(text="Выключить камеру")
        self.camera = Camera(self.args.camera)
        self.camera.start()

    def stop_camera(self, message):
        self.camera.stop()
        self.active = self.can_enable = False
        self.pointer_button.configure(text="Включить мышь", state="disabled")
        self.camera_button.configure(text="Открыть камеру", state="disabled")
        self.mode.set("СИСТЕМНАЯ МЫШЬ ВЫКЛЮЧЕНА")
        self.status.set(message)

    def toggle_pointer(self):
        if self.active:
            self.pause()
            return
        if not self.can_enable or self.mouse.emergency_requested():
            return
        self.tracker.reset()
        self.active = True
        self.mode.set("СИСТЕМНАЯ МЫШЬ ВКЛЮЧЕНА")
        self.pointer_button.configure(text="Пауза")
        self.status.set("Повторная калибровка. Смотрите прямо и откройте оба глаза.")

    def pause(self, _event=None):
        if not self.active:
            return
        self.active = self.can_enable = False
        self.tracker.reset()
        self.mode.set("ПРОБА  ·  СИСТЕМНАЯ МЫШЬ ВЫКЛЮЧЕНА")
        self.status.set("Пауза. Чтобы снова управлять мышью, включите её кнопкой.")
        self.pointer_button.configure(text="Включить мышь", state="disabled")

    def update_tracking(self, now, sample):
        result = self.tracker.update(now, sample)
        self.can_enable = result.state == "tracking"
        if not self.active:
            self.pointer_button.configure(state="normal" if self.can_enable else "disabled")
        hint = TRACKING_HINTS[result.state]
        if self.status.get() != hint:
            self.status.set(hint)
        if result.position is not None:
            if self.position != result.position:
                self.position = result.position
                self.draw_pad()
            if self.active:
                self.mouse.move(*result.position)
        if result.click and not self.args.no_clicks:
            button = result.click
            if self.args.swap_buttons:
                button = "right" if button == "left" else "left"
            if self.active:
                self.mouse.click(button)
            label = "Левый" if button == "left" else "Правый"
            mode = "Системная мышь" if self.active else "Проба"
            self.last_gesture.set(f"{mode}  ·  {label} клик")

    def poll(self):
        if self.active and self.mouse.emergency_requested():
            self.pause()
        if self.camera:
            latest, error = self.camera.snapshot()
            if error and not self.camera.stop_event.is_set():
                self.stop_camera(error)
            if not self.camera.thread.is_alive():
                self.camera = None
                self.camera_button.configure(state="normal", text="Открыть камеру")
                self.mode.set("КАМЕРА ВЫКЛЮЧЕНА")
                if not error:
                    self.status.set("Камера выключена. Её можно открыть снова.")
            elif latest and not self.camera.stop_event.is_set():
                captured_at, sample = latest
                now = monotonic()
                try:
                    if now - captured_at > self.settings.max_sample_gap_seconds:
                        if not self.feed_stale:
                            self.feed_stale = True
                            self.update_tracking(captured_at, None)
                    elif self.last_frame != captured_at:
                        self.feed_stale = False
                        self.last_frame = captured_at
                        self.update_tracking(captured_at, sample)
                except OSError as error:
                    self.pause()
                    self.last_gesture.set(f"Ввод остановлен: {error}")
        self.root.after(16, self.poll)

    def close(self):
        self.active = False
        if self.camera:
            self.camera.stop()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--download-model", action="store_true", help="fetch and verify the local model")
    commands.add_argument("--check", action="store_true", help="run the model on a blank frame without opening a camera")
    parser.add_argument("--camera", type=int, default=0, help="webcam index, normally 0")
    parser.add_argument("--range-x", type=float, default=0.12, help="horizontal nose displacement from center to screen edge")
    parser.add_argument("--range-y", type=float, default=0.10, help="vertical nose displacement from center to screen edge")
    parser.add_argument("--wink-ms", type=int, default=220, help="minimum intentional wink duration in milliseconds")
    parser.add_argument("--no-mirror", action="store_true", help="reverse horizontal direction")
    parser.add_argument("--swap-buttons", action="store_true", help="exchange left and right wink actions")
    parser.add_argument("--no-clicks", action="store_true", help="enable pointer motion only")
    args = parser.parse_args()
    try:
        if args.download_model:
            download_model()
            print("Модель готова.")
            return
        if args.check:
            check_inference()
            print("Модель и обработка кадров работают. Камера оставалась выключенной.")
            return
        if sys.platform != "win32":
            parser.error("Системный ввод поддерживается в Windows.")
        if args.camera < 0:
            parser.error("Индекс камеры не может быть отрицательным.")

        from windows_mouse import WindowsMouse, enable_dpi_awareness

        settings = Settings(mirror=not args.no_mirror, range_x=args.range_x,
                            range_y=args.range_y, wink_min_seconds=args.wink_ms / 1000)
        enable_dpi_awareness()
        mouse = WindowsMouse()
        root = tk.Tk()
        PointerApp(root, mouse, settings, args)
        root.mainloop()
    except (ImportError, OSError, RuntimeError, ValueError, tk.TclError) as error:
        parser.exit(1, f"Nose Pointer: {error}\n")


if __name__ == "__main__":
    main()
