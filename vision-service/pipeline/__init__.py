"""Vision Pipeline Package."""

from pipeline.identity_boundary import (
    IdentityBoundary,
    side_of,
)
from pipeline.live_cv_pipeline import (
    DEFAULT_IDENTITY_MAP,
    FrameCVResult,
    FrameTrackInfo,
    FunnelCounters,
    LiveCVPipeline,
    TrackEvidence,
    classify_point_side,
    configure_scrfd_threads,
    cosine_similarity,
    create_face_analysis,
    load_gallery,
    load_gallery_from_npz,
    swap_scrfd_detector,
)

__all__ = [
    "LiveCVPipeline",
    "TrackEvidence",
    "FrameCVResult",
    "FrameTrackInfo",
    "load_gallery",
    "load_gallery_from_npz",
    "DEFAULT_IDENTITY_MAP",
    "FunnelCounters",
    "cosine_similarity",
    "create_face_analysis",
    "configure_scrfd_threads",
    "swap_scrfd_detector",
    "classify_point_side",
    "IdentityBoundary",
    "side_of",
]
