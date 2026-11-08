"""Map normalized face samples to pointer positions and wink clicks."""

from dataclasses import dataclass
from math import expm1, hypot, isfinite
from typing import Literal

Click = Literal["left", "right"]
TrackingState = Literal["calibrating", "tracking", "wink", "rearming", "paused", "face_jump"]


@dataclass(frozen=True)
class Settings:
    mirror: bool = True
    range_x: float = 0.12
    range_y: float = 0.10
    dead_zone: float = 0.012
    smoothing_seconds: float = 0.09
    calibration_seconds: float = 0.80
    open_threshold: float = 0.30
    closed_threshold: float = 0.70
    wink_min_seconds: float = 0.22
    wink_max_seconds: float = 0.85
    click_cooldown_seconds: float = 0.45
    rearm_seconds: float = 0.15
    max_sample_gap_seconds: float = 0.25
    max_nose_jump: float = 0.20

    def __post_init__(self) -> None:
        ranges = (self.range_x, self.range_y, self.dead_zone)
        if not all(isfinite(value) for value in ranges):
            raise ValueError("Pointer ranges and dead zone must be finite.")
        if not 0 <= self.dead_zone < min(self.range_x, self.range_y):
            raise ValueError("The dead zone must be smaller than both pointer ranges.")
        if not 0 <= self.open_threshold < self.closed_threshold <= 1:
            raise ValueError("Eye thresholds must be ordered between zero and one.")
        if not isfinite(self.max_nose_jump) or self.max_nose_jump <= 0:
            raise ValueError("The maximum nose jump must be finite and positive.")

        timings = (
            self.smoothing_seconds, self.calibration_seconds, self.wink_min_seconds,
            self.wink_max_seconds, self.click_cooldown_seconds, self.rearm_seconds,
            self.max_sample_gap_seconds,
        )
        if not all(isfinite(value) and value >= 0 for value in timings):
            raise ValueError("Timing settings must be finite and nonnegative.")
        if not 0 < self.wink_min_seconds <= self.wink_max_seconds:
            raise ValueError("Wink durations must be positive and ordered.")
        if self.max_sample_gap_seconds == 0:
            raise ValueError("The maximum sample gap must be positive.")


@dataclass(frozen=True)
class FaceSample:
    """Camera coordinates and anatomical left/right blink scores, all from zero to one."""

    nose_x: float
    nose_y: float
    left_blink: float
    right_blink: float


@dataclass(frozen=True)
class TrackingOutput:
    """A missing position means hold the cursor. A click is a one-update event."""

    position: tuple[float, float] | None
    click: Click | None
    state: TrackingState
    calibration_progress: float

    @property
    def calibrated(self) -> bool:
        return self.calibration_progress == 1.0


class Tracker:
    """Calibrate a neutral point, smooth motion, and recognize isolated winks."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings if settings is not None else Settings()
        self.reset()

    def reset(self) -> None:
        """Forget calibration and all tracking and gesture history."""
        self._neutral: tuple[float, float] | None = None
        self._position = (0.5, 0.5)
        self._last_update: float | None = None
        self._last_nose: tuple[float, float] | None = None
        self._last_click: float | None = None
        self._break_continuity()

    def _break_continuity(self) -> None:
        self._calibration_start: float | None = None
        self._calibration_count = 0
        self._calibration_x = 0.0
        self._calibration_y = 0.0
        self._open_since: float | None = None
        self._armed = False
        self._wink: Click | None = None
        self._wink_start = 0.0
        self._wink_seen_again = False

    def update(self, now: float, sample: FaceSample | None) -> TrackingOutput:
        """Process one observation at a finite, non-decreasing monotonic time."""
        if not isfinite(now) or (self._last_update is not None and now < self._last_update):
            raise ValueError("Tracking time must be finite and non-decreasing.")

        elapsed = now - self._last_update if self._last_update is not None else 0.0
        if elapsed > self.settings.max_sample_gap_seconds:
            self._break_continuity()
            self._last_nose = None
            elapsed = 0.0
        self._last_update = now

        if sample is None or not all(0 <= value <= 1 for value in (
            sample.nose_x, sample.nose_y, sample.left_blink, sample.right_blink
        )):
            self._break_continuity()
            self._last_nose = None
            return self._hold("paused")

        previous_nose = self._last_nose
        self._last_nose = (sample.nose_x, sample.nose_y)
        if previous_nose is not None and hypot(
            sample.nose_x - previous_nose[0], sample.nose_y - previous_nose[1]
        ) > self.settings.max_nose_jump:
            self._neutral = None
            self._position = (0.5, 0.5)
            self._break_continuity()
            return self._hold("face_jump")

        left_open = sample.left_blink <= self.settings.open_threshold
        right_open = sample.right_blink <= self.settings.open_threshold
        eyes_open = left_open and right_open

        if self._neutral is None:
            return self._calibrate(now, sample, eyes_open)
        if self._wink is not None:
            return self._continue_wink(self._wink, now, sample, eyes_open)

        if not eyes_open:
            self._open_since = None
            if self._armed and left_open != right_open:
                side: Click = "right" if left_open else "left"
                wink_score = sample.right_blink if left_open else sample.left_blink
                if wink_score < self.settings.closed_threshold:
                    return self._hold("wink")
                if self._last_click is None or now >= self._last_click + self.settings.click_cooldown_seconds:
                    self._wink = side
                    self._wink_start = now
                    return self._hold("wink")
            self._armed = False
            return self._hold("rearming")

        if not self._armed:
            if self._open_since is None:
                self._open_since = now
            if now < self._open_since + self.settings.rearm_seconds:
                return self._hold("rearming")
            self._armed = True
        self._position = self._move(sample, elapsed)
        return TrackingOutput(self._position, None, "tracking", 1.0)

    def _hold(self, state: TrackingState, click: Click | None = None) -> TrackingOutput:
        progress = 1.0 if self._neutral is not None else 0.0
        return TrackingOutput(None, click, state, progress)

    def _calibrate(self, now: float, sample: FaceSample, eyes_open: bool) -> TrackingOutput:
        if not eyes_open:
            self._break_continuity()
            return self._hold("calibrating")
        if self._calibration_start is None:
            self._calibration_start = now

        self._calibration_count += 1
        self._calibration_x += sample.nose_x
        self._calibration_y += sample.nose_y
        duration = self.settings.calibration_seconds
        if now < self._calibration_start + duration:
            progress = (now - self._calibration_start) / duration
            return TrackingOutput(None, None, "calibrating", progress)

        self._neutral = (
            self._calibration_x / self._calibration_count,
            self._calibration_y / self._calibration_count,
        )
        self._armed = True
        return TrackingOutput(self._position, None, "tracking", 1.0)

    def _continue_wink(
        self, side: Click, now: float, sample: FaceSample, eyes_open: bool
    ) -> TrackingOutput:
        settings = self.settings
        if side == "left":
            wink_score, other_score = sample.left_blink, sample.right_blink
        else:
            wink_score, other_score = sample.right_blink, sample.left_blink

        if now > self._wink_start + settings.wink_max_seconds or other_score > settings.open_threshold:
            self._break_continuity()
            if eyes_open:
                self._open_since = now
            return self._hold("rearming")
        if eyes_open:
            click = None
            if self._wink_seen_again and now >= self._wink_start + settings.wink_min_seconds:
                click = side
                self._last_click = now
            self._break_continuity()
            self._open_since = now
            return self._hold("rearming", click)

        if wink_score >= settings.closed_threshold and now > self._wink_start:
            self._wink_seen_again = True
        return self._hold("wink")

    def _move(self, sample: FaceSample, elapsed: float) -> tuple[float, float]:
        settings = self.settings
        assert self._neutral is not None
        neutral_x, neutral_y = self._neutral
        dx = sample.nose_x - neutral_x
        dy = sample.nose_y - neutral_y
        target_x = self._map_axis(-dx if settings.mirror else dx, settings.range_x)
        target_y = self._map_axis(dy, settings.range_y)

        if settings.smoothing_seconds == 0:
            return target_x, target_y
        weight = -expm1(-elapsed / settings.smoothing_seconds)
        current_x, current_y = self._position
        return (
            current_x + weight * (target_x - current_x),
            current_y + weight * (target_y - current_y),
        )

    def _map_axis(self, offset: float, limit: float) -> float:
        dead_zone = self.settings.dead_zone
        if abs(offset) <= dead_zone:
            return 0.5
        fraction = min(1.0, (abs(offset) - dead_zone) / (limit - dead_zone))
        return 0.5 + (0.5 if offset > 0 else -0.5) * fraction
