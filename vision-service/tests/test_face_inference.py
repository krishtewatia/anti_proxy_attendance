import cv2
from insightface.app import FaceAnalysis


IMAGE_PATH = "vision-service/tests/sample_face.jpg"


def main():
    app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
    )

    app.prepare(ctx_id=0, det_size=(640, 640))

    image = cv2.imread(IMAGE_PATH)

    if image is None:
        raise FileNotFoundError(f"Could not read image: {IMAGE_PATH}")

    faces = app.get(image)

    print(f"Faces detected: {len(faces)}")

    for i, face in enumerate(faces):
        print(f"\nFace {i + 1}")
        print("Bounding box:", face.bbox)
        print("Detection score:", face.det_score)
        print("Embedding shape:", face.embedding.shape)
        print("Embedding norm:", round(float((face.embedding ** 2).sum() ** 0.5), 4))


if __name__ == "__main__":
    main()
