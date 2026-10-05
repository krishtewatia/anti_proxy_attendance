"""Unit tests for Face Quality Gates and Multi-Image Enrollment Engine (Step 2E.2).

Verifies:
1. Rejection: NO_FACE_DETECTED (0 faces).
2. Rejection: MULTIPLE_FACES_DETECTED (> 1 faces).
3. Rejection: FACE_TOO_SMALL (< min_face_size).
4. Rejection: DETECTION_SCORE_TOO_LOW (< min_det_score).
5. Rejection: IMAGE_TOO_BLURRY (< min_sharpness).
6. Success: Sharp face passing all gates returns normalized 512-d embedding.
7. Batch rejection: INSUFFICIENT_IMAGES (< 3 images).
8. Batch rejection: TOO_MANY_IMAGES (> 5 images).
9. Quality-weighted mean calculation: higher sharpness/detection scores receive higher weights.
10. Cross-student duplicate detection flags duplicates above similarity threshold.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

import numpy as np

# Ensure vision-service is on sys.path
SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from enrollment.quality_gates import check_image_quality, compute_laplacian_sharpness
from enrollment.engine import process_multi_image_enrollment, check_gallery_duplicate


class DummyFace:
    """Helper mock object mimicking InsightFace Face class."""

    def __init__(
        self,
        bbox: tuple[float, float, float, float] = (100.0, 100.0, 220.0, 220.0),
        det_score: float = 0.95,
        embedding: np.ndarray | None = None,
    ):
        self.bbox = np.array(bbox, dtype=np.float32)
        self.det_score = det_score
        if embedding is None:
            emb = np.random.randn(512).astype(np.float32)
            self.embedding = emb / np.linalg.norm(emb)
        else:
            self.embedding = embedding


def create_synthetic_image(h: int = 400, w: int = 400, add_noise: bool = True) -> np.ndarray:
    """Create a synthetic 3-channel image with optional high-frequency gradient noise for sharpness."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    if add_noise:
        # Create checkerboard / sharp texture to guarantee high Laplacian variance
        img[::4, ::4] = 255
        img[1::4, 1::4] = 200
        img[2::4, 2::4] = 150
    return img


class TestBiometricQualityGates(unittest.TestCase):
    """Test individual per-image quality gates and rejection reasons."""

    def setUp(self):
        self.mock_app = MagicMock()

    def test_rejection_no_face_detected(self):
        """Image with 0 detected faces must be rejected with NO_FACE_DETECTED."""
        self.mock_app.get.return_value = []
        img = create_synthetic_image(300, 300)

        result = check_image_quality(img, self.mock_app)
        self.assertFalse(result.passed)
        self.assertEqual(result.face_count, 0)
        self.assertTrue(any("NO_FACE_DETECTED" in r for r in result.rejection_reasons))

    def test_rejection_multiple_faces_detected(self):
        """Image with multiple faces must be rejected with MULTIPLE_FACES_DETECTED."""
        f1 = DummyFace(bbox=(50, 50, 150, 150))
        f2 = DummyFace(bbox=(200, 200, 300, 300))
        self.mock_app.get.return_value = [f1, f2]
        img = create_synthetic_image(400, 400)

        result = check_image_quality(img, self.mock_app)
        self.assertFalse(result.passed)
        self.assertEqual(result.face_count, 2)
        self.assertTrue(any("MULTIPLE_FACES_DETECTED" in r for r in result.rejection_reasons))

    def test_rejection_face_too_small(self):
        """Face smaller than min_face_size (e.g. 50x50 < 80x80) must be rejected with FACE_TOO_SMALL."""
        small_face = DummyFace(bbox=(100.0, 100.0, 150.0, 150.0))  # 50x50 px
        self.mock_app.get.return_value = [small_face]
        img = create_synthetic_image(400, 400)

        result = check_image_quality(img, self.mock_app, min_face_size=80)
        self.assertFalse(result.passed)
        self.assertTrue(any("FACE_TOO_SMALL" in r for r in result.rejection_reasons))
        self.assertEqual(result.face_size, (50, 50))

    def test_rejection_detection_score_too_low(self):
        """Face detection score 0.45 (< 0.60) must be rejected with DETECTION_SCORE_TOO_LOW."""
        low_score_face = DummyFace(bbox=(100.0, 100.0, 250.0, 250.0), det_score=0.45)
        self.mock_app.get.return_value = [low_score_face]
        img = create_synthetic_image(400, 400)

        result = check_image_quality(img, self.mock_app, min_det_score=0.60)
        self.assertFalse(result.passed)
        self.assertTrue(any("DETECTION_SCORE_TOO_LOW" in r for r in result.rejection_reasons))
        self.assertAlmostEqual(result.det_score, 0.45)

    def test_rejection_image_too_blurry(self):
        """Completely flat/blurry face crop (sharpness 0.0 < 50.0) must be rejected with IMAGE_TOO_BLURRY."""
        face = DummyFace(bbox=(50.0, 50.0, 200.0, 200.0), det_score=0.95)
        self.mock_app.get.return_value = [face]
        flat_img = create_synthetic_image(400, 400, add_noise=False)  # Completely uniform zero matrix

        result = check_image_quality(flat_img, self.mock_app, min_sharpness=50.0)
        self.assertFalse(result.passed)
        self.assertTrue(any("IMAGE_TOO_BLURRY" in r for r in result.rejection_reasons))
        self.assertLess(result.sharpness, 50.0)

    def test_passing_image_returns_valid_embedding(self):
        """Image meeting all size, score, face-count, and sharpness criteria passes cleanly."""
        emb = np.random.randn(512).astype(np.float32)
        emb /= np.linalg.norm(emb)
        face = DummyFace(bbox=(50.0, 50.0, 250.0, 250.0), det_score=0.98, embedding=emb)
        self.mock_app.get.return_value = [face]
        sharp_img = create_synthetic_image(400, 400, add_noise=True)

        result = check_image_quality(sharp_img, self.mock_app, min_face_size=80, min_det_score=0.60, min_sharpness=10.0)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.rejection_reasons), 0)
        self.assertEqual(result.face_count, 1)
        self.assertIsNotNone(result.embedding)
        self.assertAlmostEqual(float(np.linalg.norm(result.embedding)), 1.0, places=5)


class TestMultiImageEnrollmentEngine(unittest.TestCase):
    """Test multi-image enrollment engine, weighted fusion, and cross-student duplicate checking."""

    def setUp(self):
        self.mock_app = MagicMock()

    def test_batch_insufficient_images_rejected(self):
        """Batch with fewer than 3 images is rejected immediately."""
        images = [create_synthetic_image(), create_synthetic_image()]  # 2 images
        res = process_multi_image_enrollment(images, identity="person_short", app=self.mock_app, min_images=3)

        self.assertFalse(res.passed)
        self.assertTrue(any("INSUFFICIENT_IMAGES" in r for r in res.rejection_reasons))

    def test_batch_too_many_images_rejected(self):
        """Batch with more than 5 images is rejected immediately."""
        images = [create_synthetic_image() for _ in range(6)]  # 6 images
        res = process_multi_image_enrollment(images, identity="person_excess", app=self.mock_app, max_images=5)

        self.assertFalse(res.passed)
        self.assertTrue(any("TOO_MANY_IMAGES" in r for r in res.rejection_reasons))

    def test_quality_weighted_mean_fusion(self):
        """Verify that higher quality images receive higher weight in the mean embedding."""
        v1 = np.zeros(512, dtype=np.float32)
        v1[0] = 1.0  # Unit vector along axis 0
        v2 = np.zeros(512, dtype=np.float32)
        v2[1] = 1.0  # Unit vector along axis 1
        v3 = np.zeros(512, dtype=np.float32)
        v3[2] = 1.0  # Unit vector along axis 2

        # Mock app returning v1 (low score), v2 (medium score), v3 (very high score)
        f1 = DummyFace(bbox=(50, 50, 200, 200), det_score=0.65, embedding=v1)
        f2 = DummyFace(bbox=(50, 50, 200, 200), det_score=0.75, embedding=v2)
        f3 = DummyFace(bbox=(50, 50, 200, 200), det_score=0.99, embedding=v3)

        self.mock_app.get.side_effect = [[f1], [f2], [f3]]

        imgs = [create_synthetic_image() for _ in range(3)]
        res = process_multi_image_enrollment(
            imgs,
            identity="person_weighted",
            app=self.mock_app,
            min_images=3,
            max_images=5,
            min_sharpness=1.0,
        )

        self.assertTrue(res.passed)
        self.assertEqual(res.sample_count, 3)
        self.assertIsNotNone(res.mean_embedding)

        # Because f3 had det_score=0.99 (highest), mean_embedding[2] must be greater than [0] and [1]
        self.assertGreater(res.mean_embedding[2], res.mean_embedding[0])
        self.assertGreater(res.mean_embedding[2], res.mean_embedding[1])
        # Must be normalized
        self.assertAlmostEqual(float(np.linalg.norm(res.mean_embedding)), 1.0, places=5)

    def test_cross_student_duplicate_detection(self):
        """Candidate embedding with similarity >= 0.70 to an existing student is rejected."""
        v_target = np.random.randn(512).astype(np.float32)
        v_target /= np.linalg.norm(v_target)

        # Existing gallery with person_alice having v_target
        gallery = {"person_alice": v_target}

        # Candidate person_bob has nearly identical embedding (similarity > 0.99)
        v_bob = v_target + np.random.randn(512).astype(np.float32) * 0.01
        v_bob /= np.linalg.norm(v_bob)

        f1 = DummyFace(bbox=(50, 50, 200, 200), det_score=0.95, embedding=v_bob)
        f2 = DummyFace(bbox=(50, 50, 200, 200), det_score=0.95, embedding=v_bob)
        f3 = DummyFace(bbox=(50, 50, 200, 200), det_score=0.95, embedding=v_bob)
        self.mock_app.get.side_effect = [[f1], [f2], [f3]]

        imgs = [create_synthetic_image() for _ in range(3)]
        res = process_multi_image_enrollment(
            imgs,
            identity="person_bob",
            app=self.mock_app,
            existing_gallery=gallery,
            duplicate_threshold=0.70,
            min_sharpness=1.0,
        )

        self.assertFalse(res.passed)
        self.assertTrue(any("DUPLICATE_IDENTITY_DETECTED" in r for r in res.rejection_reasons))
        self.assertTrue(any("person_alice" in r for r in res.rejection_reasons))


if __name__ == "__main__":
    unittest.main()
