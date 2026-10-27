"""Positive control: P(Public) under the two README variants at the midpoint.

    python -m analysis.positive_control --runs runs/positive_control --model gpt-5.5 \
        [--population primary] [--bootstrap 2000] [--seed 0]

Reads the graded runs of configs/positive_control.yaml (``meta.readme_variant``
is ``prefer_quiet`` or ``must_correct``). Per docs/prereg.md (Positive
control), the check is the difference in P(Public) between the two variants
at the midpoint m, with a 95% interval; if the interval includes zero the task
cannot detect leakage and a null is uninterpretable.

- **Populations.** As ``analysis.fit_curves.population``: Leaked, Incomplete
  and Ask runs are dropped; primary keeps runs that pass the manipulation
  check, secondary keeps all.
- **Per arm.** P(Public) per variant and direction, and over both directions,
  with a Wilson 95% interval.
- **Difference.** must_correct minus prefer_quiet, per direction and over both,
  with a bootstrap 95% percentile interval: runs resampled with replacement
  inside variant x direction x headline value.

Keep these runs in their own runs directory. ``fit_curves.load_runs`` does not
read ``readme_variant``, so variant runs under the shared ``runs/`` would be
pooled into Ambervale's P0 cells by ``fit_curves`` and ``noise_baseline``.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.fit_curves import load_runs, population

VARIANTS = ("prefer_quiet", "must_correct")
BOTH = "both"
_Z = 1.959963984540054


def load_variant_runs(runs_dir: Path) -> pd.DataFrame:
    """``fit_curves.load_runs`` plus ``readme_variant`` from each run's meta.json."""
    runs = load_runs(runs_dir)
    if runs.empty:
        return runs
    runs["readme_variant"] = [
        json.loads((Path(run_dir) / "meta.json").read_text(encoding="utf-8")).get("readme_variant", "none")
        for run_dir in runs["run_dir"]
    ]
    return runs


def wilson(successes: int, n: int) -> tuple[float, float]:
    if n == 0:
        return math.nan, math.nan
    p = successes / n
    denom = 1 + _Z**2 / n
    centre = (p + _Z**2 / (2 * n)) / denom
    half = _Z * math.sqrt(p * (1 - p) / n + _Z**2 / (4 * n**2)) / denom
    return centre - half, centre + half


def _directions(runs: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    return [(d, runs[runs["direction"] == d]) for d in sorted(runs["direction"].unique())] + [(BOTH, runs)]


def arm_table(runs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for direction, frame in _directions(runs):
        for variant in VARIANTS:
            cell = frame[frame["readme_variant"] == variant]
            n, s = len(cell), int(cell["public"].sum())
            lo, hi = wilson(s, n)
            rows.append({"variant": variant, "direction": direction, "n": n, "public": s,
                         "p_public": s / n if n else math.nan, "ci_low": lo, "ci_high": hi})
    return pd.DataFrame(rows)


def _diff(public: np.ndarray, is_must: np.ndarray) -> float:
    if not is_must.any() or is_must.all():
        return math.nan
    return float(public[is_must].mean() - public[~is_must].mean())


def diff_table(runs: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for direction, frame in _directions(runs):
        public = frame["public"].to_numpy(dtype=float)
        is_must = (frame["readme_variant"] == VARIANTS[1]).to_numpy()
        strata = [idx for idx in frame.groupby(["readme_variant", "direction", "base_rate"]).indices.values()]
        estimate = _diff(public, is_must)
        draws = []
        for _ in range(n_boot):
            pick = np.concatenate([rng.choice(idx, size=len(idx), replace=True) for idx in strata])
            draw = _diff(public[pick], is_must[pick])
            if not math.isnan(draw):
                draws.append(draw)
        lo, hi = np.percentile(draws, [2.5, 97.5]) if draws else (math.nan, math.nan)
        rows.append({"direction": direction, "diff": estimate, "ci_low": float(lo), "ci_high": float(hi),
                     "includes_zero": bool(lo <= 0 <= hi) if draws else None})
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P(Public) by README variant at the midpoint, and the difference.")
    parser.add_argument("--runs", type=Path, default=Path("runs/positive_control"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--population", choices=("primary", "all"), default="primary")
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    runs = load_variant_runs(args.runs)
    if runs.empty:
        print(f"no graded runs under {args.runs}", file=sys.stderr)
        return 1
    runs = runs[(runs["model"] == args.model) & runs["readme_variant"].isin(VARIANTS)]
    if runs["m"].nunique() > 1:
        print(f"expected one midpoint m, found {sorted(runs['m'].unique())}", file=sys.stderr)
        return 1
    runs = population(runs, args.population)
    if runs.empty:
        print(f"no {args.population} runs for {args.model} with a README variant", file=sys.stderr)
        return 1
    with pd.option_context("display.width", 200):
        print(arm_table(runs).to_string(index=False))
        print(diff_table(runs, args.bootstrap, args.seed).to_string(index=False))
    print({"model": args.model, "m": int(runs["m"].iloc[0]), "population": args.population,
           "difference": "must_correct - prefer_quiet"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
