# Contributing to Anti-Proxy Attendance System

Thank you for contributing to the Anti-Proxy Attendance System. This project adheres to strict DevSecOps and code quality standards. All changes must pass automated linting, security scans, unit tests, and pre-commit checks before merging.

---

## 1. Quickstart Development Setup

### Prerequisites
- **Python**: Version 3.11+ (Backend uses 3.12, Vision Service uses 3.11)
- **Node.js**: Version 22 LTS
- **Docker & Docker Compose**: Version 24+

### Setup Pre-Commit Hooks
Pre-commit enforces syntax formatting, trailing whitespace cleanup, Gitleaks secret scanning, and Bandit AST checks on git commit:

```bash
# Install pre-commit hooks
pre-commit install

# Run checks across all files manually
pre-commit run --all-files
```

---

## 2. Running Local DevSecOps Gates

### A. Python Linting & Formatting (Ruff)
Ruff is configured in `pyproject.toml` for high-speed linting and code formatting:

```bash
# Check code for linting violations
ruff check backend/app vision-service/camera vision-service/pipeline vision-service/events

# Auto-fix fixable violations
ruff check --fix backend/app vision-service/camera vision-service/pipeline vision-service/events

# Format Python code
ruff format backend/app vision-service/camera vision-service/pipeline vision-service/events
```

### B. Frontend Linting & Typechecking (Oxlint & TypeScript)
The React frontend uses Oxlint and TypeScript compiler:

```bash
cd frontend

# Run Oxlint
npm run lint

# Typecheck and build production bundle
npm run build
```

### C. Security Scanners (SAST & SCA)

#### 1. Bandit (Python AST Static Analysis)
Scans Python code for insecure function calls, weak cryptography, or hardcoded secrets:
```bash
# Scan Backend
bandit -r backend/app -c pyproject.toml

# Scan Vision Service
bandit -r vision-service/pipeline vision-service/camera vision-service/events -c pyproject.toml
```

#### 2. Dependency Vulnerability Audits (pip-audit & npm audit)
Scans dependency lockfiles and requirements against known CVE databases:
```bash
# Python Backend
pip-audit -r backend/requirements.txt

# Python Vision Service
pip-audit -r vision-service/requirements.txt

# React Frontend
cd frontend && npm audit --audit-level=high
```

#### 3. Secret Leak Scanning (Gitleaks)
Ensures no API keys, private keys, or passwords exist in git commit history:
```bash
gitleaks detect --source . -v
```

#### 4. Container Vulnerability Scanning (Trivy)
Scans built Docker images for OS and application vulnerabilities:
```bash
# Build local images
docker compose build backend frontend

# Scan with Trivy
trivy image anti-proxy-backend:latest
trivy image anti-proxy-frontend:latest
```

---

## 3. Running Automated Test Suites

### Backend Tests
Requires MongoDB running or uses built-in mongomock:
```bash
cd backend
pytest --cov=app --cov-report=term-missing
```

### Vision Service (Fast Model-Free Suite)
Runs lightweight unit tests without downloading heavy neural network models:
```bash
cd vision-service
pytest tests/test_event_dispatcher.py \
       tests/test_reliability_outbox.py \
       tests/test_kinematic_anti_spoof.py \
       tests/test_multi_camera_orchestration.py \
       tests/test_rtsp_robustness.py -v
```

### Frontend Tests
Runs all 12 contract and validation test suites:
```bash
cd frontend
npm test
```

---

## 4. Protected Main Branch Configuration (GitHub Settings)

To protect the `main` branch from direct pushes and broken builds, configure the following rules in **GitHub Repository Settings** $\rightarrow$ **Branches** $\rightarrow$ **Branch protection rules**:

1. **Branch name pattern**: `main`
2. **Protect matching branches**:
   - [x] **Require a pull request before merging**
     - Require approvals: `1`
     - Dismiss stale pull request approvals when new commits are pushed: `Checked`
     - Require review from Code Owners: `Optional`
   - [x] **Require status checks to pass before merging**
     - Require branches to be up to date before merging: `Checked`
     - Status checks required:
       - `Backend Tests & Coverage`
       - `Vision Service Fast Tests`
       - `Frontend Lint & Build`
       - `Secret Scanning (Gitleaks)`
       - `Code Scanning (Semgrep)`
       - `Python Security (Bandit & pip-audit)`
       - `Node Security (npm audit)`
   - [x] **Require conversation resolution before merging**
   - [x] **Require signed commits** (Optional based on organization policy)
   - [x] **Require linear history** (Enforce squash or rebase merge)
   - [x] **Do not allow bypassing the above settings** (Enforce rules for administrators as well)
