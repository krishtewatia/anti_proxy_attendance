"""Unit and integration test for dynamic gallery loading and hot reload (Step 2E.2).

Verifies:
1. Initial pipeline with gallery ['person_01'] classifies unknown student as UNKNOWN.
2. New student 'person_05' is enrolled and gallery is dynamically reloaded via reload_gallery().
3. Query face for 'person_05' is recognized immediately without restarting the pipeline.
4. load_gallery_from_backend parses active biometric templates from the backend API.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

# Ensure vision-service is on sys.path
SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from pipeline.live_cv_pipeline import (
    LiveCVPipeline,
    load_gallery_from_backend,
)


def make_unit_embedding(dim: int = 512, seed: int = 1) -> np.ndarray:
    """Generate a deterministic 512-d unit vector."""
    np.random.seed(seed)
    v = np.random.randn(dim).astype(np.float32)
    return v / np.linalg.norm(v)


class TestGalleryReload(unittest.TestCase):
    """Test dynamic gallery reloading and instant recognition of newly enrolled students."""

    def test_pipeline_gallery_hot_reload_recognizes_new_student(self):
        """Pipeline must recognize a newly enrolled student after reload_gallery() without pipeline restart."""
        # 1. Baseline gallery with only person_01
        emb_person_01 = make_unit_embedding(seed=101)
        emb_person_05 = make_unit_embedding(seed=505)

        initial_gallery = {"person_01": emb_person_01}

        mock_app = MagicMock()
        mock_app.models = {}

        pipeline = LiveCVPipeline(
            app=mock_app,
            gallery=initial_gallery,
            similarity_threshold=0.40,
            min_margin=0.10,
            min_supporting_frames=2,
            source_id="PHONE_CAM_01",
        )

        # 2. Before reload: person_05 is unknown
        matched_id, score, runner_up, margin = pipeline.match_identity(emb_person_05)
        self.assertEqual(matched_id, "UNKNOWN")
        self.assertLess(score, 0.40)

        # 3. Dynamic reload: person_05 is enrolled
        updated_gallery = {
            "person_01": emb_person_01,
            "person_05": emb_person_05,
        }
        total_identities = pipeline.reload_gallery(updated_gallery)
        self.assertEqual(total_identities, 2)
        self.assertIn("person_05", pipeline.gallery)

        # 4. After reload: person_05 is recognized immediately with high confidence
        matched_id_after, score_after, _, _ = pipeline.match_identity(emb_person_05)
        self.assertEqual(matched_id_after, "person_05")
        self.assertAlmostEqual(score_after, 1.0, places=4)

    def test_load_gallery_from_backend(self):
        """load_gallery_from_backend retrieves and formats active embeddings dictionary."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "count": 2,
            "gallery": {
                "person_01": make_unit_embedding(seed=1).tolist(),
                "person_02": make_unit_embedding(seed=2).tolist(),
            },
        }

        with patch("requests.get", return_value=mock_resp):
            gallery = load_gallery_from_backend(
                backend_url="http://127.0.0.1:8000",
                auth_token="test_token",
            )

            self.assertEqual(len(gallery), 2)
            self.assertIn("person_01", gallery)
            self.assertIn("person_02", gallery)
            self.assertIsInstance(gallery["person_01"], np.ndarray)
            self.assertAlmostEqual(float(np.linalg.norm(gallery["person_01"])), 1.0, places=4)


if __name__ == "__main__":
    unittest.main()
