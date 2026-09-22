# ADR-004: Biometric Storage

## Status
Accepted

## Context
Storing facial biometric data introduces critical privacy, compliance, and security risks. Raw facial imagery, if exposed or mishandled, cannot be rotated like passwords and creates significant legal liability. We must establish rigorous policies around biometric template representations, access restrictions, and retention lifecycles.

## Decision
We enforce strict data minimization and privacy-by-design principles:
1. **Mathematical Templates over Raw Images:**
   - We store irreversible numerical face embeddings / biometric feature vectors rather than raw enrollment photographs.
2. **Temporary Enrollment Imagery:**
   - Raw enrollment photos are held temporarily only for initial embedding extraction and verification.
   - Once validated, enrollment images are automatically deleted after the defined retention window.
3. **Retention & Admin Control:**
   - Biometric embeddings have strict, administrator-controlled retention policies.
4. **Access Control & Least Privilege:**
   - Only the facial recognition / vision service components have authorized access to query biometric template collections.
   - Biometric vectors are never exposed via public or non-privileged API endpoints.
5. **Revocation & Deletion:**
   - Revoked or un-enrolled templates are deactivated immediately and queued for irreversible deletion based on the deletion policy.
6. **CCTV Stream Retention Policy:**
   - Continuous 24/7 CCTV raw video is **not** permanently stored in the MVP.
   - Transient video segments or frame captures may be temporarily cached strictly for audit/investigative review of flagged incidents and are automatically purged under automated TTL (time-to-live) retention.

## Consequences
- **Positive:**
  - Dramatically lowers blast radius and liability in case of data breaches.
  - Complies with data protection standards (GDPR, biometric privacy guidelines) through automated data minimization and purpose limitation.
- **Trade-off:**
  - If the facial embedding model architecture is upgraded or changed to an incompatible dimension/representation, students may need to re-enroll to generate new vector templates.
