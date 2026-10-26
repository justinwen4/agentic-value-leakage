"""Curve fits recover a planted k50 shift on synthetic runs; no live calls."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis.fit_curves import fit_lapse, fit_logistic, gap, gap_table, k50_table, load_runs, m50, population
from analysis.noise_baseline import cell_k50s, matched_real_gaps, neutral_gaps, threshold

N = 1000
BASE = {"A": 0.842, "B": 0.765}
M_GRID = (8, 15, 30, 60, 120)
SLOPE = 2.0
# Neutral midpoint m50 = 30 at the mean of the two base rates.
LOG_K50 = math.log(30 / (N * 0.8035))
LIKED, DISLIKED = ("liked_a", "liked_b"), ("disliked_a", "disliked_b")


def simulate(log_k50s: dict[str, float], *, rng, n_per_m: int = 50, slope: float = SLOPE,
             direction: str = "inflated", lapse: tuple[float, float] = (0.0, 0.0)) -> pd.DataFrame:
    """Runs split 25/25 across base rates, k = m / (N p), Public ~ Bernoulli(logistic in log k)."""
    rows = []
    for entity, log_k50 in log_k50s.items():
        for m in M_GRID:
            for i in range(n_per_m):
                base_rate = "A" if i < n_per_m // 2 else "B"
                k = m / (N * BASE[base_rate])
                p = 1 / (1 + math.exp(-slope * (math.log(k) - log_k50)))
                p = lapse[0] + (1 - lapse[0] - lapse[1]) * p
                rows.append({"model": "fake", "entity": entity, "direction": direction, "m": m,
                             "base_rate": base_rate, "seed": i if base_rate == "A" else 100 + i, "k": k,
                             "brief": "brief_00", "prefill": "default:17", "action": "",
                             "public": bool(rng.random() < p), "check_passed": True, "leaked": False})
    frame = pd.DataFrame(rows)
    frame["action"] = np.where(frame["public"], "Public", "Quiet")
    return frame


def write_fixtures(root: Path, runs: pd.DataFrame) -> None:
    """grade.json + meta.json per run, in the harness run-directory layout."""
    for row in runs.itertuples():
        run = root / row.model / row.entity / row.direction / str(row.m) / str(row.seed)
        run.mkdir(parents=True)
        meta = {"model_name": row.model, "entity": row.entity, "direction": row.direction, "m": row.m,
                "base_rate": row.base_rate, "seed": row.seed, "k_achieved": row.k, "brief": row.brief,
                "prefill": {"path": "x", "steps": 17}, "leaked": False}
        grade = {"action": row.action, "public": row.public, "manipulation_check_passed": True,
                 "leaked": False, "judge": None}
        (run / "meta.json").write_text(json.dumps(meta))
        (run / "grade.json").write_text(json.dumps(grade))


def planted(shift: float) -> dict[str, float]:
    return {LIKED[0]: LOG_K50 + shift / 2, LIKED[1]: LOG_K50 + shift / 2,
            DISLIKED[0]: LOG_K50 - shift / 2, DISLIKED[1]: LOG_K50 - shift / 2}


@pytest.mark.parametrize("shift", [0.8, 0.0])
def test_gap_recovers_planted_shift_from_fixtures(tmp_path, shift):
    write_fixtures(tmp_path, simulate(planted(shift), rng=np.random.default_rng(7)))
    runs = population(load_runs(tmp_path), "primary")
    assert len(runs) == 4 * len(M_GRID) * 50
    result = gap(runs, LIKED, DISLIKED, n_boot=300, seed=1)
    # Per-entity SE of log k50 is about 1 / (slope * sqrt(sum n p (1 - p))) ~ 0.08, so the gap's is ~0.08.
    assert abs(result["gap"] - shift) < 0.25, result
    assert result["ci_low"] < shift < result["ci_high"], result
    assert not result["censored"]
    if shift == 0.0:
        assert result["ci_low"] < 0 < result["ci_high"]
    else:
        assert result["ci_low"] > 0


def test_gap_estimator_is_unbiased_across_simulations():
    rng = np.random.default_rng(11)
    estimates = [gap(simulate(planted(0.8), rng=rng), LIKED, DISLIKED, n_boot=0)["gap"] for _ in range(30)]
    mean, se = float(np.mean(estimates)), float(np.std(estimates, ddof=1) / math.sqrt(len(estimates)))
    assert abs(mean - 0.8) < 3 * se + 0.02, (mean, se)
    assert 0.03 < np.std(estimates) < 0.2


def test_k50_table_recovers_each_entity():
    runs = simulate(planted(0.8), rng=np.random.default_rng(3))
    table = k50_table(runs)
    for row in table.itertuples():
        assert abs(row.log_k50 - planted(0.8)[row.entity]) < 0.3
        assert abs(row.slope - SLOPE) < 0.8


def test_gap_table_reports_each_line_and_direction():
    rng = np.random.default_rng(5)
    runs = pd.concat([simulate(planted(0.8), rng=rng, direction="inflated"),
                      simulate(planted(-0.8), rng=rng, direction="understated")])
    roles = {"fake": {"primary": {"liked": list(LIKED), "disliked": list(DISLIKED)},
                      "without_own_developer": {"liked": [LIKED[1], LIKED[0]], "disliked": list(DISLIKED)}}}
    table = gap_table(runs, roles, n_boot=0)
    assert len(table) == 4
    by = {(r.line, r.direction): r.gap for r in table.itertuples()}
    assert by[("primary", "inflated")] > 0.5 and by[("primary", "understated")] < -0.5


def test_lapse_fit_recovers_k50_under_lapses():
    runs = simulate({"e": LOG_K50}, rng=np.random.default_rng(9), n_per_m=400, lapse=(0.1, 0.1))
    curve = fit_lapse(runs["k"], runs["public"])
    assert abs(curve.log_k50 - LOG_K50) < 0.15
    assert 0.03 < curve.lapse_low < 0.2 and 0.03 < curve.lapse_high < 0.2


def test_k50_outside_the_grid_is_censored_not_extrapolated():
    rng = np.random.default_rng(2)
    low = simulate({"e": math.log(0.002)}, rng=rng)
    high = simulate({"e": math.log(2.0)}, rng=rng)
    assert fit_logistic(low["k"], low["public"]).censored == "below"
    assert fit_logistic(high["k"], high["public"]).censored == "above"
    assert fit_logistic(high["k"], high["public"]).k50 is None
    flat = simulate({"e": LOG_K50}, rng=rng)
    assert fit_logistic(flat["k"], np.zeros(len(flat))).censored == "above"
    assert fit_logistic(flat["k"], np.ones(len(flat))).censored == "below"
    result = gap(pd.concat([simulate(planted(0.0), rng=rng).query("entity != 'liked_a'"),
                            low.assign(entity="liked_a")]), LIKED, DISLIKED, n_boot=20)
    assert result["censored"] and math.isnan(result["gap"])
    assert result["boot_clipped_share"] > 0


def test_population_drops_leaked_offcurve_and_failed_check():
    runs = simulate({"e": LOG_K50}, rng=np.random.default_rng(1), n_per_m=4)
    runs.loc[0, "leaked"] = True
    runs.loc[1, "action"] = "Incomplete"
    runs.loc[2, "action"] = "Ask"
    runs.loc[3, "check_passed"] = False
    assert len(population(runs, "primary")) == len(runs) - 4
    assert len(population(runs, "all")) == len(runs) - 3


def test_m50_and_pilot_grid():
    rng = np.random.default_rng(4)
    runs = pd.concat([simulate({"neutral": LOG_K50}, rng=rng, direction=d) for d in ("inflated", "understated")])
    result = m50(runs)
    assert 24 < result["m50"] < 37
    assert result["grid"] == sorted({round(result["m50"] * f) for f in (0.25, 0.5, 1, 2, 4)})


def test_neutral_gaps_and_threshold():
    k50s = pd.DataFrame([
        {"entity": f"n{i}", "brief": b, "direction": "inflated", "log_k50": 0.1 * i + (0.05 if b == "brief_01" else 0)}
        for i in range(6) for b in ("brief_00", "brief_01")
    ])
    gaps = neutral_gaps(k50s)
    assert len(gaps) == 2 * 15
    assert math.isclose(gaps["gap"].max(), 0.5)
    real = pd.DataFrame([{"entity": e, "brief": "brief_00", "direction": "inflated", "log_k50": v}
                         for e, v in (("a", 0.0), ("b", 0.9), ("c", 1.0))])
    matched = matched_real_gaps(real, {"a": 1700.0, "b": 1600.0, "c": 1650.0})
    assert list(zip(matched["a"], matched["b"])) == [("a", "c"), ("c", "b")]
    assert np.allclose(matched["gap"], [1.0, 0.1])
    result = threshold(gaps, matched)
    assert result["threshold"] == max(result["neutral_p95"], result["matched_p95"])
    assert result["neutral_n"] == 30 and result["matched_n"] == 2


def test_cell_k50s_single_k_uses_the_pooled_slope():
    rng = np.random.default_rng(6)
    true = {f"n{i}": LOG_K50 + 0.2 * (i - 2) for i in range(5)}
    runs = simulate(true, rng=rng, n_per_m=400).query("m == 30")
    k50s = cell_k50s(runs, slope=SLOPE)
    assert set(k50s["method"]) == {"fixed_slope"}
    for row in k50s.itertuples():
        assert abs(row.log_k50 - true[row.entity]) < 0.2
    with pytest.raises(ValueError):
        cell_k50s(runs, slope=None)
