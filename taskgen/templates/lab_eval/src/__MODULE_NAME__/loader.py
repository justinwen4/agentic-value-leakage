"""Load per-item evaluation results from the data directory."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
REQUIRED_COLUMNS = ["id", "repo", "resolved", "runtime_s", "run_at"]


def result_files(data_dir: Path | str = DATA_DIR) -> list[Path]:
    """All CSV result files under ``data_dir``, in name order."""
    return sorted(Path(data_dir).glob("*.csv"))


def load_results(data_dir: Path | str = DATA_DIR) -> pd.DataFrame:
    """Return one row per item id, combined across all result files."""
    files = result_files(data_dir)
    if not files:
        raise FileNotFoundError(f"no result files under {data_dir}")
    frames = [pd.read_csv(path) for path in files]
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset="id")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"result files are missing columns: {missing}")
    return df.reset_index(drop=True)
