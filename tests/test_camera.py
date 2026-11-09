from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from camera import AMBIGUOUS_FACE, Camera, create_landmarker, extract_sample
from tracking import FaceSample


NOSE = [None, SimpleNamespace(x=0.4, y=0.6)]
BLINKS = [
    SimpleNamespace(category_name="eyeBlinkRight", score=0.1),
    SimpleNamespace(category_name="eyeBlinkLeft", score=0.9),
]
FACE = FaceSample(0.4, 0.6, 0.9, 0.1)
DIRECTSHOW = 700
MEDIA_FOUNDATION = 1400


class FakeCaptureError(Exception):
    pass


def result(landmarks, blendshapes):
    return SimpleNamespace(face_landmarks=landmarks, face_blendshapes=blendshapes)


class CameraTests(unittest.TestCase):
    def fake_capture(self, opened=True):
        capture = Mock()
        capture.isOpened.return_value = opened
        capture.read.return_value = (False, None)
        return capture

    def give_one_frame(self, camera, capture):
        def read():
            if capture.read.call_count == 1:
                return True, object()
            camera.stop()
            return False, None

        capture.read.side_effect = read

    def run_camera(self, camera, primary, alternate, *, has_face=True, inference_error=None):
        def open_capture(index, backend):
            self.assertEqual(index, camera.index)
            if backend == DIRECTSHOW:
                return primary
            self.assertEqual(backend, MEDIA_FOUNDATION)
            primary.release.assert_called_once_with()
            return alternate

        cv2 = SimpleNamespace(
            VideoCapture=Mock(side_effect=open_capture), CAP_DSHOW=DIRECTSHOW, CAP_MSMF=MEDIA_FOUNDATION,
            CAP_PROP_FRAME_WIDTH=3, CAP_PROP_FRAME_HEIGHT=4, COLOR_BGR2RGB=5, cvtColor=Mock(),
            error=FakeCaptureError,
        )
        mediapipe = SimpleNamespace(Image=Mock(), ImageFormat=SimpleNamespace(SRGB=1))
        landmarker = Mock()
        landmarker.detect_for_video.return_value = result([NOSE], [BLINKS]) if has_face else result([], [])
        landmarker.detect_for_video.side_effect = inference_error
        camera.stop_event.wait = Mock()
        with (
            patch.dict("sys.modules", {"cv2": cv2, "mediapipe": mediapipe}),
            patch("camera.create_landmarker", return_value=nullcontext(landmarker)),
        ):
            camera.run()
        return cv2.VideoCapture, landmarker

    def test_no_initial_directshow_frames_fall_back_to_the_same_camera_index(self):
        camera = Camera(3)
        primary, alternate = self.fake_capture(), self.fake_capture()
        self.give_one_frame(camera, alternate)
        open_capture, landmarker = self.run_camera(camera, primary, alternate)
        self.assertEqual(open_capture.call_args_list, [call(3, DIRECTSHOW), call(3, MEDIA_FOUNDATION)])
        self.assertEqual(primary.read.call_count, 20)
        self.assertEqual(alternate.read.call_count, 2)
        primary.release.assert_called_once_with()
        alternate.release.assert_called_once_with()
        landmarker.detect_for_video.assert_called_once()
        self.assertEqual(camera.latest[1], FACE)
        self.assertIsNone(camera.error)

    def test_initial_driver_read_exception_falls_back_to_the_same_camera_index(self):
        for error_type in (OSError, FakeCaptureError):
            with self.subTest(error_type=error_type):
                camera = Camera(2)
                primary, alternate = self.fake_capture(), self.fake_capture()
                primary.read.side_effect = error_type("first backend could not read")
                self.give_one_frame(camera, alternate)
                open_capture, landmarker = self.run_camera(camera, primary, alternate)
                self.assertEqual(open_capture.call_args_list, [call(2, DIRECTSHOW), call(2, MEDIA_FOUNDATION)])
                primary.release.assert_called_once_with()
                alternate.release.assert_called_once_with()
                landmarker.detect_for_video.assert_called_once()
                self.assertEqual(camera.latest[1], FACE)
                self.assertIsNone(camera.error)

    def test_failed_backends_keep_the_most_recent_nonempty_read_error(self):
        for alternate_detail in (None, "", "second backend read error"):
            with self.subTest(alternate_detail=alternate_detail):
                camera = Camera(0)
                primary = self.fake_capture()
                alternate = self.fake_capture(opened=alternate_detail is not None)
                primary.read.side_effect = OSError("first backend read error")
                if alternate_detail is not None:
                    alternate.read.side_effect = FakeCaptureError(alternate_detail)
                open_capture, _ = self.run_camera(camera, primary, alternate)
                self.assertEqual(open_capture.call_args_list, [call(0, DIRECTSHOW), call(0, MEDIA_FOUNDATION)])
                self.assertEqual(camera.error.key, "camera_error_detail")
                self.assertEqual(camera.error.detail, alternate_detail or "first backend read error")
                primary.release.assert_called_once_with()
                alternate.release.assert_called_once_with()

    def test_stop_during_initial_driver_read_exception_does_not_try_another_backend(self):
        camera = Camera(0)
        primary, alternate = self.fake_capture(), self.fake_capture()

        def stop_during_read():
            camera.stop()
            raise OSError("read interrupted")

        primary.read.side_effect = stop_during_read
        open_capture, _ = self.run_camera(camera, primary, alternate)
        open_capture.assert_called_once_with(0, DIRECTSHOW)
        primary.release.assert_called_once_with()
        self.assertIsNone(camera.error)

    def test_driver_read_exception_after_first_frame_does_not_switch_backends(self):
        camera = Camera(0)
        primary, alternate = self.fake_capture(), self.fake_capture()
        primary.read.side_effect = [(True, object()), FakeCaptureError("camera disconnected")]
        open_capture, landmarker = self.run_camera(camera, primary, alternate)
        open_capture.assert_called_once_with(0, DIRECTSHOW)
        primary.release.assert_called_once_with()
        landmarker.detect_for_video.assert_called_once()
        self.assertEqual(camera.error.detail, "camera disconnected")

    def test_inference_exception_never_switches_backends(self):
        camera = Camera(0)
        primary, alternate = self.fake_capture(), self.fake_capture()
        primary.read.return_value = (True, object())
        open_capture, _ = self.run_camera(camera, primary, alternate, inference_error=FakeCaptureError("model failed"))
        open_capture.assert_called_once_with(0, DIRECTSHOW)
        primary.release.assert_called_once_with()
        self.assertEqual(camera.error.detail, "model failed")

    def test_both_failed_backends_report_whether_any_camera_opened(self):
        for primary_opened, alternate_opened, error in (
            (False, False, "camera_unavailable"),
            (True, False, "camera_no_frames"),
            (False, True, "camera_no_frames"),
            (True, True, "camera_no_frames"),
        ):
            with self.subTest(primary_opened=primary_opened, alternate_opened=alternate_opened):
                camera = Camera(2)
                primary = self.fake_capture(primary_opened)
                alternate = self.fake_capture(alternate_opened)
                open_capture, landmarker = self.run_camera(camera, primary, alternate)
                self.assertEqual(open_capture.call_args_list, [call(2, DIRECTSHOW), call(2, MEDIA_FOUNDATION)])
                self.assertEqual(primary.read.call_count, 20 if primary_opened else 0)
                self.assertEqual(alternate.read.call_count, 20 if alternate_opened else 0)
                primary.release.assert_called_once_with()
                alternate.release.assert_called_once_with()
                landmarker.detect_for_video.assert_not_called()
                self.assertEqual(camera.error.key, error)

    def test_stop_during_backend_switch_releases_primary_and_skips_alternate(self):
        camera = Camera(1)
        primary, alternate = self.fake_capture(), self.fake_capture()
        primary.release.side_effect = camera.stop
        open_capture, _ = self.run_camera(camera, primary, alternate)
        open_capture.assert_called_once_with(1, DIRECTSHOW)
        primary.release.assert_called_once_with()
        alternate.release.assert_not_called()
        self.assertIsNone(camera.error)

    def test_losing_frames_after_success_never_switches_backends(self):
        camera = Camera(0)
        primary, alternate = self.fake_capture(), self.fake_capture()
        primary.read.side_effect = [(True, object())] + [(False, None)] * 20
        open_capture, landmarker = self.run_camera(camera, primary, alternate, has_face=False)
        open_capture.assert_called_once_with(0, DIRECTSHOW)
        self.assertEqual(primary.read.call_count, 21)
        primary.release.assert_called_once_with()
        alternate.release.assert_not_called()
        landmarker.detect_for_video.assert_called_once()
        self.assertEqual(camera.error.key, "camera_no_frames")

    def test_landmarker_requests_two_faces(self):
        mediapipe = Mock()
        with patch("camera.model_is_ready", return_value=True):
            create_landmarker(mediapipe)
        options = mediapipe.tasks.vision.FaceLandmarkerOptions
        self.assertEqual(options.call_args.kwargs["num_faces"], 2)
        self.assertTrue(options.call_args.kwargs["output_face_blendshapes"])

    def test_zero_faces_or_incomplete_scores_have_no_sample(self):
        for observation in (result([], []), result([NOSE], []), result([NOSE], [BLINKS[:1]])):
            with self.subTest(observation=observation):
                self.assertIsNone(extract_sample(observation))

    def test_single_face_provides_anatomical_eye_scores(self):
        self.assertEqual(extract_sample(result([NOSE], [BLINKS])), FACE)

    def test_two_faces_are_ambiguous_even_if_one_signal_is_incomplete(self):
        for observation in (
            result([NOSE, NOSE], [BLINKS, BLINKS]),
            result([NOSE, NOSE], []),
            result([NOSE], [BLINKS, BLINKS]),
        ):
            with self.subTest(observation=observation):
                self.assertIs(extract_sample(observation), AMBIGUOUS_FACE)

    def test_face_loss_reaches_ui_before_a_newer_face_sample(self):
        camera = Camera(0)
        camera.publish(0.1, FACE)
        camera.publish(0.2, None)
        camera.publish(0.3, FACE)
        self.assertEqual(camera.snapshot(), ((0.2, None), None))
        self.assertEqual(camera.snapshot(), ((0.3, FACE), None))

    def test_ambiguity_takes_priority_over_loss_and_a_newer_face_sample(self):
        camera = Camera(0)
        camera.publish(0.1, None)
        camera.publish(0.2, AMBIGUOUS_FACE)
        camera.publish(0.3, None)
        camera.publish(0.4, FACE)
        self.assertEqual(camera.snapshot(), ((0.2, AMBIGUOUS_FACE), None))
        self.assertEqual(camera.snapshot(), ((0.4, FACE), None))


if __name__ == "__main__":
    unittest.main()
