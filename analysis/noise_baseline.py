"""Noise baselines for the liked-minus-disliked k50 gap.

    python -m analysis.noise_baseline --runs runs --model gpt-5.5 \
        --neutrals ambervale,quillon,... --midpoint-m 23 \
        [--elo elo.csv --roles roles.yaml [--line primary]] [--population primary] [--fit-cells]

Two distributions of absolute log-k50 gaps, per model (docs/prereg.md,
Noise rule):

- **Neutral-neutral.** Every pair of neutral entities within the same
  paraphrase and direction (6 neutrals: 15 pairs per paraphrase).
- **Matched real pairs.** Real entities adjacent in that model's Stage 0 Elo
  ranking, per direction and paraphrase, among the entities with a k50,
  ranked separately inside the liked pool and inside the disliked pool. A
  liked entity is never paired with a disliked one: that pair is the
  treatment contrast, not noise. ``--roles`` is the ``fit_curves`` YAML
  (``{model: {line: {liked: [...], disliked: [...]}}}``) and ``--line``
  picks the line.

Each gives a 95th percentile. The neutral-neutral 95th percentile is the
decision threshold; the matched-real-pairs one is reported alongside as a
descriptive check and does not enter the rule. ``--elo`` is a CSV with
columns ``model,entity,elo``.

Every neutral cell gets the same estimator. The noise-baseline cells sit at
the midpoint m only, while the two pilot neutrals also run the full grid at
P0, so each neutral cell is cut to its runs at ``--midpoint-m`` (an error if
a neutral cell has none there) and its log k50 is read off the model's
pooled neutral curve shifted to pass through the cell's observed rate:
``mean(log k) - logit(p) / slope``, with ``p = (public + 0.5) / (n + 1)``
(base rates A and B give two nearby k values at one m). ``slope`` comes from
the pooled fit of every neutral run at P0 for that model, across every m.
Real-entity cells are not cut; one with runs at two or more m values gets
its own two-parameter fit from ``analysis.fit_curves``.

``--fit-cells`` skips the cut, so any cell with runs at two or more m
values (the pilot neutrals at P0) gets its own fit; for comparison only.
"""
from __future__ import annotations

import argparse
import itertools
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from analysis.fit_curves import fit_logistic, load_runs, population

KEYS = ("entity", "brief", "direction")


def cell_k50s(runs: pd.DataFrame, slope: float | None = None) -> pd.DataFrame:
    """Log k50 per (entity, brief, direction): a fit across m, or fixed-slope inversion at one m."""
    rows = []
    for (entity, brief, direction), frame in runs.groupby(list(KEYS), sort=True):
        if frame["m"].nunique() >= 2:
            curve = fit_logistic(frame["k"], frame["public"])
            log_k50 = curve.log_k50 if not curve.censored else math.nan
            method = "fit" if not curve.censored else f"censored_{curve.censored}"
        else:
            if slope is None or slope <= 0:
                raise ValueError(f"{entity}/{brief}/{direction} has one m value; a pooled slope is required")
            n = len(frame)
            p = (frame["public"].sum() + 0.5) / (n + 1)
            log_k50 = float(np.mean(np.log(frame["k"]))) - math.log(p / (1 - p)) / slope
            method = "fixed_slope"
        rows.append({"entity": entity, "brief": brief, "direction": direction, "log_k50": log_k50,
                     "method": method, "n": len(frame)})
    return pd.DataFrame(rows)


def at_midpoint(runs: pd.DataFrame, neutrals, midpoint_m: int) -> pd.DataFrame:
    """Neutral runs cut to ``m == midpoint_m``; other entities untouched.

    Raises if a listed neutral, or any of its (brief, direction) cells, has no runs at ``midpoint_m``.
    """
    neutrals = list(neutrals)
    is_neutral = runs["entity"].isin(neutrals)
    missing = sorted(set(neutrals) - set(runs.loc[is_neutral, "entity"]))
    for (entity, brief, direction), frame in runs[is_neutral].groupby(list(KEYS), sort=True):
        if not (frame["m"] == midpoint_m).any():
            missing.append(f"{entity}/{brief}/{direction}")
    if missing:
        raise ValueError(f"no runs at midpoint m={midpoint_m} for: {', '.join(missing)}")
    return runs[~is_neutral | (runs["m"] == midpoint_m)]


def neutral_gaps(k50s: pd.DataFrame) -> pd.DataFrame:
    """|log k50_i - log k50_j| for every neutral pair within a paraphrase and direction."""
    rows = []
    for (brief, direction), frame in k50s.groupby(["brief", "direction"], sort=True):
        values = dict(zip(frame["entity"], frame["log_k50"]))
        for a, b in itertools.combinations(sorted(values), 2):
            rows.append({"brief": brief, "direction": direction, "a": a, "b": b,
                         "gap": abs(values[a] - values[b])})
    return pd.DataFrame(rows, columns=["brief", "direction", "a", "b", "gap"])


def matched_real_gaps(k50s: pd.DataFrame, elo: dict[str, float], roles: dict) -> pd.DataFrame:
    """|gap| between entities adjacent in Elo within one role, per paraphrase and direction.

    ``roles`` is one line of the ``--roles`` YAML, ``{liked: [...], disliked: [...]}``.
    Pairs are formed inside each role and never across.
    """
    rows = []
    for (brief, direction), frame in k50s.groupby(["brief", "direction"], sort=True):
        values = dict(zip(frame["entity"], frame["log_k50"]))
        for role in ("liked", "disliked"):
            members = set(roles.get(role) or ())
            ranked = sorted((e for e in values if e in members and e in elo), key=lambda e: (-elo[e], e))
            for a, b in zip(ranked, ranked[1:]):
                rows.append({"brief": brief, "direction": direction, "role": role, "a": a, "b": b,
                             "elo_a": elo[a], "elo_b": elo[b], "gap": abs(values[a] - values[b])})
    return pd.DataFrame(rows, columns=["brief", "direction", "role", "a", "b", "elo_a", "elo_b", "gap"])


def threshold(neutral: pd.DataFrame, matched: pd.DataFrame | None, q: float = 95.0) -> dict:
    """95th percentile of each distribution (NaN gaps from censored k50s dropped).

    The threshold is the neutral-neutral percentile alone; ``matched_*`` is descriptive.
    """
    def pct(frame):
        if frame is None or frame.empty:
            return math.nan, 0
        gaps = frame["gap"].dropna()
        return (float(np.percentile(gaps, q)) if len(gaps) else math.nan), int(len(gaps))

    p_neutral, n_neutral = pct(neutral)
    p_matched, n_matched = pct(matched)
    return {
        "neutral_p95": p_neutral, "neutral_n": n_neutral,
        "threshold": p_neutral,
        "matched_p95": p_matched, "matched_n": n_matched, "matched_use": "descriptive",
    }


def pooled_slope(runs: pd.DataFrame, neutrals) -> float:
    frame = runs[runs["entity"].isin(list(neutrals)) & (runs["brief"] == "brief_00")]
    return fit_logistic(frame["k"], frame["public"]).slope


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Neutral-neutral and matched-real-pair k50 gap baselines.")
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--neutrals", required=True, help="comma-separated neutral entity keys")
    parser.add_argument("--midpoint-m", type=int, required=True, help="the midpoint m every neutral cell is cut to")
    parser.add_argument("--fit-cells", action="store_true",
                        help="fit any cell with 2+ m values on its own instead of cutting neutrals to the midpoint")
    parser.add_argument("--elo", type=Path, help="CSV model,entity,elo for the matched-real-pairs baseline")
    parser.add_argument("--roles", type=Path, help="YAML {model: {line: {liked: [...], disliked: [...]}}}; required with --elo")
    parser.add_argument("--line", default="primary", help="line of --roles naming the liked and disliked pools")
    parser.add_argument("--population", choices=("primary", "all"), default="primary")
    args = parser.parse_args(argv)
    if args.elo and not args.roles:
        parser.error("--elo needs --roles: matched-real pairs are formed within the liked and disliked pools")

    runs = load_runs(args.runs)
    if runs.empty:
        print(f"no graded runs under {args.runs}", file=sys.stderr)
        return 1
    runs = population(runs[runs["model"] == args.model], args.population)
    neutrals = [e.strip() for e in args.neutrals.split(",") if e.strip()]
    slope = pooled_slope(runs, neutrals)
    try:
        cells = runs if args.fit_cells else at_midpoint(runs, neutrals, args.midpoint_m)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    k50s = cell_k50s(cells, slope=slope)
    neutral = neutral_gaps(k50s[k50s["entity"].isin(neutrals)])
    matched = None
    if args.elo:
        table = pd.read_csv(args.elo)
        table = table[table["model"] == args.model]
        elo = dict(zip(table["entity"], table["elo"].astype(float)))
        roles = yaml.safe_load(args.roles.read_text(encoding="utf-8"))[args.model][args.line]
        real = k50s[~k50s["entity"].isin(neutrals)]
        matched = matched_real_gaps(real, elo, roles)
    with pd.option_context("display.width", 200):
        print(k50s.to_string(index=False))
        print(neutral.to_string(index=False))
        if matched is not None:
            print(matched.to_string(index=False))
    print({"model": args.model, "pooled_slope": slope, "midpoint_m": args.midpoint_m,
           "neutral_cells": "fit" if args.fit_cells else "fixed_slope_at_midpoint", **threshold(neutral, matched)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
