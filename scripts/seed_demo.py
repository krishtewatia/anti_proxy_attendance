#!/usr/bin/env python3
"""Seed & Bootstrap Script for Anti-Proxy Attendance Local Stack.

Delegates directly to seed_clean_demo.py to ensure strictly:
  - 1 Root Admin
  - 1 Teacher
  - 4 Students in DS-B
  - 0 Fake sessions, 0 Fake dates, 0 Fake attendance records
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from seed_clean_demo import main

if __name__ == "__main__":
    main()
