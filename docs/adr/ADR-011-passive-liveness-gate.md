# ADR-011: Passive Liveness Gate on the Browser-Webcam Marking Path

## Status
Accepted (2026-10). Supersedes the postponement in ADR-008 for the browser-webcam flow. The gate ships in **observe** mode; switching the default to **enforce** is a separate change made after the evaluation in this document has been run.

## Context
Attendance is marked when the vision service recognizes an enrolled face in a frame sent by the teacher's browser (ADR-010 and the secured marking path). Recognition alone cannot tell a person from a picture of that person: a printed photo or a phone showing a student's face could be recognized and marked.

ADR-008 postponed a neural anti-spoofing model because the doorway pipeline needed 15 frames per second on CPU. That constraint no longer applies. The browser sends 2 to 3 frames per second, so each frame has a budget of roughly 330 to 500 ms.

### Options considered

| Option | License | Fit | Decision |
|---|---|---|---|
| **MiniFASNet ensemble** (Silent-Face-Anti-Spoofing, Minivision) | Apache-2.0 for code and the published weights. Training data is not disclosed. | Two 80x80 models, about 0.4 M parameters each. Measured here: about 6 ms per face on CPU (median; 10 ms at the 95th percentile, 14 photos). | **Adopted** |
| InsightFace liveness add-on | The package states its pretrained models are for non-commercial research only; the add-on's own notice could not be verified. | Already in the dependency, one call per face. | Not used |
| MiniFASNetV2-SE trained on CelebA-Spoof (third-party ONNX) | Apache-2.0 code, but the weights derive from a non-commercial dataset. | Ready-made ONNX. | Not used |
| Active challenge ("turn your head left") | Own code. | At 2 to 3 FPS a challenge needs 2 to 3 seconds and 6 to 9 frames per student, per-student state, and prompts on the teacher's screen. It handles several faces in view badly, and a fixed challenge is defeated by a replayed video of a head turning. | Not now. Could be added later for faces in an uncertain score band. |

Note on a licence already in use: the `buffalo_l` recognition models from InsightFace are also for non-commercial research only. That is acceptable for this project; a commercial deployment would need a licence from InsightFace.

## Decision

### 1. Where the gate runs
In the vision service (`vision-service/camera/liveness.py`, called from `camera/vision_api.py`), on every face that has already been matched to an enrolled student, **before** the recognition result is signed. Unknown faces are not checked: they are never signed anyway.

- **enforce**: a face is signed only if it is judged live. A spoof, an inference error, an unusable crop or a missing model all mean no signed result. The service refuses to start in enforce mode without the model.
- **observe**: the check runs and is logged, and the result is still signed.

A face that is refused is returned with status `spoof` (or `liveness_unavailable` when the check could not be made) and carries no signed result.

### 2. Liveness is attested inside the signature
The signed message is now version 2 and includes a liveness attestation:

```
v2|session_id|identity|confidence|issued_at|expires_at|nonce|liveness
```

`liveness` is `passed` (checked and judged live, enforce mode) or `unchecked` (observe mode). The backend rejects a result with no attestation, an unknown value, or a tampered one (the value is covered by the HMAC). With `LIVENESS_MODE=enforce` the backend accepts only `passed`, so a vision service that is running without enforcement cannot mark attendance. Both services read the same `LIVENESS_MODE` and are deployed together; version 1 results are no longer accepted.

### 3. What is logged and shown
- The vision service logs each non-live outcome with the session, the matched identity, the score, the reason and the mode.
- The backend writes a `SPOOF_ATTEMPT` audit event (session, presented identity, score, the session's teacher), at most one per student per session every 30 seconds.
- The teacher's camera view draws a red box labelled "Spoof detected" and shows a notice that nothing was marked. The student's name is not shown on the box.
- No frame, crop or embedding is logged or stored anywhere on this path.

### 4. Threshold
The score is the mean "real face" probability of the two models (0 to 1). The threshold is `LIVENESS_THRESHOLD`, default **0.5**, which is provisional: it approximates upstream's rule (real is the most likely of three classes) and has not been calibrated. The calibrated value comes from the evaluation below.

## Threat model

The gate is one of three controls. None of them is sufficient alone.

| Control | What it addresses | What it does not |
|---|---|---|
| **Liveness gate** | A printed photo, a photo on a phone, a video on a laptop held up to the camera. | High-quality or unusual presentation attacks it was not measured against (3D masks, high-resolution displays, injected video). |
| **Supervised capture** | The camera is the teacher's, in the classroom, with the teacher watching the screen. An attacker has to hold a spoof up in front of the teacher, and the overlay tells the teacher when the system suspects one. | An inattentive or colluding teacher. |
| **Audited manual corrections** | A wrong mark, in either direction, can be corrected by the teacher. Corrections lock the record against later recognitions and are written to the audit log with the reason. Spoof attempts are audited too. | A correction nobody makes. |

Out of scope: an attacker who controls the teacher's browser or camera driver and injects frames (the frame route trusts the teacher's session), and attacks on enrollment (a student enrolling someone else's photo). Enrollment does not run the liveness gate.

### Limits of what has been measured
- The model's training data and its accuracy on faces, skin tones, cameras and lighting unlike those it was trained on are unknown. The upstream authors state that robustness depends on the camera and the scene.
- The evaluation set is one person, one camera, three attack types and a few dozen attempts. It shows whether the gate works in this setup. It is not a general accuracy claim.
- With zero accepted spoofs out of N attempts the true rate is not zero: the 95% upper bound is about 3/N (for 24 attempts, about 12%).
- One accepted frame marks attendance, so results are reported per attempt as well as per frame.

## Evaluation

Captured by the project owner, with their own face only, following `docs/evaluation/liveness_capture_guide.md`, and stored outside the repository under `$VISION_FIXTURES_DIR/liveness`. Measured with:

```bash
cd vision-service
VISION_FIXTURES_DIR=/path/to/fixtures python evaluation/liveness_eval.py
```

The script reports, for a range of thresholds, the false accept rate (spoofs passed) per attack type and the false reject rate (real faces blocked), per frame and per attempt. A spoof attempt counts as accepted if any of its frames passes; a live attempt counts as rejected only if all of its frames fail.

**Threshold rule:** the lowest threshold at which no spoof attempt is accepted, provided no live attempt is rejected and at most 5% of live frames are rejected. If no threshold meets that, the script recommends none, and the next step is requiring two consecutive passing frames (`--consecutive 2`) rather than accepting a compromise.

### Results
*Not yet measured. To be filled in from the evaluation run, together with the commit that switches the default mode to enforce.*

| | Value |
|---|---|
| Live attempts / frames | |
| Attack attempts (print / phone screen / laptop replay) | |
| Chosen threshold | |
| False accept rate, per attempt (per attack type) | |
| False reject rate, per frame / per attempt | |

## Reproducing the model files

The vision-service image downloads two ONNX files from the `liveness-models-v1` release of this repository at build time, with the SHA-256 enforced by the builder (`ADD --checksum`); a mismatch fails the build. The service checks the hashes again when it loads the files.

They were produced as follows.

1. **Source.** `https://github.com/minivision-ai/Silent-Face-Anti-Spoofing`, commit `b6d5f04ad78778917853b25c778acef6d5626d15` (Apache-2.0).

   | File | SHA-256 |
   |---|---|
   | `resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.pth` | `a5eb02e1843f19b5386b953cc4c9f011c3f985d0ee2bb9819eea9a142099bec0` |
   | `resources/anti_spoof_models/4_0_0_80x80_MiniFASNetV1SE.pth` | `84ee1d37d96894d5e82de5a57df044ef80a58be2b218b5ed7cdfd875ec2f5990` |

2. **Fetch** the three files the conversion needs into a folder (the repository cannot be checked out on Windows because one of its log file names is not a valid path there):

   ```bash
   SHA=b6d5f04ad78778917853b25c778acef6d5626d15
   BASE=https://raw.githubusercontent.com/minivision-ai/Silent-Face-Anti-Spoofing/$SHA
   mkdir -p up/src/model_lib up/resources/anti_spoof_models out
   for f in src/model_lib/MiniFASNet.py \
            resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.pth \
            resources/anti_spoof_models/4_0_0_80x80_MiniFASNetV1SE.pth; do
     curl -sSfL "$BASE/$f" -o "up/$f"
   done
   ```

3. **Convert** in a throwaway container (PyTorch is needed only for this step):

   ```bash
   docker run --rm \
     -v "$PWD/up:/upstream:ro" -v "$PWD/out:/out" \
     -v "$PWD/vision-service/tools/convert_minifasnet_to_onnx.py:/convert.py:ro" \
     python:3.11-slim sh -c "
       pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu &&
       pip install onnx==1.17.0 onnxruntime==1.20.1 numpy==2.1.3 &&
       python /convert.py --upstream /upstream --out /out"
   ```

   The script checks the input hashes, loads the weights with `weights_only=True`, exports with opset 17, validates the graph, and compares the ONNX output with PyTorch on random image-like inputs (maximum absolute difference 2.4e-6 and 1.8e-6).

4. **Result.**

   | File | SHA-256 | Crop scale |
   |---|---|---|
   | `minifasnet_v2_scale2.7_80x80.onnx` | `c058068e54189e467aff1991442b8cf5c75220ab0356f49c9508aaff9e3e91e6` | 2.7 |
   | `minifasnet_v1se_scale4.0_80x80.onnx` | `2be5c295aefee7bf6356edbf6303b1827aab5d793e4a1898de4e11fb0fa2db35` | 4.0 |

   The weights are unchanged; only the file format differs. A fresh conversion is functionally the same but is not guaranteed to be byte-identical, so the pinned hashes refer to the published files. The release also carries `manifest.json`, the upstream licence and a notice of the change.

5. **Inference**, exactly as upstream: the face box is enlarged around its centre by the crop scale (reduced if it would not fit, shifted if it touches an edge), resized to 80x80, and fed as BGR float values 0 to 255 with no normalization. Each model returns three logits; class 1 is "real". The score is the mean softmax probability of class 1.

## Consequences
**Positive**
- A held-up photo or screen is checked before anything is signed, and in enforce mode cannot be marked.
- The backend can tell from the signature whether liveness was enforced, so a misconfigured vision service cannot mark attendance in an enforcing deployment.
- About 6 ms per recognized face; no effect on frames without a recognized face.

**Negative**
- Real students can be rejected (poor lighting, strong backlight, very small faces). The teacher sees it and can mark manually, which is audited.
- A new model with unknown training data sits on the marking path. Its behaviour outside the measured setup is unknown.
- The image build now needs to reach GitHub to download the model files.
- The signature format changed; backend and vision service must be deployed together.

## Revisit when
- The evaluation shows live and spoof scores overlapping (no usable threshold).
- A spoof is reported in real use.
- The camera or its resolution changes: re-run the evaluation.
