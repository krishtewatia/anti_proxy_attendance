# Biometric Data Collection Protocol & Volunteer Consent Policy

## 1. Overview & Purpose
This document establishes the ethical, legal, and operational protocol for collecting and managing face evaluation datasets for the Automated Anti-Proxy Attendance System.

The sole purpose of gathering facial image data is to benchmark, evaluate, and tune facial detection, recognition thresholds, and anti-proxy tracking accuracy within a controlled educational environment.

> [!IMPORTANT]
> **Strict Prohibition on Third-Party Face Scraping**:
> In accordance with privacy regulations and institutional ethics guidelines, scraping faces from public websites, social media, or search engines is **strictly prohibited**. Third-party face datasets (e.g., LFW, CelebA, CASIA-WebFace) must **NOT** be utilized unless their license and informed consent provisions are explicitly verified and formally approved.

---

## 2. Informed Consent & Participant Rights
All subjects participating in dataset collection must be fully informed adult volunteers who have executed an explicit written Informed Consent Agreement.

### 2.1 Core Volunteer Rights
1. **Voluntary Participation**: Participation is 100% voluntary. Refusal to participate has zero academic, employment, or grading penalty.
2. **Specific Purpose Limitation**: Biometric data will be used strictly for evaluating the anti-proxy recognition pipeline and determining mathematical similarity thresholds. It will never be used for commercial profiling, law enforcement, or surveillance.
3. **Local-Only Storage**: All raw images and extracted mathematical embeddings are stored strictly on local encrypted development workstations. **No data is ever uploaded to public clouds, third-party APIs, or external SaaS vendors.**
4. **Git Exclusion Guarantee**: All dataset directories (`data/`, `evaluation_dataset/`, `*.npy`, `*.npz`) are permanently gitignored. No biometric data or personally identifying imagery is committed to source control or published in issue trackers.
5. **Right to Immediate Withdrawal and Deletion**:
   - Any volunteer may withdraw consent at any time without providing a reason.
   - Upon withdrawal, all raw images, cropped faces, and mathematical embeddings associated with the volunteer are immediately and permanently purged from all local disks using secure deletion.

---

## 3. Standardized Dataset Layout
Evaluation data is stored in the local, gitignored directory structure: `data/evaluation_dataset/`.

```
data/evaluation_dataset/
├── README.md                          # Directory documentation & safety notice
├── dataset_manifest.json              # Condition metadata per image (subject, condition tags)
├── enrollment/                        # Enrollment reference images (3-5 per subject)
│   ├── person_01/
│   │   ├── enroll_01.jpg              # Frontal, neutral expression, baseline lighting
│   │   ├── enroll_02.jpg              # Frontal, slight head angle variation (±10 deg)
│   │   └── enroll_03.jpg              # Frontal, natural smile / slight expression
│   ├── person_02/
│   │   └── ...
│   └── person_N/
│       └── ...
└── probes/                            # Test/probe images evaluated across conditions
    ├── person_01/
    │   ├── frontal_normal_01.jpg      # Baseline condition: frontal, standard lighting
    │   ├── frontal_dim_02.jpg         # Lighting condition: low-light (< 50 lux)
    │   ├── frontal_backlit_03.jpg     # Lighting condition: strong backlighting / window glare
    │   ├── yaw_left_04.jpg            # Pose angle: ~30 deg yaw left
    │   ├── yaw_right_05.jpg           # Pose angle: ~30 deg yaw right
    │   ├── pitch_down_06.jpg          # Pose angle: ~20 deg downward pitch (phone held low)
    │   ├── pitch_up_07.jpg            # Pose angle: ~20 deg upward pitch (camera mounted high)
    │   ├── distance_close_08.jpg      # Distance: ~1.0 meter from camera
    │   ├── distance_far_09.jpg        # Distance: ~3.5 meters from camera
    │   ├── glasses_on_10.jpg          # Occlusion: corrective glasses worn
    │   └── glasses_off_11.jpg         # Occlusion: corrective glasses removed
    ├── ...
    └── unknown/                       # Open-set impostor probes (subjects NOT in enrollment/)
        ├── unknown_01_01.jpg
        ├── unknown_02_01.jpg
        └── ...
```

---

## 4. Collection Conditions Specification

To ensure rigorous evaluation, probe images must capture realistic variability encountered in lecture halls and classroom entrances:

| Condition Dimension | Test Categories | Operational Definition |
| :--- | :--- | :--- |
| **Lighting** | Normal (300–500 lux)<br>Dim (< 100 lux)<br>Backlit / Glare | Standard indoor fluorescent/LED classroom lighting.<br>Evening or curtain-drawn ambient lighting.<br>Strong directional light source behind the subject. |
| **Pose / Angle** | Frontal (0°)<br>Yaw Left / Right (±30°)<br>Pitch Up / Down (±20°) | Direct gaze into camera lens.<br>Subject turning towards doorway or fellow student.<br>Camera mounted above doorway looking down, or desk phone. |
| **Distance** | Close (1.0m)<br>Mid (2.0m)<br>Far (3.5m+) | Face width > 150px in 1080p frame.<br>Face width ~ 80–120px in 1080p frame.<br>Face width ~ 45–60px (near detection limit of SCRFD-0.5g). |
| **Accessories** | No Glasses<br>Glasses<br>Partial Obstruction | Baseline unobstructed face.<br>Corrective optical glasses or reading frames.<br>Hair covering forehead, winter scarf, or light shadow. |
| **Open-Set Cohort** | Unenrolled Impostors | Separate individuals who are **not** present in `enrollment/` gallery, simulating unauthorized visitors, drop-ins, or proxy impostors. |

---

## 5. Deletion & Verification Procedure
To delete a participant's data upon consent revocation:
1. Locate participant identifier (e.g., `person_04`).
2. Remove directory `data/evaluation_dataset/enrollment/person_04/`.
3. Remove directory `data/evaluation_dataset/probes/person_04/`.
4. Delete student biometric record in MongoDB:
   ```bash
   python -m app.services.enrollment_service delete --student-id "STU_..."
   ```
5. Purge cached embeddings:
   ```bash
   rm -f vision-service/evaluation/cache/embeddings.npz
   ```
6. Verify disk status with:
   ```bash
   git status -u  # Must report clean (no untracked biometric files)
   ```
