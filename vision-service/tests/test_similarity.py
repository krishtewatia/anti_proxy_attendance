import cv2
import numpy as np
from insightface.app import FaceAnalysis

IMG1_PATH = "vision-service/tests/sample_face.jpg"
IMG2_PATH = "vision-service/tests/sample_face_2.jpg"


def main():
    app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=0, det_size=(640, 640))

    img1 = cv2.imread(IMG1_PATH)
    img2 = cv2.imread(IMG2_PATH)

    if img1 is None:
        raise FileNotFoundError(f"Missing {IMG1_PATH}")
    if img2 is None:
        raise FileNotFoundError(f"Missing {IMG2_PATH}")

    faces1 = app.get(img1)
    faces2 = app.get(img2)

    print("=" * 45)
    print(f"Image 1 (sample_face.jpg):   {len(faces1)} face(s) detected")
    if faces1:
        print(f"  Score: {faces1[0].det_score:.4f}, Embedding shape: {faces1[0].embedding.shape}")

    print(f"Image 2 (sample_face_2.jpg): {len(faces2)} face(s) detected")
    if faces2:
        print(f"  Score: {faces2[0].det_score:.4f}, Embedding shape: {faces2[0].embedding.shape}")

    if faces1 and faces2:
        emb1 = faces1[0].embedding
        emb2 = faces2[0].embedding
        cosine_sim = float(np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2)))
        print("-" * 45)
        print(f"Cosine Similarity: {cosine_sim:.4f}")
        print("=" * 45)


if __name__ == "__main__":
    main()
