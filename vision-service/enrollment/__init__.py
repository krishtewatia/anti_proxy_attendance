"""Biometric face enrollment package with quality gating and template extraction."""

from enrollment.quality_gates import QualityGateResult, check_image_quality
from enrollment.engine import EnrollmentBatchResult, process_multi_image_enrollment

__all__ = [
    "QualityGateResult",
    "check_image_quality",
    "EnrollmentBatchResult",
    "process_multi_image_enrollment",
]
