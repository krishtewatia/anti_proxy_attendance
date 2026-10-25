"""Face photo checks for the student setup: size from the header, confidence,
face size, same person across photos, and the stored template."""

import math
import struct

from app.services import photo_quality as pq


def _png(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"


def _jpeg(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def _unit(index: int, size: int = 512) -> list[float]:
    vector = [0.0] * size
    vector[index] = 1.0
    return vector


def _ok(box=(100, 100, 400, 420), score=0.9, embedding=None) -> dict:
    return {"status": "ok", "embedding": embedding or _unit(0), "det_score": score, "bbox": list(box)}


def test_the_size_is_read_from_png_and_jpeg_headers():
    assert pq.image_size(_png(640, 480)) == (640, 480)
    assert pq.image_size(_jpeg(960, 720)) == (960, 720)
    assert pq.image_size(b"GIF89a....") is None


def test_a_clear_large_face_passes():
    check = pq.check_photo(_png(640, 480), _ok())
    assert check.ok and check.problems == []
    assert math.isclose(check.face_fraction, 300 / 480)
    # What the student sees never includes the embedding.
    assert "embedding" not in check.public()


def test_no_face_low_confidence_small_face_and_wrong_format_are_refused():
    assert pq.check_photo(_png(640, 480), {"status": "no_face"}).problems[0].startswith("No face")
    assert not pq.check_photo(_png(640, 480), _ok(score=0.5)).ok
    small = pq.check_photo(_png(640, 480), _ok(box=(10, 10, 100, 110)))
    assert not small.ok and "too small" in small.problems[0]
    assert pq.check_photo(b"not an image", _ok()).problems == ["Use a JPEG or PNG photo."]
    assert not pq.check_photo(_png(640, 480), {"status": "ok", "embedding": _unit(0)}).ok  # no box


def test_photos_must_show_the_same_person_at_the_recognition_threshold():
    same = [_unit(0), [0.9, 0.1] + [0.0] * 510]
    different = [_unit(0), _unit(1)]
    assert pq.same_person(same)
    assert not pq.same_person(different)
    assert pq.SAME_PERSON_MIN_SIMILARITY == 0.50


def test_the_template_is_the_normalised_mean():
    template = pq.mean_template([[1.0, 0.0], [0.0, 1.0]])
    assert math.isclose(template[0], 1 / math.sqrt(2)) and math.isclose(template[1], 1 / math.sqrt(2))
