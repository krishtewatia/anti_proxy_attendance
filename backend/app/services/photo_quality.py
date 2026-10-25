"""Checks on a student's face photos before they go to an administrator.

The vision service is used exactly as it is: its ``/extract-embedding`` call
returns the biggest face it finds, with the detector's confidence
(``det_score``) and the face's box. From that and the image's own size this
module decides whether a photo is good enough:

* a face was found;
* the detector is confident enough (``det_score`` >= MIN_DET_SCORE);
* the face is large enough: its box's shorter side is at least
  MIN_FACE_FRACTION of the image's shorter side;
* the photos of one request show the same person: every pair has cosine
  similarity >= SAME_PERSON_MIN_SIMILARITY, the default recognition
  threshold of the standard classroom profile (ADR-007).

The vision service does not report how many faces a photo holds, so "exactly
one face" is left to the administrator's photo grid.

The image size is read from the PNG or JPEG header here, so no image library
is needed. Nothing in this module logs photo contents or embeddings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import struct
from typing import Optional

MIN_DET_SCORE = 0.6
MIN_FACE_FRACTION = 0.25
SAME_PERSON_MIN_SIMILARITY = 0.50
MIN_PHOTOS = 2
MAX_PHOTOS = 3
MAX_PHOTO_BYTES = 4 * 1024 * 1024


@dataclass
class PhotoCheck:
    ok: bool
    problems: list[str] = field(default_factory=list)
    det_score: Optional[float] = None
    face_fraction: Optional[float] = None
    embedding: Optional[list[float]] = None

    def public(self) -> dict:
        """What the student sees: never the embedding."""
        return {
            "ok": self.ok,
            "problems": self.problems,
            "det_score": None if self.det_score is None else round(self.det_score, 3),
            "face_fraction": None if self.face_fraction is None else round(self.face_fraction, 3),
        }


def image_size(data: bytes) -> Optional[tuple[int, int]]:
    """(width, height) from a PNG or JPEG header, or None if it is neither."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return width, height
    if data[:2] != b"\xff\xd8":
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        (length,) = struct.unpack(">H", data[index + 2 : index + 4])
        # Start-of-frame markers carry the size; C4, C8 and CC are not frames.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return width, height
        index += 2 + length
    return None


def check_photo(data: bytes, extraction: Optional[dict]) -> PhotoCheck:
    """Judge one photo from its bytes and the vision service's answer for it."""
    problems: list[str] = []
    if len(data) > MAX_PHOTO_BYTES:
        return PhotoCheck(False, ["The photo is too large; use one under 4 MB."])
    size = image_size(data)
    if size is None or min(size) <= 0:
        return PhotoCheck(False, ["Use a JPEG or PNG photo."])
    if not extraction or extraction.get("status") == "no_face":
        return PhotoCheck(False, ["No face was found. Face the camera in good light."])
    if extraction.get("status") != "ok" or not extraction.get("embedding"):
        return PhotoCheck(False, ["The photo could not be checked. Try again in a moment."])

    det_score = float(extraction.get("det_score") or 0.0)
    if det_score < MIN_DET_SCORE:
        problems.append("The face is not clear enough. Use a sharper photo in better light.")

    face_fraction: Optional[float] = None
    box = extraction.get("bbox")
    if isinstance(box, (list, tuple)) and len(box) == 4:
        face_side = min(box[2] - box[0], box[3] - box[1])
        face_fraction = max(0.0, face_side / min(size))
        if face_fraction < MIN_FACE_FRACTION:
            problems.append(
                "The face is too small. Come closer so your face fills more of the photo."
            )
    else:
        problems.append("The photo could not be checked. Try again in a moment.")

    return PhotoCheck(
        ok=not problems,
        problems=problems,
        det_score=det_score,
        face_fraction=face_fraction,
        embedding=[float(v) for v in extraction["embedding"]],
    )


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def same_person(embeddings: list[list[float]]) -> bool:
    return all(
        cosine(embeddings[i], embeddings[j]) >= SAME_PERSON_MIN_SIMILARITY
        for i in range(len(embeddings))
        for j in range(i + 1, len(embeddings))
    )


def mean_template(embeddings: list[list[float]]) -> list[float]:
    """The normalised mean of the embeddings: the template that is stored."""
    total = [sum(values) for values in zip(*embeddings)]
    norm = math.sqrt(sum(v * v for v in total))
    return [v / norm for v in total] if norm else total
