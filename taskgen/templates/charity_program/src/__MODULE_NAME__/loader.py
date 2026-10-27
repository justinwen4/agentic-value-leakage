"""Load per-beneficiary records from the data directory."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
REQUIRED_COLUMNS = [
    "id",
    "support_date",
    "site_code",
    "operations_year",
    "confirmed_received",
    "followup_lag_days",
    "verified_at",
]


def beneficiary_files(data_dir: Path | str = DATA_DIR) -> list[Path]:
    """All CSV record files under ``data_dir``, in name order."""
    return sorted(Path(data_dir).glob("*.csv"))


def load_beneficiaries(data_dir: Path | str = DATA_DIR) -> pd.DataFrame:
    """Return one row per beneficiary id, combined across all record files."""
    files = beneficiary_files(data_dir)
    if not files:
        raise FileNotFoundError(f"no record files under {data_dir}")
    frames = [pd.read_csv(path) for path in files]
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset="id")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"record files are missing columns: {missing}")
    return df.reset_index(drop=True)
