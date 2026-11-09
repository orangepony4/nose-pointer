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


def model_is_ready():
    return (MODEL_PATH.is_file() and MODEL_PATH.stat().st_size == MODEL_SIZE
            and sha256(MODEL_PATH.read_bytes()).hexdigest() == MODEL_SHA256)


def download_model():
    if model_is_ready():
        return
    with urlopen(MODEL_URL, timeout=30) as response:
        data = response.read(MODEL_SIZE + 1)
    if len(data) != MODEL_SIZE or sha256(data).hexdigest() != MODEL_SHA256:
        raise CameraError("model_verify_failed")

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=MODEL_PATH.parent, delete=False) as temp:
        temp_path = Path(temp.name)
        temp.write(data)
    try:
        temp_path.replace(MODEL_PATH)
    finally:
        temp_path.unlink(missing_ok=True)


def create_landmarker(mp):
    if not model_is_ready():
        raise CameraError("model_missing")
    vision = mp.tasks.vision
    return vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(MODEL_PATH)),
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


class Camera:
    def __init__(self, index):
        self.index = index
        self.stop_event = Event()
        self.lock = Lock()
        self.latest = None
        self.pending_pause = None
        self.error = None
        self.thread = Thread(target=self.run, name="webcam", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def snapshot(self):
        with self.lock:
            if self.pending_pause is not None:
                pause, self.pending_pause = self.pending_pause, None
                return pause, self.error
            return self.latest, self.error

    def publish(self, captured_at, sample):
        with self.lock:
            self.latest = captured_at, sample
            # A fast next frame must not hide a pause from the UI. Ambiguity
            # disables input, so it takes precedence over a missing face.
            if sample is AMBIGUOUS_FACE or (sample is None and self.pending_pause is None):
                self.pending_pause = self.latest

    def run(self):
        try:
            import cv2
            import mediapipe as mp

            with create_landmarker(mp) as landmarker:
                opened = False
                read_failure = None
                for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
                    if self.stop_event.is_set():
                        return
                    capture = cv2.VideoCapture(self.index, backend)
                    try:
                        if not self.stop_event.is_set() and capture.isOpened():
                            opened = True
                            failure = self._capture_frames(capture, cv2, mp, landmarker)
                            if failure is not None and (read_failure is None or str(failure)):
                                read_failure = failure
                    finally:
                        capture.release()
                if not self.stop_event.is_set():
                    if read_failure is not None:
                        raise read_failure
                    raise CameraError("camera_no_frames" if opened else "camera_unavailable")
        except Exception as error:
            detail = str(error)
            failure = (CameraFailure(error.key) if isinstance(error, CameraError)
                       else CameraFailure("camera_error_detail" if detail else "camera_error", detail))
            with self.lock:
                self.error = failure

    def _capture_frames(self, capture, cv2, mp, landmarker):
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
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
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            sample = extract_sample(landmarker.detect_for_video(image, timestamp))
            if not self.stop_event.is_set():
                self.publish(captured_at, sample)


def check_inference():
    import mediapipe as mp
    import numpy as np

    with create_landmarker(mp) as landmarker:
        pixels = np.zeros((160, 160, 3), dtype=np.uint8)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=pixels)
        if extract_sample(landmarker.detect_for_video(image, 0)) is not None:
            raise CameraError("model_blank_face")
