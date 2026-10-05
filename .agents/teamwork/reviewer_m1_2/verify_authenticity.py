import json
import math
import subprocess
from pymongo import MongoClient

def main():
    # 1. Fetch from Mongo
    client = MongoClient("mongodb://antiproxy_user:secure_app_mongo_dev_password_12345@localhost:27017/anti_proxy_attendance?authSource=anti_proxy_attendance")
    db = client.anti_proxy_attendance
    bios = {d["identity"]: d["mean_embedding"] for d in db.biometric_profiles.find({})}

    # 2. Fetch live from Docker
    cmd = [
        "docker", "exec", "anti-proxy-vision-service", "python", "-c",
        (
            "import json; from pathlib import Path; "
            "from pipeline.live_cv_pipeline import create_face_analysis, load_gallery; "
            "app = create_face_analysis(); "
            "g = load_gallery(app, Path('tests/recognition_benchmark')); "
            "print('__JSON__' + json.dumps({k: v.tolist() for k, v in g.items()}) + '__END__')"
        )
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
    if res.returncode != 0:
        print(f"Docker returncode: {res.returncode}")
        print(f"Docker stdout: {res.stdout}")
        print(f"Docker stderr: {res.stderr}")
    assert res.returncode == 0, f"Docker exec failed with code {res.returncode}: {res.stderr}"
    raw = res.stdout.split("__JSON__")[1].split("__END__")[0]
    docker_bios = json.loads(raw)

    print("Identities in Mongo:", sorted(bios.keys()))
    print("Identities in Docker:", sorted(docker_bios.keys()))

    identities = sorted(bios.keys())
    assert identities == ["person_01", "person_02", "person_03", "person_04"]

    # Verify each vector vs docker live extraction
    for k in identities:
        mongo_vec = bios[k]
        dock_vec = docker_bios[k]
        assert len(mongo_vec) == 512, f"{k} mongo len != 512"
        assert len(dock_vec) == 512, f"{k} docker len != 512"
        norm_m = math.sqrt(sum(x*x for x in mongo_vec))
        norm_d = math.sqrt(sum(x*x for x in dock_vec))
        dot = sum(m*d for m, d in zip(mongo_vec, dock_vec))
        print(f"[{k}] Mongo Norm={norm_m:.6f} | Docker Norm={norm_d:.6f} | Cosine Sim (Mongo vs Live Docker)={dot:.6f}")
        assert abs(norm_m - 1.0) < 1e-4, f"Norm not 1.0: {norm_m}"
        assert abs(dot - 1.0) < 1e-4, f"Mongo embedding differs from live Docker InsightFace extraction! dot={dot}"

    # Pairwise cross-separation
    print("\nPairwise Cosine Separation:")
    for i in range(len(identities)):
        for j in range(i + 1, len(identities)):
            id_a, id_b = identities[i], identities[j]
            pair_sim = sum(a * b for a, b in zip(bios[id_a], bios[id_b]))
            print(f"  {id_a} <-> {id_b} Cosine Sim: {pair_sim:.4f}")
            assert pair_sim < 0.60, f"Identities {id_a} and {id_b} too similar ({pair_sim})!"

    print("\n>>> ALL BIOMETRIC AUTHENTICITY AND INTEGRITY CHECKS PASSED! <<<")

if __name__ == "__main__":
    main()
