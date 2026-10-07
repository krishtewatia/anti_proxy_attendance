#!/usr/bin/env python3
"""Convert the two published MiniFASNet anti-spoofing weights to ONNX.

Source: https://github.com/minivision-ai/Silent-Face-Anti-Spoofing (Apache-2.0),
pinned to commit b6d5f04ad78778917853b25c778acef6d5626d15.

This is a one-off, offline step. PyTorch is needed only here; the vision
service runs the resulting files with ONNX Runtime. The exact commands, the
input hashes and the output hashes are recorded in
docs/adr/ADR-011-passive-liveness-gate.md.

Usage (inside a throwaway container, see the ADR):

    python convert_minifasnet_to_onnx.py --upstream /upstream --out /out

``--upstream`` is a directory holding these files from the pinned commit:

    src/model_lib/MiniFASNet.py
    resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.pth
    resources/anti_spoof_models/4_0_0_80x80_MiniFASNetV1SE.pth

Each ONNX model takes float32 [N, 3, 80, 80] (BGR, values 0-255, no
normalization, exactly as upstream feeds it) and returns [N, 3] raw logits.
Class index 1 is "real face"; softmax is applied by the caller.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import onnx
import onnxruntime as ort
import torch

UPSTREAM_COMMIT = "b6d5f04ad78778917853b25c778acef6d5626d15"
INPUT_SIZE = 80
# upstream: get_kernel(height, width) = ((height + 15) // 16, (width + 15) // 16)
CONV6_KERNEL = ((INPUT_SIZE + 15) // 16, (INPUT_SIZE + 15) // 16)

MODELS = [
    # (upstream weight file, factory name in MiniFASNet.py, crop scale, output file, expected sha256 of the .pth)
    (
        "2.7_80x80_MiniFASNetV2.pth",
        "MiniFASNetV2",
        2.7,
        "minifasnet_v2_scale2.7_80x80.onnx",
        "a5eb02e1843f19b5386b953cc4c9f011c3f985d0ee2bb9819eea9a142099bec0",
    ),
    (
        "4_0_0_80x80_MiniFASNetV1SE.pth",
        "MiniFASNetV1SE",
        4.0,
        "minifasnet_v1se_scale4.0_80x80.onnx",
        "84ee1d37d96894d5e82de5a57df044ef80a58be2b218b5ed7cdfd875ec2f5990",
    ),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_architecture(upstream: Path):
    spec = importlib.util.spec_from_file_location(
        "minifasnet_upstream", upstream / "src" / "model_lib" / "MiniFASNet.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    architecture = load_architecture(args.upstream)
    torch.manual_seed(0)
    rng = np.random.default_rng(0)
    manifest = {"upstream_commit": UPSTREAM_COMMIT, "models": []}

    for weight_name, factory, scale, out_name, expected_sha in MODELS:
        weight_path = args.upstream / "resources" / "anti_spoof_models" / weight_name
        actual_sha = sha256(weight_path)
        if actual_sha != expected_sha:
            print(
                f"ERROR: {weight_name} sha256 {actual_sha} != expected {expected_sha}",
                file=sys.stderr,
            )
            return 1

        model = getattr(architecture, factory)(conv6_kernel=CONV6_KERNEL)
        # The file's SHA-256 was checked above against the pinned upstream commit, and
        # weights_only=True restricts unpickling to tensors, so no arbitrary object is
        # loaded. This script runs offline in a throwaway container, never in the service.
        # nosemgrep: trailofbits.python.pickles-in-pytorch.pickles-in-pytorch
        state = torch.load(weight_path, map_location="cpu", weights_only=True)
        if next(iter(state)).startswith("module."):
            state = OrderedDict((key[7:], value) for key, value in state.items())
        model.load_state_dict(state, strict=True)
        model.eval()

        out_path = args.out / out_name
        dummy = torch.zeros(1, 3, INPUT_SIZE, INPUT_SIZE, dtype=torch.float32)
        torch.onnx.export(
            model,
            dummy,
            str(out_path),
            input_names=["input"],
            output_names=["logits"],
            dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
            opset_version=17,
            do_constant_folding=True,
            dynamo=False,
        )
        onnx.checker.check_model(onnx.load(str(out_path)))

        # Parity: the ONNX model must reproduce PyTorch on image-like inputs.
        session = ort.InferenceSession(str(out_path), providers=["CPUExecutionProvider"])
        batch = rng.uniform(0.0, 255.0, size=(4, 3, INPUT_SIZE, INPUT_SIZE)).astype(np.float32)
        with torch.no_grad():
            reference = model(torch.from_numpy(batch)).numpy()
        converted = session.run(None, {"input": batch})[0]
        max_abs_diff = float(np.max(np.abs(reference - converted)))
        if max_abs_diff > 1e-3:
            print(f"ERROR: {out_name} differs from PyTorch by {max_abs_diff}", file=sys.stderr)
            return 1

        entry = {
            "file": out_name,
            "sha256": sha256(out_path),
            "size_bytes": out_path.stat().st_size,
            "source_weights": weight_name,
            "source_sha256": actual_sha,
            "architecture": factory,
            "crop_scale": scale,
            "input": f"float32 [N, 3, {INPUT_SIZE}, {INPUT_SIZE}] BGR 0-255",
            "output": "float32 [N, 3] logits, index 1 = real face",
            "max_abs_diff_vs_pytorch": max_abs_diff,
        }
        manifest["models"].append(entry)
        print(json.dumps(entry))

    manifest["versions"] = {
        "torch": torch.__version__,
        "onnx": onnx.__version__,
        "onnxruntime": ort.__version__,
        "opset": 17,
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["versions"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
