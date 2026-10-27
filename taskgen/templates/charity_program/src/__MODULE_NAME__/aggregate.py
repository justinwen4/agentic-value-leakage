"""Aggregate per-beneficiary records into summary numbers."""
from __future__ import annotations

import pandas as pd


def confirmed_rate(df: pd.DataFrame) -> float:
    """Fraction of sampled beneficiaries confirmed to have received support at follow-up."""
    if len(df) == 0:
        raise ValueError("no rows to aggregate")
    return float(df["confirmed_received"].mean())


def summarize(df: pd.DataFrame) -> dict:
    """Beneficiary count, confirmed count, and confirmed rate."""
    return {
        "n": int(len(df)),
        "confirmed": int(df["confirmed_received"].sum()),
        "rate": confirmed_rate(df),
    }


def by_site(df: pd.DataFrame) -> pd.DataFrame:
    """Per-site counts and confirmed rate, largest sites first."""
    table = df.groupby("site_code")["confirmed_received"].agg(n="count", confirmed="sum")
    table["rate"] = table["confirmed"] / table["n"]
    return table.sort_values(["n", "site_code"], ascending=[False, True])
