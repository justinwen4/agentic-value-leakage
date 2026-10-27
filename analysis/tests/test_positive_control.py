"""Positive control recovers a planted variant difference; every other analysis ignores variant runs."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from analysis.fit_curves import k50_table, load_runs, m50, population
from analysis.positive_control import arm_table, control_runs, diff_table, main, wilson

from .test_curves import LOG_K50, simulate, write_fixtures

P_PUBLIC = {"prefer_quiet": 0.25, "must_correct": 0.75}


def test_planted_difference_from_fixtures(tmp_path, capsys):
    seeds = {("prefer_quiet", "A"): 3000, ("prefer_quiet", "B"): 3100,
             ("must_correct", "A"): 4000, ("must_correct", "B"): 4100}
    for (variant, base_rate), start in seeds.items():
        for direction in ("inflated", "understated"):
            for i in range(25):
                run = tmp_path / "fake" / "ambervale" / direction / "16" / str(start + i)
                run.mkdir(parents=True)
                public = i <= P_PUBLIC[variant] * 24  # exactly 6 or 18 of runs 1..24
                action = "Public" if public else "Quiet"
                if i == 0:
                    action, public = "Incomplete", False  # dropped from both populations
                meta = {"model_name": "fake", "entity": "ambervale", "direction": direction, "m": 16,
                        "base_rate": base_rate, "seed": start + i, "k_achieved": 0.02, "brief": "brief_00",
                        "prefill": {"path": "x", "steps": 17}, "leaked": False, "readme_variant": variant}
                grade = {"action": action, "public": public, "manipulation_check_passed": True,
                         "leaked": False, "judge": None}
                (run / "meta.json").write_text(json.dumps(meta))
                (run / "grade.json").write_text(json.dumps(grade))

    runs = control_runs(load_runs(tmp_path), "fake")
    assert len(runs) == 2 * 2 * 2 * 24

    arms = arm_table(runs).set_index(["variant", "direction"])
    assert set(arms.index.get_level_values("direction")) == {"inflated", "understated", "both"}
    assert arms.loc[("must_correct", "both"), "n"] == 96
    for variant, p in P_PUBLIC.items():
        row = arms.loc[(variant, "both")]
        assert row["p_public"] == p
        assert (row["ci_low"], row["ci_high"]) == pytest.approx(wilson(round(96 * p), 96))
    assert wilson(10, 20) == pytest.approx((0.2993, 0.7007), abs=1e-4)

    diffs = diff_table(runs, n_boot=500).set_index("direction")
    for direction in ("inflated", "understated", "both"):
        row = diffs.loc[direction]
        assert row["diff"] == pytest.approx(0.5)
        assert row["ci_low"] < 0.5 < row["ci_high"]
        assert not row["includes_zero"]
        assert row["ci_low"] > 0.3

    assert main(["--runs", str(tmp_path), "--model", "fake", "--bootstrap", "200"]) == 0
    assert "must_correct - prefer_quiet" in capsys.readouterr().out


def test_variant_runs_are_excluded_from_curves_and_kept_by_positive_control(tmp_path):
    rng = np.random.default_rng(12)
    ordinary = pd.concat([simulate({"ambervale": LOG_K50}, rng=rng, n_per_m=20, direction=d)
                          for d in ("inflated", "understated")])
    write_fixtures(tmp_path / "plain", ordinary)
    write_fixtures(tmp_path / "mixed", ordinary)
    # Same model, entity, direction and m as ordinary runs, other seeds: all Public
    # under must_correct, all Quiet under prefer_quiet, enough to move any curve they join.
    for variant, start, public in (("must_correct", 4000, True), ("prefer_quiet", 3000, False)):
        for seed in range(start, start + 20):
            run = tmp_path / "mixed" / "fake" / "ambervale" / "inflated" / "8" / str(seed)
            run.mkdir(parents=True)
            meta = {"model_name": "fake", "entity": "ambervale", "direction": "inflated", "m": 8,
                    "base_rate": "A", "seed": seed, "k_achieved": 8 / 842, "brief": "brief_00",
                    "prefill": {"path": "x", "steps": 17}, "leaked": False,
                    "readme_variant": variant, "arm": variant}
            grade = {"action": "Public" if public else "Quiet", "public": public,
                     "manipulation_check_passed": True, "leaked": False, "judge": None}
            (run / "meta.json").write_text(json.dumps(meta))
            (run / "grade.json").write_text(json.dumps(grade))

    plain, mixed = load_runs(tmp_path / "plain"), load_runs(tmp_path / "mixed")
    assert set(plain["readme_variant"]) == {"none"} and plain["arm"].isna().all()
    assert mixed["readme_variant"].value_counts().to_dict() == {"none": len(ordinary), "must_correct": 20,
                                                                "prefer_quiet": 20}
    assert set(mixed.loc[mixed["readme_variant"] != "none", "arm"]) == {"must_correct", "prefer_quiet"}

    pd.testing.assert_frame_equal(k50_table(population(mixed)), k50_table(population(plain)))
    assert m50(population(mixed)) == m50(population(plain))
    with_variants = k50_table(population(mixed, include_variants=True))
    assert with_variants["n"].sum() == len(ordinary) + 40
    assert m50(population(mixed, include_variants=True)) != m50(population(plain))

    control = control_runs(mixed, "fake")
    assert len(control) == 40 and set(control["readme_variant"]) == {"must_correct", "prefer_quiet"}
    arms = arm_table(control).set_index(["variant", "direction"])
    assert arms.loc[("must_correct", "both"), "n"] == 20 and arms.loc[("must_correct", "both"), "p_public"] == 1.0
    assert arms.loc[("prefer_quiet", "both"), "n"] == 20 and arms.loc[("prefer_quiet", "both"), "p_public"] == 0.0
