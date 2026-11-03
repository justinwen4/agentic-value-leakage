"""Figures for the midpoint sweep: P(Public) against the headline shift per model.

    python -m analysis.plot_midpoint --runs runs --out runs/figures/midpoint

Reads the sweep cells (configs/midpoint_sweep.yaml: neutral entity, brief_00,
default prefix, plain README) through ``fit_curves.load_runs`` and the
primary population. The x axis is the shift in percentage points, m / 10,
since one flip moves the headline by 1/N = 0.1 pp at either base rate.
Intervals are Wilson 95%. Writes three PNGs and ``midpoint_counts.csv``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from analysis.fit_curves import load_runs, population
from analysis.positive_control import wilson

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SWEEP = _PROJECT_ROOT / "configs" / "midpoint_sweep.yaml"

MODEL_LABELS = {
    "claude-opus-4.8": "Claude Opus 4.8",
    "gpt-5.5": "GPT-5.5",
    "gemini-3.1-pro": "Gemini 3.1 Pro",
}
# Categorical slots 1-3 of the reference palette (valid for all pairs).
MODEL_COLORS = {"claude-opus-4.8": "#2a78d6", "gpt-5.5": "#eb6834", "gemini-3.1-pro": "#1baf7a"}
ACTIONS = ["Both", "Public", "Quiet", "Nothing", "Incomplete", "Ask"]
ACTION_LABELS = {
    "Both": "NOTES + CORRECTIONS",
    "Public": "CORRECTIONS only",
    "Quiet": "NOTES only",
    "Nothing": "Neither file",
    "Incomplete": "Test still failing",
    "Ask": "Ask",
}
# Public actions in blues, the rest in warm and gray steps, so the split reads at a glance.
ACTION_COLORS = {
    "Both": "#1f5fae", "Public": "#7fb0ea", "Quiet": "#eb6834",
    "Nothing": "#f3b08f", "Incomplete": "#9a9893", "Ask": "#cfcdc6",
}
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def sweep_runs(runs_dir: Path, sweep: dict) -> pd.DataFrame:
    """Graded runs that are cells of the sweep config, run folders directly under ``runs_dir``."""
    runs = load_runs(runs_dir)
    if runs.empty:
        return runs
    seeds = sweep["seeds"]
    seed_set = {int(s) for v in (seeds.values() if isinstance(seeds, dict) else [seeds]) for s in v}
    models = [m["name"] for m in sweep["models"]]
    top = runs["run_dir"].map(lambda p: Path(p).relative_to(runs_dir).parts[0])
    keep = (
        top.isin(models) & runs["model"].isin(models)
        & runs["entity"].isin(sweep["entities"]) & runs["m"].isin(sweep["m"])
        & runs["seed"].isin(seed_set) & (runs["brief"] == sweep["brief"])
        & runs["prefill"].str.startswith("default") & (runs["readme_variant"] == "none")
    )
    return runs[keep].copy()


def counts(runs: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    grouped = runs.groupby(keys)["public"].agg(n="size", public="sum").reset_index()
    ci = [wilson(int(s), int(n)) for s, n in zip(grouped["public"], grouped["n"])]
    grouped["p_public"] = grouped["public"] / grouped["n"]
    grouped["ci_low"] = [max(0.0, c[0]) for c in ci]
    grouped["ci_high"] = [min(1.0, c[1]) for c in ci]
    grouped["shift_pp"] = grouped["m"] / 10
    return grouped


def _style(ax, grid_m: list[int]) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_xscale("log", base=2)
    ticks = [m / 10 for m in grid_m]
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{t:g}" for t in ticks])
    ax.minorticks_off()
    ax.set_ylim(-0.03, 1.08)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=9, length=0, pad=6)
    ax.axhline(0.5, color=INK_2, linewidth=1, linestyle=(0, (3, 3)), zorder=1)


def _curves(ax, table: pd.DataFrame, models: list[str], grid_m: list[int], labels: bool) -> None:
    _style(ax, grid_m)
    offsets = np.linspace(-0.06, 0.06, len(models))  # dodge in log2 units so overlapping lines stay visible
    for model, dx in zip(models, offsets):
        rows = table[table["model"] == model].sort_values("m")
        if rows.empty:
            continue
        x = rows["shift_pp"].to_numpy() * 2 ** dx
        y = rows["p_public"].to_numpy()
        err = np.clip(np.vstack([y - rows["ci_low"].to_numpy(), rows["ci_high"].to_numpy() - y]), 0, None)
        color = MODEL_COLORS.get(model, INK_2)
        ax.errorbar(x, y, yerr=err, color=color, linewidth=2, elinewidth=1.2, capsize=0,
                    marker="o", markersize=7, markeredgecolor=SURFACE, markeredgewidth=1.5,
                    label=MODEL_LABELS.get(model, model), zorder=3)
    ax.text(grid_m[0] / 10 * 1.15, 0.47, "50%: the m50 the sweep looks for", color=INK_2, fontsize=8, va="top")
    if labels:
        ax.set_xlabel("Headline shift from the fix (percentage points, log scale)", color=INK_2, fontsize=9)
        ax.set_ylabel("P(public): CORRECTIONS.md edited", color=INK_2, fontsize=9)


def _legend(fig, models: list[str]) -> None:
    handles = [plt.Line2D([], [], color=MODEL_COLORS.get(m, INK_2), marker="o", linewidth=2, markersize=7)
               for m in models]
    fig.legend(handles, [MODEL_LABELS.get(m, m) for m in models], loc="upper right", frameon=False,
               ncol=len(models), fontsize=9, labelcolor=INK, bbox_to_anchor=(0.98, 0.88))


def _title(fig, title: str, subtitle: str) -> None:
    fig.text(0.02, 0.975, title, fontsize=12.5, fontweight="bold", color=INK, va="top")
    fig.text(0.02, 0.925, subtitle, fontsize=9, color=INK_2, va="top")


def plot_pooled(runs: pd.DataFrame, models: list[str], grid_m: list[int], out: Path) -> pd.DataFrame:
    table = counts(runs, ["model", "m"])
    fig, ax = plt.subplots(figsize=(8, 4.8), facecolor=SURFACE)
    fig.subplots_adjust(top=0.78, bottom=0.13, left=0.1, right=0.97)
    _curves(ax, table, models, grid_m, labels=True)
    n = int(table["n"].median()) if not table.empty else 0
    _title(fig, "P(public) by headline shift, neutral lab (Ambervale)",
           f"Both directions and base rates pooled, about {n} runs per point; bars are Wilson 95% intervals")
    _legend(fig, models)
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return table


def plot_by_direction(runs: pd.DataFrame, models: list[str], grid_m: list[int], out: Path) -> pd.DataFrame:
    table = counts(runs, ["model", "direction", "m"])
    directions = [d for d in ("inflated", "understated") if d in set(table["direction"])]
    fig, axes = plt.subplots(1, len(directions), figsize=(11, 4.6), sharey=True, facecolor=SURFACE, squeeze=False)
    fig.subplots_adjust(top=0.74, bottom=0.15, left=0.07, right=0.98, wspace=0.08)
    meaning = {"inflated": "fix lowers the published number", "understated": "fix raises the published number"}
    for ax, direction in zip(axes[0], directions):
        _curves(ax, table[table["direction"] == direction], models, grid_m, labels=False)
        ax.set_title(f"{direction.capitalize()}: {meaning[direction]}", fontsize=10, color=INK, loc="left", pad=8)
        ax.set_xlabel("Headline shift (pp, log scale)", color=INK_2, fontsize=9)
    axes[0][0].set_ylabel("P(public)", color=INK_2, fontsize=9)
    n = int(table["n"].median()) if not table.empty else 0
    _title(fig, "P(public) by headline shift, split by direction",
           f"About {n} runs per point (base rates A and B pooled); Wilson 95% intervals")
    _legend(fig, models)
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return table


def plot_actions(runs: pd.DataFrame, models: list[str], grid_m: list[int], out: Path) -> pd.DataFrame:
    """Share of each action code per model and m, from all graded runs (Incomplete and Ask kept)."""
    share = (runs.groupby(["model", "m"])["action"].value_counts(normalize=True)
             .unstack(fill_value=0.0).reindex(columns=ACTIONS, fill_value=0.0))
    present = [a for a in ACTIONS if share[a].sum() > 0]
    fig, axes = plt.subplots(1, len(models), figsize=(11, 4.2), sharey=True, facecolor=SURFACE, squeeze=False)
    fig.subplots_adjust(top=0.72, bottom=0.15, left=0.07, right=0.98, wspace=0.08)
    for ax, model in zip(axes[0], models):
        ax.set_facecolor(SURFACE)
        rows = share.loc[model] if model in share.index.get_level_values(0) else None
        xs = np.arange(len(grid_m))
        bottom = np.zeros(len(grid_m))
        for action in present:
            vals = np.array([rows.loc[m, action] if rows is not None and m in rows.index else 0.0 for m in grid_m])
            ax.bar(xs, vals, bottom=bottom, width=0.72, color=ACTION_COLORS[action],
                   edgecolor=SURFACE, linewidth=1.5, label=ACTION_LABELS[action])
            bottom += vals
        ax.set_xticks(xs)
        ax.set_xticklabels([f"{m / 10:g}" for m in grid_m])
        ax.set_title(MODEL_LABELS.get(model, model), fontsize=10, color=INK, loc="left", pad=8)
        ax.set_xlabel("Headline shift (pp)", color=INK_2, fontsize=9)
        ax.set_ylim(0, 1)
        ax.set_yticks([0, 0.5, 1.0])
        ax.set_yticklabels(["0%", "50%", "100%"])
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=INK_2, labelsize=9, length=0, pad=6)
    axes[0][0].set_ylabel("Share of runs", color=INK_2, fontsize=9)
    _title(fig, "Which log files each run edited",
           "All graded sweep runs; public = CORRECTIONS.md edited (blues)")
    handles = [plt.Rectangle((0, 0), 1, 1, color=ACTION_COLORS[a]) for a in present]
    fig.legend(handles, [ACTION_LABELS[a] for a in present], loc="upper right", frameon=False,
               ncol=len(present), fontsize=9, labelcolor=INK, bbox_to_anchor=(0.98, 0.88))
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return share.reset_index()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plot P(Public) against headline shift for the midpoint sweep.")
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--config", type=Path, default=_SWEEP)
    parser.add_argument("--out", type=Path, default=Path("runs/figures/midpoint"))
    args = parser.parse_args(argv)

    sweep = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    every = sweep_runs(args.runs, sweep)
    if every.empty:
        print(f"no graded sweep runs under {args.runs}", file=sys.stderr)
        return 1
    models = [m["name"] for m in sweep["models"] if m["name"] in set(every["model"])]
    grid_m = sorted(int(m) for m in sweep["m"])
    primary = population(every, "primary")
    args.out.mkdir(parents=True, exist_ok=True)

    pooled = plot_pooled(primary, models, grid_m, args.out / "p_public_by_shift.png")
    split = plot_by_direction(primary, models, grid_m, args.out / "p_public_by_shift_direction.png")
    plot_actions(every, models, grid_m, args.out / "actions_by_shift.png")
    split.assign(pooled=False).pipe(lambda d: pd.concat([pooled.assign(direction="pooled", pooled=True), d])) \
        .to_csv(args.out / "midpoint_counts.csv", index=False)

    dropped = every.groupby("model").size() - primary.groupby("model").size().reindex(models, fill_value=0)
    for model in models:
        rows = pooled[pooled["model"] == model]
        print(f"{model}: {int(rows['n'].sum())} primary runs ({int(dropped.get(model, 0))} dropped), "
              f"P(public) by m: " + ", ".join(f"{m}={p:.2f}" for m, p in zip(rows["m"], rows["p_public"])))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
