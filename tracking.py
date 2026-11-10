"""Map normalized face samples to pointer positions and optional clicks."""

from collections.abc import Callable
from dataclasses import dataclass
from math import dist, expm1, hypot, isfinite
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
    dwell_seconds: float | None = None
    dwell_radius: float = 0.02
    motion_only: bool = False

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
        if self.dwell_seconds is not None and (
            not isfinite(self.dwell_seconds) or self.dwell_seconds <= 0
        ):
            raise ValueError("Dwell duration must be finite and positive.")
        if self.motion_only and self.dwell_seconds is not None:
            raise ValueError("Motion-only mode cannot use dwell clicks.")
        if not 0 < self.dwell_radius <= 0.25:
            raise ValueError("Dwell radius must be greater than zero and at most 0.25.")

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

    @property
    def is_valid(self) -> bool:
        return all(0 <= value <= 1 for value in (
            self.nose_x, self.nose_y, self.left_blink, self.right_blink
        ))


@dataclass(frozen=True)
class TrackingOutput:
    """A missing position means hold the cursor. A click is a one-update event."""

    position: tuple[float, float] | None
    click: Click | None
    state: TrackingState
    calibration_progress: float
    dwell_progress: float = 0.0

    @property
    def calibrated(self) -> bool:
        return self.calibration_progress == 1.0


class Tracker:
    """Calibrate a neutral point, smooth motion, and detect clicks."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings if settings is not None else Settings()
        self.reset()

    @property
    def calibrated(self) -> bool:
        return self._neutral is not None

    def reset(self) -> None:
        """Forget calibration and all tracking and gesture history."""
        self._neutral: tuple[float, float] | None = None
        self._origin = (0.5, 0.5)
        self._position = self._origin
        self._last_update: float | None = None
        self._last_nose: tuple[float, float] | None = None
        self._last_click: float | None = None
        self._break_continuity()

    def reset_dwell(self) -> None:
        """Require fresh motion before another dwell, keeping the current calibration."""
        self._dwell_origin: tuple[float, float] | None = None
        self._dwell_armed = False
        self._dwell_candidate: tuple[tuple[float, float], float] | None = None

    def interrupts_pending_click(self, sample: FaceSample) -> bool:
        """Whether this eye observation interrupts an in-progress click gesture."""
        if self._wink is not None:
            return not self._other_eye_open(self._wink, sample)
        return self._dwell_candidate is not None and not self._dwell_eyes_open(sample)

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
        self._wink_reopening_at: float | None = None
        self._wink_reopening_confirmed = False
        self.reset_dwell()

    def update(
        self, now: float, sample: FaceSample | None,
        *, calibration_position: tuple[float, float] | None = None,
        dwell_projection: Callable[[float, float], tuple[float, float]] | None = None,
    ) -> TrackingOutput:
        """Process a monotonic observation, optionally anchoring completed calibration."""
        if not isfinite(now) or (self._last_update is not None and now < self._last_update):
            raise ValueError("Tracking time must be finite and non-decreasing.")
        if calibration_position is not None and (
            not isinstance(calibration_position, tuple)
            or len(calibration_position) != 2
            or not all(
                isinstance(coordinate, (int, float)) and 0 <= coordinate <= 1
                for coordinate in calibration_position
            )
        ):
            raise ValueError("Calibration position must contain two normalized coordinates.")

        elapsed = now - self._last_update if self._last_update is not None else 0.0
        if elapsed > self.settings.max_sample_gap_seconds:
            self._break_continuity()
            if not self.calibrated:
                self._last_nose = None
            elapsed = 0.0
        self._last_update = now

        if sample is None or not sample.is_valid:
            self._break_continuity()
            # A calibrated tracker still needs to check where a face returns.
            if not self.calibrated:
                self._last_nose = None
            return self._hold("paused")

        previous_nose = self._last_nose
        self._last_nose = (sample.nose_x, sample.nose_y)
        if previous_nose is not None and hypot(
            sample.nose_x - previous_nose[0], sample.nose_y - previous_nose[1]
        ) > self.settings.max_nose_jump:
            self._neutral = None
            self._origin = (0.5, 0.5)
            self._position = self._origin
            self._break_continuity()
            return self._hold("face_jump")

        left_open = sample.left_blink <= self.settings.open_threshold
        right_open = sample.right_blink <= self.settings.open_threshold
        eyes_open = self.settings.motion_only or (left_open and right_open)
        dwell_seconds = self.settings.dwell_seconds
        if dwell_seconds is not None:
            # Dwell needs no wink gesture. Only a clear closure interrupts it.
            eyes_open = self._dwell_eyes_open(sample)

        if not self.calibrated:
            return self._calibrate(now, sample, eyes_open, calibration_position)
        if self._wink is not None:
            return self._continue_wink(self._wink, now, sample, eyes_open)

        if not eyes_open:
            self._open_since = None
            if dwell_seconds is not None:
                self._dwell_candidate = None
            elif self._armed and left_open != right_open:
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

        target = self._target(sample)
        self._position = self._move(target, elapsed)
        if dwell_seconds is None:
            return TrackingOutput(self._position, None, "tracking", 1.0)
        position = self._position
        if dwell_projection is not None:
            target = dwell_projection(*target)
            position = dwell_projection(*position)
        click, progress = self._advance_dwell(now, target, position, dwell_seconds)
        return TrackingOutput(self._position, click, "tracking", 1.0, progress)

    def _hold(self, state: TrackingState, click: Click | None = None) -> TrackingOutput:
        progress = 1.0 if self.calibrated else 0.0
        return TrackingOutput(None, click, state, progress)

    def _calibrate(
        self, now: float, sample: FaceSample, eyes_open: bool,
        calibration_position: tuple[float, float] | None,
    ) -> TrackingOutput:
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

        neutral_x = self._calibration_x / self._calibration_count
        neutral_y = self._calibration_y / self._calibration_count
        if calibration_position is not None:
            # Keep the pointer at its anchor if the user's final pose drifted.
            if abs(sample.nose_x - neutral_x) > self.settings.dead_zone:
                neutral_x = sample.nose_x
            if abs(sample.nose_y - neutral_y) > self.settings.dead_zone:
                neutral_y = sample.nose_y
            self._origin = calibration_position
            self._position = calibration_position
        self._neutral = (neutral_x, neutral_y)
        if self.settings.dwell_seconds is not None:
            # Smoothing or a late calibration shift must not look like new intent.
            self._dwell_origin = self._target(sample)
        self._armed = True
        return TrackingOutput(self._position, None, "tracking", 1.0)

    def _dwell_eyes_open(self, sample: FaceSample) -> bool:
        return max(sample.left_blink, sample.right_blink) < self.settings.closed_threshold

    def _other_eye_open(self, side: Click, sample: FaceSample) -> bool:
        other_score = sample.right_blink if side == "left" else sample.left_blink
        return other_score <= self.settings.open_threshold

    def _continue_wink(
        self, side: Click, now: float, sample: FaceSample, eyes_open: bool
    ) -> TrackingOutput:
        settings = self.settings
        if now > self._wink_start + settings.wink_max_seconds or not self._other_eye_open(side, sample):
            self._break_continuity()
            if eyes_open:
                self._open_since = now
            return self._hold("rearming")
        if eyes_open:
            click = None
            # An uncertain reopening must not make a brief closure count as a wink.
            closure_end = now if self._wink_reopening_at is None else self._wink_reopening_at
            if self._wink_seen_again and closure_end >= self._wink_start + settings.wink_min_seconds:
                click = side
                self._last_click = now
            self._break_continuity()
            self._open_since = now
            return self._hold("rearming", click)

        # Allow one intermediate observation to be score jitter. Once partial
        # reopening is confirmed, a new closure cannot extend the old one.
        if self._wink_reopening_confirmed:
            return self._hold("wink")
        wink_score = sample.left_blink if side == "left" else sample.right_blink
        if wink_score >= settings.closed_threshold:
            if now > self._wink_start:
                self._wink_seen_again = True
            self._wink_reopening_at = None
        elif self._wink_reopening_at is None:
            self._wink_reopening_at = now
        elif now > self._wink_reopening_at:
            self._wink_reopening_confirmed = True
        return self._hold("wink")

    def _advance_dwell(
        self, now: float, target: tuple[float, float], position: tuple[float, float], duration: float
    ) -> tuple[Click | None, float]:
        radius = self.settings.dwell_radius
        if self._dwell_origin is None:
            self._dwell_origin = target
            return None, 0.0
        if not self._dwell_armed:
            rearm_distance = 2 * radius
            if (dist(target, self._dwell_origin) < rearm_distance
                    or dist(position, self._dwell_origin) < rearm_distance):
                return None, 0.0
            self._dwell_armed = True

        settled = dist(position, target) <= radius
        if settled and self._dwell_candidate is not None:
            anchor, started_at = self._dwell_candidate
            # Compare with the fixed anchor to catch cumulative drift.
            if dist(target, anchor) <= radius and dist(position, anchor) <= radius:
                if now < started_at + duration:
                    return None, (now - started_at) / duration
                self._dwell_origin = position
                self._dwell_armed = False
                self._dwell_candidate = None
                return "left", 1.0

        self._dwell_candidate = (target, now) if settled else None
        return None, 0.0

    def _target(self, sample: FaceSample) -> tuple[float, float]:
        settings = self.settings
        assert self._neutral is not None
        neutral_x, neutral_y = self._neutral
        dx = sample.nose_x - neutral_x
        dy = sample.nose_y - neutral_y
        return (
            self._map_axis(-dx if settings.mirror else dx, settings.range_x, self._origin[0]),
            self._map_axis(dy, settings.range_y, self._origin[1]),
        )

    def _move(self, target: tuple[float, float], elapsed: float) -> tuple[float, float]:
        smoothing = self.settings.smoothing_seconds
        if smoothing == 0:
            return target
        weight = -expm1(-elapsed / smoothing)
        current_x, current_y = self._position
        target_x, target_y = target
        return (
            current_x + weight * (target_x - current_x),
            current_y + weight * (target_y - current_y),
        )

    def _map_axis(self, offset: float, limit: float, origin: float) -> float:
        dead_zone = self.settings.dead_zone
        if abs(offset) <= dead_zone:
            return origin
        fraction = min(1.0, (abs(offset) - dead_zone) / (limit - dead_zone))
        # Each side of the neutral position still reaches its own desktop edge.
        return origin + (1.0 - origin if offset > 0 else -origin) * fraction
