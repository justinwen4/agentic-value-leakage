"""Ladder table reads each rung's own cells and picks the lowest rung that passes for every model."""
from __future__ import annotations

import json

import pandas as pd

from analysis.fit_curves import load_runs, population
from analysis.ladder import chosen_rung, ladder_table, main

SWEEP = {"brief": "brief_00", "seeds": {"A": [0, 1, 2, 3, 4], "B": [100, 101, 102, 103, 104]}}
LADDER = {
    "models": [{"name": "a"}, {"name": "b"}],
    "entities": ["ambervale"],
    "arms": [
        {"name": "rung1", "brief": "brief_minor", "seeds": {"A": [40000, 40001, 40002, 40003, 40004],
                                                           "B": [40100, 40101, 40102, 40103, 40104]}},
        {"name": "rung2", "readme_variant": "size_note", "seeds": {"A": [41000, 41001, 41002, 41003, 41004],
                                                                   "B": [41100, 41101, 41102, 41103, 41104]}},
    ],
}
# public share per (rung, model, m), 10 runs per cell
PLAN = {
    ("rung0", "a", 2): 1.0, ("rung0", "a", 128): 1.0, ("rung0", "b", 2): 0.9, ("rung0", "b", 128): 0.9,
    ("rung1", "a", 2): 0.5, ("rung1", "a", 128): 1.0, ("rung1", "b", 2): 0.8, ("rung1", "b", 128): 0.9,
    ("rung2", "a", 2): 0.3, ("rung2", "a", 128): 0.9, ("rung2", "b", 2): 0.6, ("rung2", "b", 128): 0.9,
}


def _write(root, rung, model, m, seed, public, **meta_extra):
    run = root / model / "ambervale" / "inflated" / str(m) / str(seed)
    run.mkdir(parents=True)
    meta = {"model_name": model, "entity": "ambervale", "direction": "inflated", "m": m, "base_rate": "A",
            "seed": seed, "k_achieved": m / 842, "brief": "brief_00", "prefill": {"path": "x", "steps": 17},
            "arm": None if rung == "rung0" else rung, **meta_extra}
    grade = {"action": "Both" if public else "Quiet", "public": public, "manipulation_check_passed": True,
             "leaked": False, "judge": None}
    (run / "meta.json").write_text(json.dumps(meta))
    (run / "grade.json").write_text(json.dumps(grade))


def _fixture(root):
    extras = {"rung0": {}, "rung1": {"brief": "brief_minor"}, "rung2": {"readme_variant": "size_note"}}
    seeds = {"rung0": SWEEP["seeds"], **{a["name"]: a["seeds"] for a in LADDER["arms"]}}
    for (rung, model, m), share in PLAN.items():
        all_seeds = seeds[rung]["A"] + seeds[rung]["B"]
        for i, seed in enumerate(all_seeds):
            _write(root, rung, model, m, seed, i < round(share * len(all_seeds)), **extras[rung])
    # Same m, other configs' seeds or variants: must not count anywhere.
    _write(root, "rung0", "a", 2, 3000, False, readme_variant="prefer_quiet", arm="prefer_quiet")
    _write(root, "rung0", "a", 2, 9, False)


def test_table_and_choice(tmp_path, capsys):
    _fixture(tmp_path)
    runs = population(load_runs(tmp_path), "primary", include_variants=True)
    table = ladder_table(runs, LADDER, SWEEP).set_index(["rung", "model"])
    assert table.loc[("rung0", "a"), "n2"] == 10 and table.loc[("rung0", "a"), "p2"] == 1.0
    assert table.loc[("rung1", "a"), "passes"] and not table.loc[("rung1", "b"), "passes"]
    assert table.loc[("rung2", "a"), "passes"] and table.loc[("rung2", "b"), "passes"]
    assert chosen_rung(table.reset_index()) == "rung2"

    ladder_path, sweep_path = tmp_path / "l.yaml", tmp_path / "s.yaml"
    ladder_path.write_text(json.dumps(LADDER))
    sweep_path.write_text(json.dumps(SWEEP))
    assert main(["--runs", str(tmp_path), "--ladder", str(ladder_path), "--sweep", str(sweep_path)]) == 0
    assert "chosen rung: rung2" in capsys.readouterr().out


def test_boundaries_count_as_passing():
    from analysis.ladder import MAX_P2, MIN_GAP
    runs = pd.DataFrame({"model": ["a"] * 20, "m": [2] * 10 + [128] * 10, "entity": "ambervale",
                         "brief": "brief_00", "readme_variant": "none", "log_history": "none", "arm": None,
                         "seed": SWEEP["seeds"]["A"] * 2 + SWEEP["seeds"]["B"] * 2,
                         "public": [True] * 4 + [False] * 6 + [True] * 7 + [False] * 3})
    table = ladder_table(runs, {**LADDER, "models": [{"name": "a"}], "arms": []}, SWEEP)
    row = table.iloc[0]
    assert (row["p2"], row["p128"]) == (0.4, 0.7) and row["p2"] <= MAX_P2 and row["gap"] < MIN_GAP
    assert row["passes"]


def test_no_rung_for_everyone():
    table = pd.DataFrame({"rung": ["rung0", "rung1"], "model": ["a", "a"], "passes": [False, False]})
    assert chosen_rung(table) is None
