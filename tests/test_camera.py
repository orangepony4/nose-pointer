from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from camera import AMBIGUOUS_FACE, Camera, create_landmarker, extract_sample
from tracking import FaceSample


NOSE = [None, SimpleNamespace(x=0.4, y=0.6)]
BLINKS = [
    SimpleNamespace(category_name="eyeBlinkRight", score=0.1),
    SimpleNamespace(category_name="eyeBlinkLeft", score=0.9),
]
FACE = FaceSample(0.4, 0.6, 0.9, 0.1)


def result(landmarks, blendshapes):
    return SimpleNamespace(face_landmarks=landmarks, face_blendshapes=blendshapes)


class CameraTests(unittest.TestCase):
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
