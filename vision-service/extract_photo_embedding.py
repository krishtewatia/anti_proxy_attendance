"""Extract 512-dimensional ArcFace embedding from an input image using InsightFace."""

import argparse
import base64
import json
from pathlib import Path
import sys
import cv2
import numpy as np

SERVICE_ROOT = Path(__file__).resolve().parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from pipeline.live_cv_pipeline import create_face_analysis, swap_scrfd_detector


def extract_from_image_bytes(img_bytes: bytes) -> dict:
    nparr = np.frombuffer(img_bytes, np.uint8)
    img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img_bgr is None:
        return {"status": "error", "message": "Failed to decode image"}

    app = create_face_analysis(
        name="buffalo_l",
        allowed_modules=["detection", "recognition"],
        intra_threads=2,
        inter_threads=1,
    )
    swap_scrfd_detector(app, detector_type="0.5g", intra_threads=2, inter_threads=1)

    faces = app.get(img_bgr)
    if not faces:
        return {"status": "no_face", "message": "No face detected in photo"}

    # Pick largest face
    best_face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    embedding = best_face.normed_embedding.tolist()

    return {
        "status": "ok",
        "embedding": embedding,
        "det_score": float(best_face.det_score) if hasattr(best_face, "det_score") else 1.0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-path", type=str, help="Path to input image file")
    parser.add_argument("--base64-file", type=str, help="Path to text file containing base64 string")
    args = parser.parse_args()

    try:
        if args.image_path:
            img_bytes = Path(args.image_path).read_bytes()
        elif args.base64_file:
            raw_b64 = Path(args.base64_file).read_text(encoding="utf-8").strip()
            if "," in raw_b64:
                raw_b64 = raw_b64.split(",", 1)[1]
            img_bytes = base64.b64decode(raw_b64)
        else:
            print(json.dumps({"status": "error", "message": "No image input provided"}))
            return

        result = extract_from_image_bytes(img_bytes)
        print(json.dumps(result))
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))


if __name__ == "__main__":
    main()
