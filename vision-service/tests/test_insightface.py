from insightface.app import FaceAnalysis


def main():
    app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
    )

    app.prepare(ctx_id=0, det_size=(640, 640))

    print("InsightFace model loaded successfully.")
    print("Models:", list(app.models.keys()))


if __name__ == "__main__":
    main()
