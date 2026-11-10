"""Local webcam inference. The UI only receives coordinates and blink scores."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Event, Lock, Thread
from time import monotonic
from urllib.request import urlopen

from i18n import translate
from tracking import FaceSample


MODEL_PATH = Path(__file__).resolve().parent / "models" / "face_landmarker.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
MODEL_SIZE = 3_758_596
NOSE_TIP = 1
AMBIGUOUS_FACE = object()


class CameraError(RuntimeError):
    def __init__(self, key):
        self.key = key
        super().__init__(translate("en", key))


@dataclass(frozen=True)
class CameraFailure:
    key: str
    detail: str = ""


def read_verified_model():
    if not MODEL_PATH.is_file():
        return None
    try:
        with MODEL_PATH.open("rb") as model_file:
            data = model_file.read(MODEL_SIZE + 1)
    except FileNotFoundError:
        return None
    if len(data) != MODEL_SIZE or sha256(data).hexdigest() != MODEL_SHA256:
        return None
    return data


def model_is_ready():
    return read_verified_model() is not None


def download_model():
    if model_is_ready():
        return
    with urlopen(MODEL_URL, timeout=30) as response:
        data = response.read(MODEL_SIZE + 1)
    if len(data) != MODEL_SIZE or sha256(data).hexdigest() != MODEL_SHA256:
        raise CameraError("model_verify_failed")

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with NamedTemporaryFile(dir=MODEL_PATH.parent, delete=False) as temp:
            temp_path = Path(temp.name)
            temp.write(data)
        temp_path.replace(MODEL_PATH)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def create_landmarker(mp):
    model_data = read_verified_model()
    if model_data is None:
        raise CameraError("model_missing")
    vision = mp.tasks.vision
    return vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        # MediaPipe's native Windows file loader cannot open every Unicode path.
        base_options=mp.tasks.BaseOptions(model_asset_buffer=model_data),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=2,
        output_face_blendshapes=True,
    ))


def extract_sample(result):
    if len(result.face_landmarks) > 1 or len(result.face_blendshapes) > 1:
        return AMBIGUOUS_FACE
    if not result.face_landmarks or not result.face_blendshapes:
        return None
    nose = result.face_landmarks[0][NOSE_TIP]
    scores = {item.category_name: item.score for item in result.face_blendshapes[0]}
    if "eyeBlinkLeft" not in scores or "eyeBlinkRight" not in scores:
        return None
    return FaceSample(nose.x, nose.y, scores["eyeBlinkLeft"], scores["eyeBlinkRight"])


def _infer_frame(cv2, mp, landmarker, frame, timestamp):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    return extract_sample(landmarker.detect_for_video(image, timestamp))


class Camera:
    def __init__(self, index):
        self.index = index
        self.stop_event = Event()
        self.lock = Lock()
        self.latest = None
        self.pending_pause = None
        self._unread_blink_peaks = (None, None)
        self.error = None
        self.thread = Thread(target=self.run, name="webcam", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def snapshot(self, *, interrupts_gesture=None, after_capture_at=None):
        """Read the latest frame or a fresh tracking or gesture interruption."""
        with self.lock:
            peaks, self._unread_blink_peaks = self._unread_blink_peaks, (None, None)
            if self.pending_pause is not None:
                pause, self.pending_pause = self.pending_pause, None
                return pause, self.error
            if interrupts_gesture is not None and self.latest is not None:
                _, sample = self.latest
                if isinstance(sample, FaceSample) and not interrupts_gesture(sample):
                    interruption = max(
                        (peak for peak in peaks if peak is not None
                         and (after_capture_at is None or peak[0] > after_capture_at)
                         and interrupts_gesture(peak[1])),
                        key=lambda observation: observation[0], default=None,
                    )
                    if interruption is not None:
                        return interruption, self.error
            return self.latest, self.error

    def publish(self, captured_at, sample):
        if isinstance(sample, FaceSample) and not sample.is_valid:
            sample = None
        with self.lock:
            self.latest = captured_at, sample
            # A fast next frame must not hide a pause from the UI. Ambiguity
            # disables input, so it takes precedence over a missing face.
            if sample is AMBIGUOUS_FACE or (sample is None and self.pending_pause is None):
                self.pending_pause = self.latest
            elif isinstance(sample, FaceSample):
                # Two samples are enough to keep the strongest evidence for each eye.
                left, right = self._unread_blink_peaks
                if left is None or sample.left_blink >= left[1].left_blink:
                    left = self.latest
                if right is None or sample.right_blink >= right[1].right_blink:
                    right = self.latest
                self._unread_blink_peaks = left, right

    def run(self):
        try:
            import cv2
            import mediapipe as mp

            with create_landmarker(mp) as landmarker:
                opened = False
                startup_failure = None
                for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
                    if self.stop_event.is_set():
                        return
                    capture = None
                    try:
                        try:
                            capture = cv2.VideoCapture(self.index, backend)
                            if self.stop_event.is_set():
                                return
                            if not capture.isOpened():
                                continue
                            opened = True
                            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                        except (OSError, cv2.error) as error:
                            failure = error
                        else:
                            failure = self._capture_frames(capture, cv2, mp, landmarker)
                    finally:
                        if capture is not None:
                            capture.release()
                    if failure is not None and (startup_failure is None or str(failure)):
                        startup_failure = failure
                if not self.stop_event.is_set():
                    if startup_failure is not None:
                        raise startup_failure
                    raise CameraError("camera_no_frames" if opened else "camera_unavailable")
        except Exception as error:
            detail = str(error)
            failure = (CameraFailure(error.key) if isinstance(error, CameraError)
                       else CameraFailure("camera_error_detail" if detail else "camera_error", detail))
            with self.lock:
                self.error = failure

    def _capture_frames(self, capture, cv2, mp, landmarker):
        last_timestamp = -1
        failures = 0
        while not self.stop_event.is_set():
            try:
                ok, frame = capture.read()
            except (OSError, cv2.error) as error:
                if self.stop_event.is_set():
                    return
                if last_timestamp != -1:
                    raise
                # The alternate backend may still deliver its first frame.
                return error
            captured_at = monotonic()
            if self.stop_event.is_set():
                return
            if not ok:
                self.publish(captured_at, None)
                failures += 1
                if failures >= 20:
                    # A backend switch is only for a camera that has yet to deliver a frame.
                    if last_timestamp != -1:
                        raise CameraError("camera_no_frames")
                    return
                self.stop_event.wait(0.05)
                continue
            failures = 0
            timestamp = max(last_timestamp + 1, int(captured_at * 1000))
            last_timestamp = timestamp
            sample = _infer_frame(cv2, mp, landmarker, frame, timestamp)
            if not self.stop_event.is_set():
                self.publish(captured_at, sample)


def check_inference():
    import cv2
    import mediapipe as mp
    import numpy as np

    with create_landmarker(mp) as landmarker:
        frame = np.zeros((160, 160, 3), dtype=np.uint8)
        try:
            sample = _infer_frame(cv2, mp, landmarker, frame, 0)
        except cv2.error as error:
            raise RuntimeError(f"OpenCV could not convert the test frame. {error}") from error
        if sample is not None:
            raise CameraError("model_blank_face")
