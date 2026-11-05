"""The lab ceiling probe's fixed test (configs/ceiling_probe.yaml header).

    python -m analysis.ceiling_probe --runs runs

Per model and lab, Fisher's exact test on P(Public) in the inflated
direction: the lab's probe runs against the same model's Ambervale inflated
runs at every m of the midpoint sweep. One-sided (lab lower) for models
listed in ``ONE_SIDED``, two-sided otherwise; Holm across all tests. The
understated direction, directions pooled against every Ambervale run, and
the Ambervale m = 2 cell alone are printed alongside, untested. Primary
population (manipulation check passed, unleaked, on-curve), as in
``fit_curves``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml
from scipy.stats import fisher_exact

from analysis.fit_curves import load_runs, population

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
ONE_SIDED = {"claude-opus-4.8"}
ALPHA = 0.05


def _seeds(cfg: dict) -> set[int]:
    seeds = cfg["seeds"]
    return {int(s) for group in (seeds.values() if isinstance(seeds, dict) else [seeds]) for s in group}


def _cells(runs: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    keep = runs["m"].isin(cfg["m"]) & runs["seed"].isin(_seeds(cfg)) & (runs["brief"] == cfg["brief"])
    return runs[keep & runs["prefill"].str.startswith("default") & (runs["readme_variant"] == "none")]


def holm(pvalues: list[float]) -> list[float]:
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    adjusted, running = [0.0] * len(pvalues), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(pvalues) - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


def _row(model, lab, label, lab_runs, ref_runs, test: bool) -> dict:
    s, n = int(lab_runs["public"].sum()), len(lab_runs)
    rs, rn = int(ref_runs["public"].sum()), len(ref_runs)
    row = {"model": model, "lab": lab, "comparison": label, "public": s, "n": n,
           "p_public": s / n if n else float("nan"), "ref_public": rs, "ref_n": rn,
           "ref_p_public": rs / rn if rn else float("nan"), "p_value": float("nan"), "tested": test}
    if test and n and rn:
        alternative = "less" if model in ONE_SIDED else "two-sided"
        row["p_value"] = fisher_exact([[s, n - s], [rs, rn - rs]], alternative=alternative)[1]
        row["alternative"] = alternative
    return row


def probe_table(runs: pd.DataFrame, probe: dict, sweep: dict) -> pd.DataFrame:
    probe_runs = _cells(runs, probe)
    reference = _cells(runs, sweep)
    reference = reference[reference["entity"].isin(sweep["entities"])]
    labs = probe["entities"]
    rows = []
    for model in [m["name"] for m in probe["models"]]:
        ref = reference[reference["model"] == model]
        for lab in labs[model] if isinstance(labs, dict) else labs:
            mine = probe_runs[(probe_runs["model"] == model) & (probe_runs["entity"] == lab)]
            for direction in ("inflated", "understated"):
                rows.append(_row(model, lab, f"{direction} vs Ambervale {direction}, all m",
                                 mine[mine["direction"] == direction], ref[ref["direction"] == direction],
                                 test=direction == "inflated"))
            rows.append(_row(model, lab, "pooled vs Ambervale, all m", mine, ref, test=False))
            rows.append(_row(model, lab, "pooled vs Ambervale, m = 2", mine, ref[ref["m"] == 2], test=False))
    table = pd.DataFrame(rows)
    tested = table["tested"] & table["p_value"].notna()
    table.loc[tested, "p_holm"] = holm(table.loc[tested, "p_value"].tolist())
    return table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fixed test for the lab ceiling probe.")
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--probe", type=Path, default=_PROJECT_ROOT / "configs" / "ceiling_probe.yaml")
    parser.add_argument("--sweep", type=Path, default=_PROJECT_ROOT / "configs" / "midpoint_sweep.yaml")
    parser.add_argument("--out", type=Path, help="write the table as CSV")
    args = parser.parse_args(argv)
    runs = population(load_runs(args.runs), "primary")
    if runs.empty:
        print(f"no graded runs under {args.runs}", file=sys.stderr)
        return 1
    table = probe_table(runs, yaml.safe_load(args.probe.read_text()), yaml.safe_load(args.sweep.read_text()))
    if args.out:
        table.to_csv(args.out, index=False)
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(table.drop(columns=["tested"]).to_string(index=False, float_format=lambda v: f"{v:.3g}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
