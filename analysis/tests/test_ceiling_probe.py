"""Ceiling probe test finds a planted drop for one lab and none for another."""
from __future__ import annotations

import json

import pytest
from scipy.stats import fisher_exact

from analysis.ceiling_probe import holm, main, probe_table
from analysis.fit_curves import load_runs, population

SWEEP = {"models": [{"name": "opus"}], "entities": ["ambervale"], "m": [2, 128],
         "seeds": {"A": [0, 1], "B": [100, 101]}, "brief": "brief_00"}
PROBE = {"models": [{"name": "opus"}], "entities": {"opus": ["liked", "disliked"]}, "m": [2],
         "seeds": {"A": [30000, 30001, 30002, 30003, 30004], "B": [30100, 30101, 30102, 30103, 30104]},
         "brief": "brief_00"}


def _write(root, *, entity, direction, m, seed, public):
    run = root / "opus" / entity / direction / str(m) / str(seed)
    run.mkdir(parents=True)
    meta = {"model_name": "opus", "entity": entity, "direction": direction, "m": m, "base_rate": "A",
            "seed": seed, "k_achieved": m / 842, "brief": "brief_00", "prefill": {"path": "x", "steps": 17}}
    grade = {"action": "Both" if public else "Quiet", "public": public, "manipulation_check_passed": True,
             "leaked": False, "judge": None}
    (run / "meta.json").write_text(json.dumps(meta))
    (run / "grade.json").write_text(json.dumps(grade))


def _fixture(root):
    for direction in ("inflated", "understated"):
        for m in SWEEP["m"]:
            for seed in [0, 1, 100, 101]:
                _write(root, entity="ambervale", direction=direction, m=m, seed=seed, public=True)
        for i, seed in enumerate(PROBE["seeds"]["A"] + PROBE["seeds"]["B"]):
            _write(root, entity="liked", direction=direction, m=2, seed=seed,
                   public=not (direction == "inflated" and i < 5))
            _write(root, entity="disliked", direction=direction, m=2, seed=seed, public=True)
    _write(root, entity="ambervale", direction="inflated", m=2, seed=999, public=False)  # not a sweep seed


def test_planted_drop(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("analysis.ceiling_probe.ONE_SIDED", {"opus"})
    _fixture(tmp_path)
    table = probe_table(population(load_runs(tmp_path), "primary"), PROBE, SWEEP).set_index(["lab", "comparison"])
    liked = table.loc[("liked", "inflated vs Ambervale inflated, all m")]
    assert (liked["public"], liked["n"], liked["ref_public"], liked["ref_n"]) == (5, 10, 8, 8)
    assert liked["p_value"] == pytest.approx(fisher_exact([[5, 5], [8, 0]], alternative="less")[1])
    assert liked["p_value"] < 0.05
    disliked = table.loc[("disliked", "inflated vs Ambervale inflated, all m")]
    assert disliked["p_value"] == 1.0
    assert table.loc[("liked", "pooled vs Ambervale, m = 2"), "ref_n"] == 8
    assert table["p_holm"].notna().sum() == 2
    assert main(["--runs", str(tmp_path), "--probe", str(_cfg(tmp_path, "p", PROBE)),
                 "--sweep", str(_cfg(tmp_path, "s", SWEEP))]) == 0
    assert "liked" in capsys.readouterr().out


def _cfg(root, name, cfg):
    path = root / f"{name}.yaml"
    path.write_text(json.dumps(cfg))
    return path


def test_holm():
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
