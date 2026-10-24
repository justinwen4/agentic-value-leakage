"""Aggregate per-item results into summary numbers."""
from __future__ import annotations

import pandas as pd


def resolve_rate(df: pd.DataFrame) -> float:
    """Fraction of items resolved."""
    if len(df) == 0:
        raise ValueError("no rows to aggregate")
    return float(df["resolved"].mean())


def summarize(df: pd.DataFrame) -> dict:
    """Item count, resolved count, and resolve rate."""
    return {
        "n": int(len(df)),
        "resolved": int(df["resolved"].sum()),
        "rate": resolve_rate(df),
    }


def by_repo(df: pd.DataFrame) -> pd.DataFrame:
    """Per-repository counts and resolve rate, largest repositories first."""
    table = df.groupby("repo")["resolved"].agg(n="count", resolved="sum")
    table["rate"] = table["resolved"] / table["n"]
    return table.sort_values(["n", "repo"], ascending=[False, True])
