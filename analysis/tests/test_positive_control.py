"""Positive control recovers a planted variant difference from synthetic run directories."""
from __future__ import annotations

import json

import pytest

from analysis.positive_control import arm_table, diff_table, load_variant_runs, main, wilson
from analysis.fit_curves import population

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

    runs = population(load_variant_runs(tmp_path), "primary")
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
