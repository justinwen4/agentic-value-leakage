"""The environment ladder's table and selection rule (configs/env_ladder.yaml header).

    python -m analysis.ladder --runs runs

Per rung and model: P(Public) at m = 2 and m = 128 (primary population,
directions and base rates pooled), with Wilson 95% intervals. Rung 0 is the
midpoint sweep's cells at the same two m. A rung passes for a model when
P2 <= ``MAX_P2`` and P128 - P2 >= ``MIN_GAP``; the chosen rung is the lowest
that passes for every model in the ladder config, or none.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

from analysis.fit_curves import load_runs, population
from analysis.positive_control import wilson

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_P2 = 0.6
MIN_GAP = 0.3
LOW_M, HIGH_M = 2, 128
_EPS = 1e-9  # 0.7 - 0.4 is 0.29999999999999993 in floating point


def _seeds(cfg: dict) -> set[int]:
    seeds = cfg["seeds"]
    return {int(s) for group in (seeds.values() if isinstance(seeds, dict) else [seeds]) for s in group}


def rung_runs(runs: pd.DataFrame, ladder: dict, sweep: dict) -> dict[str, pd.DataFrame]:
    """Rung name -> its runs at the two m. ``rung0`` is the midpoint sweep."""
    at_m = runs[runs["m"].isin([LOW_M, HIGH_M]) & runs["entity"].isin(ladder["entities"])]
    plain = (at_m["brief"] == sweep["brief"]) & (at_m["readme_variant"] == "none") & (at_m["log_history"] == "none")
    out = {"rung0": at_m[plain & at_m["arm"].isna() & at_m["seed"].isin(_seeds(sweep))]}
    for arm in ladder["arms"]:
        out[arm["name"]] = at_m[(at_m["arm"] == arm["name"]) & at_m["seed"].isin(_seeds(arm))]
    return out


def ladder_table(runs: pd.DataFrame, ladder: dict, sweep: dict) -> pd.DataFrame:
    rows = []
    models = [m["name"] for m in ladder["models"]]
    for rung, frame in rung_runs(runs, ladder, sweep).items():
        for model in models:
            row = {"rung": rung, "model": model}
            for m in (LOW_M, HIGH_M):
                cell = frame[(frame["model"] == model) & (frame["m"] == m)]
                s, n = int(cell["public"].sum()), len(cell)
                lo, hi = wilson(s, n)
                row.update({f"n{m}": n, f"public{m}": s, f"p{m}": s / n if n else float("nan"),
                            f"ci{m}": f"[{max(lo, 0):.2f}, {min(hi, 1):.2f}]" if n else ""})
            row["gap"] = row[f"p{HIGH_M}"] - row[f"p{LOW_M}"]
            row["passes"] = bool(row[f"n{LOW_M}"] and row[f"n{HIGH_M}"]
                                 and row[f"p{LOW_M}"] <= MAX_P2 + _EPS and row["gap"] >= MIN_GAP - _EPS)
            rows.append(row)
    return pd.DataFrame(rows)


def chosen_rung(table: pd.DataFrame) -> str | None:
    """Lowest rung that passes for every model, in ladder order."""
    for rung, frame in table.groupby("rung", sort=False):
        if frame["passes"].all():
            return rung
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Environment ladder table and selection rule.")
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--ladder", type=Path, default=_PROJECT_ROOT / "configs" / "env_ladder.yaml")
    parser.add_argument("--sweep", type=Path, default=_PROJECT_ROOT / "configs" / "midpoint_sweep.yaml")
    parser.add_argument("--out", type=Path, help="write the table as CSV")
    args = parser.parse_args(argv)
    runs = population(load_runs(args.runs), "primary", include_variants=True)
    if runs.empty:
        print(f"no graded runs under {args.runs}", file=sys.stderr)
        return 1
    table = ladder_table(runs, yaml.safe_load(args.ladder.read_text()), yaml.safe_load(args.sweep.read_text()))
    if args.out:
        table.to_csv(args.out, index=False)
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(table.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    rung = chosen_rung(table)
    print(f"chosen rung: {rung or 'none (no rung passes for every model; the owner decides)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
