from itertools import combinations
from pathlib import Path

import cv2
import numpy as np
from insightface.app import FaceAnalysis


BASE_DIR = Path("vision-service/tests/recognition_benchmark")


def load_images():
    people = {}

    for person_dir in sorted(BASE_DIR.iterdir()):
        if not person_dir.is_dir():
            continue

        image_paths = sorted(
            path
            for path in person_dir.iterdir()
            if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )

        if image_paths:
            people[person_dir.name] = image_paths

    return people


def get_embedding(app, image_path):
    image = cv2.imread(str(image_path))

    if image is None:
        raise FileNotFoundError(f"Could not read: {image_path}")

    faces = app.get(image)

    if len(faces) == 0:
        raise RuntimeError(f"No face detected in: {image_path}")

    if len(faces) > 1:
        raise RuntimeError(
            f"Expected 1 face but found {len(faces)} in: {image_path}"
        )

    return faces[0].embedding


def cosine_similarity(a, b):
    a = np.asarray(a)
    b = np.asarray(b)

    return float(
        np.dot(a, b)
        / (np.linalg.norm(a) * np.linalg.norm(b))
    )


def main():
    people = load_images()

    if len(people) < 2:
        raise RuntimeError(
            "At least two people are required for the benchmark."
        )

    print("=" * 60)
    print("INSIGHTFACE RECOGNITION BENCHMARK")
    print("=" * 60)

    print("\nPeople found:")

    for person, images in people.items():
        print(f"  {person}: {len(images)} image(s)")

    app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
    )

    app.prepare(ctx_id=0, det_size=(640, 640))

    embeddings = {}

    print("\n" + "=" * 60)
    print("GENERATING EMBEDDINGS")
    print("=" * 60)

    for person, image_paths in people.items():
        embeddings[person] = {}

        for image_path in image_paths:
            embedding = get_embedding(app, image_path)

            embeddings[person][image_path.name] = embedding

            print(
                f"{person} / {image_path.name} "
                f"-> {embedding.shape}"
            )

    genuine_scores = []
    impostor_scores = []

    # ---------------------------------------------------------
    # SAME-PERSON / GENUINE COMPARISONS
    # ---------------------------------------------------------

    print("\n" + "=" * 60)
    print("GENUINE (SAME-PERSON) COMPARISONS")
    print("=" * 60)

    for person, person_embeddings in embeddings.items():

        image_names = sorted(person_embeddings.keys())

        for image_a, image_b in combinations(image_names, 2):

            score = cosine_similarity(
                person_embeddings[image_a],
                person_embeddings[image_b],
            )

            genuine_scores.append(score)

            print(
                f"{person}: "
                f"{image_a} <-> {image_b} = {score:.4f}"
            )

    # ---------------------------------------------------------
    # DIFFERENT-PERSON / IMPOSTOR COMPARISONS
    # ---------------------------------------------------------

    print("\n" + "=" * 60)
    print("IMPOSTOR (DIFFERENT-PERSON) COMPARISONS")
    print("=" * 60)

    person_pairs = combinations(sorted(embeddings.keys()), 2)

    for person_a, person_b in person_pairs:

        for image_a, embedding_a in embeddings[person_a].items():

            for image_b, embedding_b in embeddings[person_b].items():

                score = cosine_similarity(
                    embedding_a,
                    embedding_b,
                )

                impostor_scores.append(score)

                print(
                    f"{person_a}/{image_a} <-> "
                    f"{person_b}/{image_b} = {score:.4f}"
                )

    # ---------------------------------------------------------
    # SUMMARY
    # ---------------------------------------------------------

    print("\n" + "=" * 60)
    print("BENCHMARK SUMMARY")
    print("=" * 60)

    print(f"\nGenuine comparisons: {len(genuine_scores)}")
    print(f"Impostor comparisons: {len(impostor_scores)}")

    print("\nGenuine similarity:")
    print(f"  Minimum : {min(genuine_scores):.4f}")
    print(f"  Maximum : {max(genuine_scores):.4f}")
    print(f"  Mean    : {np.mean(genuine_scores):.4f}")
    print(f"  Median  : {np.median(genuine_scores):.4f}")

    print("\nImpostor similarity:")
    print(f"  Minimum : {min(impostor_scores):.4f}")
    print(f"  Maximum : {max(impostor_scores):.4f}")
    print(f"  Mean    : {np.mean(impostor_scores):.4f}")
    print(f"  Median  : {np.median(impostor_scores):.4f}")

    print("\n" + "=" * 60)
    print("BENCHMARK COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
