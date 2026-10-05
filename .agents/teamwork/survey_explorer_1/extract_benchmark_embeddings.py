import subprocess
import json
import sys

cmd = [
    "docker", "exec", "anti-proxy-vision-service",
    "python", "-c",
    "from pipeline.live_cv_pipeline import create_face_analysis, load_gallery; "
    "from pathlib import Path; import json; "
    "app = create_face_analysis('buffalo_l'); "
    "gal = load_gallery(app, Path('tests/recognition_benchmark')); "
    "print(json.dumps({k: v.tolist() for k, v in gal.items()}))"
]

res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    print(f"Error: {res.stderr}", file=sys.stderr)
    sys.exit(res.returncode)

for line in res.stdout.splitlines():
    line = line.strip()
    if line.startswith("{") and line.endswith("}"):
        data = json.loads(line)
        print("Extracted identities:", list(data.keys()))
        for k, v in data.items():
            print(f"  {k}: length={len(v)}, first 3={v[:3]}")
        with open("benchmark_embeddings.json", "w") as f:
            json.dump(data, f)
        print("Saved to benchmark_embeddings.json")
        break
