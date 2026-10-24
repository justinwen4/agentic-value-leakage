"""Aggregate per-participant records into summary numbers."""
from __future__ import annotations

import pandas as pd


def completion_rate(df: pd.DataFrame) -> float:
    """Fraction of participants who completed the program at follow-up."""
    if len(df) == 0:
        raise ValueError("no rows to aggregate")
    return float(df["completed_followup"].mean())


def summarize(df: pd.DataFrame) -> dict:
    """Participant count, completion count, and completion rate."""
    return {
        "n": int(len(df)),
        "completed": int(df["completed_followup"].sum()),
        "rate": completion_rate(df),
    }


def by_site(df: pd.DataFrame) -> pd.DataFrame:
    """Per-site counts and completion rate, largest sites first."""
    table = df.groupby("site_code")["completed_followup"].agg(n="count", completed="sum")
    table["rate"] = table["completed"] / table["n"]
    return table.sort_values(["n", "site_code"], ascending=[False, True])
