"""S-curves of P(Public) against log k, and the liked-minus-disliked k50 shift.

    python -m analysis.fit_curves --runs runs [--roles roles.yaml] [--bootstrap 2000] [--midpoint]

Inputs are ``grade.json`` plus ``meta.json`` under ``--runs``; k is
``meta.k_achieved``, never the nominal m. Per docs/prereg.md (Analysis plan):

- **Curve.** P(Public) = 1 / (1 + exp(-slope * (log k - log k50))), fit by
  maximum likelihood on individual runs, per (model, entity, direction). The
  4-parameter lapse fit, P = g + (1 - g - l) * logistic(...), is a robustness
  line; its k50 is the k at which P = 0.5. A k50 outside the curve's k range
  is reported as censored below or above, not extrapolated.
- **Populations.** Leaked, Incomplete and Ask runs are dropped. Primary keeps
  runs that pass the manipulation check (deterministic, or the judge
  confirms the new headline); secondary keeps all. Nothing counts as not
  public.
- **Gap.** Per model and direction, the mean log k50 of the liked entities
  minus that of the disliked, in natural-log units of k. ``--roles`` names
  them per model and per line (e.g. ``primary``, ``without_own_developer``).
- **Intervals.** Bootstrap over runs, stratified by entity x direction x k x
  headline value, entities not resampled, 95% percentile intervals. Inside a
  resample a censored k50 is clipped to the grid edge; the share of
  resamples with any clipping is reported.

``--midpoint`` also fits each model's neutral curve in log m pooling both
directions and base rates (the midpoint sweep) and prints m50 with the
pilot grid ``round(m50 x {1/4, 1/2, 1, 2, 4})``.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.optimize import minimize

GRID_FACTORS = (0.25, 0.5, 1.0, 2.0, 4.0)
_SLOPE_CAP = 100.0
_OFF_CURVE = ("Incomplete", "Ask")


# ------------------------------------------------------------------------ data


def load_runs(runs_dir: Path) -> pd.DataFrame:
    """One row per graded run."""
    rows = []
    for grade_path in sorted(Path(runs_dir).rglob("grade.json")):
        meta_path = grade_path.parent / "meta.json"
        if not meta_path.is_file():
            continue
        grade = json.loads(grade_path.read_text(encoding="utf-8"))
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        judge = grade.get("judge") or {}
        prefill = meta.get("prefill")
        leaked = grade.get("leaked")
        if leaked is None:
            leaked = meta.get("leaked")
        rows.append({
            "run_dir": str(grade_path.parent),
            "model": meta["model_name"],
            "entity": meta["entity"],
            "direction": meta["direction"],
            "m": int(meta["m"]),
            "base_rate": str(meta["base_rate"]),
            "seed": int(meta["seed"]),
            "k": float(meta["k_achieved"]),
            "brief": meta.get("brief", "brief_00"),
            "prefill": "none" if not prefill else f"default:{prefill.get('steps')}",
            "action": grade["action"],
            "public": bool(grade["public"]),
            "check_passed": bool(grade["manipulation_check_passed"]) or judge.get("saw_new_headline") is True,
            "leaked": bool(leaked),
        })
    return pd.DataFrame(rows)


def population(runs: pd.DataFrame, which: str = "primary") -> pd.DataFrame:
    """``primary`` (manipulation check passed) or ``all``, on-curve and unleaked."""
    keep = ~runs["leaked"] & ~runs["action"].isin(_OFF_CURVE)
    if which == "primary":
        keep &= runs["check_passed"]
    elif which != "all":
        raise ValueError(f"unknown population {which!r}")
    return runs[keep]


# ------------------------------------------------------------------------ fits


@dataclass
class Curve:
    log_k50: float
    slope: float
    n: int
    log_k_min: float
    log_k_max: float
    lapse_low: float = 0.0
    lapse_high: float = 0.0
    converged: bool = True

    @property
    def censored(self) -> str | None:
        if math.isnan(self.log_k50) or self.slope <= 0:
            return "no_crossing"
        if self.log_k50 < self.log_k_min:
            return "below"
        if self.log_k50 > self.log_k_max:
            return "above"
        return None

    @property
    def k50(self) -> float | None:
        return None if self.censored else math.exp(self.log_k50)

    def clipped_log_k50(self) -> float:
        if math.isnan(self.log_k50) or self.slope <= 0:
            return self.log_k_max
        return min(max(self.log_k50, self.log_k_min), self.log_k_max)


def _counts(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ux, inv = np.unique(x, return_inverse=True)
    return ux, np.bincount(inv, weights=y), np.bincount(inv).astype(float)


def _newton(ux: np.ndarray, s: np.ndarray, n: np.ndarray) -> tuple[np.ndarray, bool]:
    """Binomial logistic regression of successes ``s`` of ``n`` on ``ux``."""
    beta = np.zeros(2)
    X = np.column_stack([np.ones_like(ux), ux])

    def nll(b):
        eta = X @ b
        return float(np.sum(n * np.logaddexp(0.0, eta) - s * eta))

    current = nll(beta)
    for _ in range(100):
        p = 1.0 / (1.0 + np.exp(-(X @ beta)))
        grad = X.T @ (s - n * p)
        hess = (X * (n * p * (1 - p))[:, None]).T @ X
        try:
            step = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            return beta, False
        t = 1.0
        while t > 1e-6:
            trial = beta + t * step
            value = nll(trial)
            if value <= current + 1e-12:
                break
            t /= 2
        else:
            return beta, False
        beta, previous, current = trial, current, value
        if abs(beta[1]) > _SLOPE_CAP:
            return beta, False
        if abs(previous - current) < 1e-10 and np.max(np.abs(t * step)) < 1e-8:
            return beta, True
    return beta, False


def _bounded(ux: np.ndarray, s: np.ndarray, n: np.ndarray) -> np.ndarray:
    """Fallback for separated data: MLE with |slope| capped."""
    X = np.column_stack([np.ones_like(ux), ux])

    def nll(b):
        eta = X @ b
        p = 1.0 / (1.0 + np.exp(-eta))
        return float(np.sum(n * np.logaddexp(0.0, eta) - s * eta)), X.T @ (n * p - s)

    res = minimize(nll, np.zeros(2), jac=True, method="L-BFGS-B",
                   bounds=[(None, None), (-_SLOPE_CAP, _SLOPE_CAP)])
    return res.x


def fit_logistic(k, public) -> Curve:
    """Two-parameter logistic in log k, maximum likelihood."""
    x = np.log(np.asarray(k, dtype=float))
    y = np.asarray(public, dtype=float)
    ux, s, n = _counts(x, y)
    if len(ux) < 2 or s.sum() in (0, n.sum()):
        level = "above" if s.sum() == 0 else "below"
        log_k50 = math.inf if level == "above" else -math.inf
        return Curve(log_k50, 1.0, int(n.sum()), float(x.min()), float(x.max()), converged=False)
    beta, ok = _newton(ux, s, n)
    if not ok:
        beta = _bounded(ux, s, n)
    b0, b1 = float(beta[0]), float(beta[1])
    log_k50 = -b0 / b1 if b1 != 0 else math.inf
    return Curve(log_k50, b1, int(n.sum()), float(x.min()), float(x.max()), converged=ok)


def fit_lapse(k, public, max_lapse: float = 0.49) -> Curve:
    """Four-parameter logistic with lower and upper lapse rates; k50 is where P = 0.5."""
    base = fit_logistic(k, public)
    x = np.log(np.asarray(k, dtype=float))
    y = np.asarray(public, dtype=float)
    ux, s, n = _counts(x, y)
    if len(ux) < 2:
        return base
    a0 = base.log_k50 if math.isfinite(base.log_k50) else float(np.median(ux))
    b0 = base.slope if base.slope > 0 else 1.0

    def nll(theta):
        a, b, g, l = theta
        p = g + (1 - g - l) / (1 + np.exp(-b * (ux - a)))
        p = np.clip(p, 1e-12, 1 - 1e-12)
        return -float(np.sum(s * np.log(p) + (n - s) * np.log(1 - p)))

    span = float(ux.max() - ux.min()) or 1.0
    res = minimize(
        nll, [a0, min(b0, _SLOPE_CAP), 0.02, 0.02], method="L-BFGS-B",
        bounds=[(ux.min() - 2 * span, ux.max() + 2 * span), (1e-3, _SLOPE_CAP), (0, max_lapse), (0, max_lapse)],
    )
    a, b, g, l = (float(v) for v in res.x)
    q = (0.5 - g) / (1 - g - l)
    if q <= 0:
        log_k50 = -math.inf
    elif q >= 1:
        log_k50 = math.inf
    else:
        log_k50 = a + math.log(q / (1 - q)) / b
    return Curve(log_k50, b, int(n.sum()), float(x.min()), float(x.max()), g, l, bool(res.success))


FITS = {"logistic": fit_logistic, "lapse": fit_lapse}


# ------------------------------------------------------------------------- k50


def k50_table(runs: pd.DataFrame, fit: str = "logistic", keys=("model", "entity", "direction", "brief", "prefill")) -> pd.DataFrame:
    rows = []
    for group, frame in runs.groupby(list(keys), sort=True):
        curve = FITS[fit](frame["k"], frame["public"])
        rows.append({
            **dict(zip(keys, group)),
            "fit": fit, "n": curve.n, "log_k50": curve.log_k50, "k50": curve.k50,
            "censored": curve.censored, "slope": curve.slope,
            "lapse_low": curve.lapse_low, "lapse_high": curve.lapse_high,
            "p_public": float(frame["public"].mean()),
        })
    return pd.DataFrame(rows)


def _gap_from(frame: pd.DataFrame, liked, disliked, fit: str, clip: bool) -> tuple[float, bool]:
    def value(entity):
        rows = frame[frame["entity"] == entity]
        if rows.empty:
            raise ValueError(f"no runs for entity {entity!r}")
        curve = FITS[fit](rows["k"], rows["public"])
        if curve.censored and not clip:
            return math.nan, True
        return (curve.clipped_log_k50() if clip else curve.log_k50), bool(curve.censored)

    liked_v = [value(e) for e in liked]
    disliked_v = [value(e) for e in disliked]
    censored = any(c for _, c in liked_v + disliked_v)
    gap = float(np.mean([v for v, _ in liked_v]) - np.mean([v for v, _ in disliked_v]))
    return gap, censored


def gap(runs: pd.DataFrame, liked, disliked, *, fit: str = "logistic", n_boot: int = 2000, seed: int = 0) -> dict:
    """Liked-minus-disliked mean log k50 for one model and direction, with a stratified bootstrap.

    ``runs`` holds one model, one direction, one population. The point
    estimate is NaN when any of the k50s is censored.
    """
    frame = runs[runs["entity"].isin(list(liked) + list(disliked))].reset_index(drop=True)
    estimate, censored = _gap_from(frame, liked, disliked, fit, clip=False)
    rng = np.random.default_rng(seed)
    strata = [idx.to_numpy() for _, idx in frame.groupby(["entity", "direction", "m", "base_rate"]).groups.items()]
    draws = []
    clipped = 0
    for _ in range(n_boot):
        pick = np.concatenate([rng.choice(idx, size=len(idx), replace=True) for idx in strata])
        value, was_clipped = _gap_from(frame.iloc[pick], liked, disliked, fit, clip=True)
        draws.append(value)
        clipped += was_clipped
    lo, hi = (np.percentile(draws, [2.5, 97.5]) if draws else (math.nan, math.nan))
    return {
        "gap": estimate, "censored": censored, "ci_low": float(lo), "ci_high": float(hi),
        "n_boot": n_boot, "boot_clipped_share": clipped / n_boot if n_boot else 0.0,
        "ratio": math.exp(estimate) if math.isfinite(estimate) else math.nan,
    }


def gap_table(runs: pd.DataFrame, roles: dict, *, fit: str = "logistic", n_boot: int = 2000) -> pd.DataFrame:
    """Every model x line x direction in ``roles``: ``{model: {line: {liked: [...], disliked: [...]}}}``."""
    rows = []
    for model, lines in roles.items():
        for line, spec in lines.items():
            for direction in sorted(runs["direction"].unique()):
                frame = runs[(runs["model"] == model) & (runs["direction"] == direction) & (runs["brief"] == "brief_00")]
                if frame.empty:
                    continue
                result = gap(frame, spec["liked"], spec["disliked"], fit=fit, n_boot=n_boot)
                rows.append({"model": model, "line": line, "direction": direction, "fit": fit, **result})
    return pd.DataFrame(rows)


# -------------------------------------------------------------------- midpoint


def m50(runs: pd.DataFrame) -> dict:
    """Neutral midpoint in whole flips, pooling directions and base rates."""
    curve = fit_logistic(runs["m"].astype(float), runs["public"])
    value = math.exp(curve.log_k50) if not curve.censored else None
    grid = sorted({max(1, round(value * f)) for f in GRID_FACTORS}) if value else None
    return {"m50": value, "censored": curve.censored, "slope": curve.slope, "n": curve.n, "grid": grid}


# ------------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fit P(Public) curves and the liked-disliked k50 shift.")
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--roles", type=Path, help="YAML {model: {line: {liked: [...], disliked: [...]}}}")
    parser.add_argument("--population", choices=("primary", "all"), default="primary")
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--midpoint", action="store_true", help="print m50 and the pilot grid per model")
    parser.add_argument("--out", type=Path, help="directory for k50.csv and gaps.csv")
    args = parser.parse_args(argv)

    runs = load_runs(args.runs)
    if runs.empty:
        print(f"no graded runs under {args.runs}", file=sys.stderr)
        return 1
    pop = population(runs, args.population)
    print(f"{len(runs)} graded runs, {len(pop)} in the {args.population} population")
    tables = [k50_table(pop, fit) for fit in FITS]
    k50s = pd.concat(tables, ignore_index=True)
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(k50s.to_string(index=False))
    if args.midpoint:
        for model, frame in pop.groupby("model"):
            print(f"midpoint {model}: {m50(frame)}")
    gaps = None
    if args.roles:
        roles = yaml.safe_load(args.roles.read_text(encoding="utf-8"))
        gaps = pd.concat([gap_table(pop, roles, fit=fit, n_boot=args.bootstrap) for fit in FITS], ignore_index=True)
        with pd.option_context("display.width", 200, "display.max_columns", 20):
            print(gaps.to_string(index=False))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        k50s.to_csv(args.out / "k50.csv", index=False)
        if gaps is not None:
            gaps.to_csv(args.out / "gaps.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
