#!/usr/bin/env python3
"""Print the headline numbers for the current results.

Usage: python report.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from {{MODULE_NAME}}.report import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
