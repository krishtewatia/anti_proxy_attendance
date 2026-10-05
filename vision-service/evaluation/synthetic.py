"""Synthetic dataset generator for biometric face recognition accuracy evaluation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import numpy as np


def generate_synthetic_evaluation_data(
    num_enrolled: int = 10,
    probes_per_enrolled: int = 6,
    num_unknown_probes: int = 20,
    dim: int = 512,
    seed: int = 42,
) -> Tuple[
    Dict[str, np.ndarray],
    Dict[str, List[Tuple[np.ndarray, Optional[Dict[str, Any]]]]],
    List[Tuple[np.ndarray, Optional[Dict[str, Any]]]],
]:
    """
    Generate realistic synthetic ArcFace 512-d embeddings modeling empirical distributions.

    Empirical targets (InsightFace ResNet50/100 on 5-person test):
      - Genuine cosine similarity: mean ~0.74, std ~0.06, min ~0.60, max ~0.88
      - Impostor cosine similarity: mean ~0.05, std ~0.05, min ~-0.10, max ~0.18
      - Condition perturbations:
          * Normal: base genuine similarity ~0.76 - 0.85
          * Dim lighting: ~ -0.06
          * Yaw angle: ~ -0.08
          * Pitch angle: ~ -0.05
          * Distance far: ~ -0.07
          * Glasses: ~ -0.04
    """
    rng = np.random.default_rng(seed)

    # 1. Generate orthogonal/random base centroids for enrolled identities in 512-d space
    # High-dimensional random vectors on unit sphere have pairwise dot product ~ N(0, 1/sqrt(512)) ~ N(0, 0.044)
    gallery_centroids: Dict[str, np.ndarray] = {}
    for i in range(1, num_enrolled + 1):
        person_id = f"person_{i:02d}"
        v = rng.standard_normal(dim).astype(np.float32)
        v /= np.linalg.norm(v)
        gallery_centroids[person_id] = v

    # 2. Build enrolled gallery (unit normalized)
    enrolled_gallery = dict(gallery_centroids)

    # Condition list for probes
    conditions = [
        {"lighting": "normal", "pose": "frontal", "distance": "mid", "occlusion": "none"},
        {"lighting": "dim", "pose": "frontal", "distance": "mid", "occlusion": "none"},
        {"lighting": "backlit", "pose": "frontal", "distance": "mid", "occlusion": "none"},
        {"lighting": "normal", "pose": "yaw_left", "distance": "mid", "occlusion": "none"},
        {"lighting": "normal", "pose": "pitch_down", "distance": "mid", "occlusion": "none"},
        {"lighting": "normal", "pose": "frontal", "distance": "far", "occlusion": "none"},
        {"lighting": "normal", "pose": "frontal", "distance": "close", "occlusion": "glasses"},
    ]

    # 3. Generate probes for enrolled identities
    probe_embeddings: Dict[str, List[Tuple[np.ndarray, Optional[Dict[str, Any]]]]] = {}

    for person_id, centroid in gallery_centroids.items():
        probe_embeddings[person_id] = []
        for p_idx in range(probes_per_enrolled):
            cond = conditions[p_idx % len(conditions)].copy()

            # Target cosine similarity ~ 0.75 + perturbation
            target_sim = 0.76
            if cond["lighting"] == "dim":
                target_sim -= 0.05
            elif cond["lighting"] == "backlit":
                target_sim -= 0.06
            if "yaw" in cond["pose"]:
                target_sim -= 0.08
            elif "pitch" in cond["pose"]:
                target_sim -= 0.05
            if cond["distance"] == "far":
                target_sim -= 0.07
            if cond["occlusion"] == "glasses":
                target_sim -= 0.04

            # Add slight random noise
            target_sim += float(rng.normal(0.0, 0.02))
            target_sim = float(np.clip(target_sim, 0.52, 0.88))

            # Construct probe vector v_probe = target_sim * centroid + sqrt(1 - target_sim^2) * noise_perp
            noise = rng.standard_normal(dim).astype(np.float32)
            noise -= np.dot(noise, centroid) * centroid
            noise /= np.linalg.norm(noise)

            probe_v = target_sim * centroid + float(np.sqrt(1.0 - target_sim**2)) * noise
            probe_v /= np.linalg.norm(probe_v)

            probe_embeddings[person_id].append((probe_v, cond))

    # 4. Generate open-set unknown impostor probes
    unknown_probes: List[Tuple[np.ndarray, Optional[Dict[str, Any]]]] = []
    for u_idx in range(num_unknown_probes):
        cond = conditions[u_idx % len(conditions)].copy()
        # Random vector not matching any enrolled centroid
        u_vec = rng.standard_normal(dim).astype(np.float32)
        # Ensure it doesn't accidentally collide strongly with any centroid
        for centroid in gallery_centroids.values():
            dot = np.dot(u_vec, centroid)
            if abs(dot) > 0.30:
                u_vec -= dot * centroid
        u_vec /= np.linalg.norm(u_vec)
        unknown_probes.append((u_vec, cond))

    return enrolled_gallery, probe_embeddings, unknown_probes
