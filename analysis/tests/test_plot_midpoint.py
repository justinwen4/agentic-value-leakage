"""Midpoint figures read only sweep cells and count P(Public) per model and m."""
from __future__ import annotations

import json

import pandas as pd
import pytest
import yaml

from analysis.plot_midpoint import main

SWEEP = {
    "models": [{"name": "fake"}],
    "entities": ["ambervale"],
    "m": [2, 128],
    "seeds": {"A": [0, 1, 2, 3], "B": [100, 101, 102, 103]},
    "brief": "brief_00",
}


def _write(root, *, m, seed, base_rate, direction, action, entity="ambervale"):
    run = root / "fake" / entity / direction / str(m) / str(seed)
    run.mkdir(parents=True)
    meta = {"model_name": "fake", "entity": entity, "direction": direction, "m": m, "base_rate": base_rate,
            "seed": seed, "k_achieved": m / 842, "brief": "brief_00", "prefill": {"path": "x", "steps": 17}}
    public = action in ("Public", "Both")
    det = {"corrections_modified": public, "notes_modified": action in ("Both", "Quiet"),
           "published_number_edited": public}
    grade = {"action": action, "public": public, "manipulation_check_passed": True,
             "leaked": False, "judge": None, "deterministic": det}
    say = "Logged for downstream users." if public else "A minor fix."
    events = [{"role": "assistant", "prefill": True, "content": "downstream", "tool_calls": None},
              {"role": "assistant", "prefill": False, "content": say,
               "tool_calls": [{"id": "c0", "name": "bash", "args": {"cmd": "git commit -am x"}}] if m == 128 else None}]
    (run / "meta.json").write_text(json.dumps(meta))
    (run / "grade.json").write_text(json.dumps(grade))
    (run / "trajectory.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (run / "diff.patch").write_text("diff --git a/pyproject.toml b/pyproject.toml\n" if public else "")
    (run / "final_message.txt").write_text("Done.\n")


def test_counts_and_figures(tmp_path, capsys):
    runs = tmp_path / "runs"
    for direction in ("inflated", "understated"):
        for base_rate, seeds in SWEEP["seeds"].items():
            for i, seed in enumerate(seeds):
                _write(runs, m=2, seed=seed, base_rate=base_rate, direction=direction,
                       action="Quiet" if i == 0 else "Both")
                _write(runs, m=128, seed=seed, base_rate=base_rate, direction=direction, action="Public")
    _write(runs, m=2, seed=999, base_rate="A", direction="inflated", action="Quiet")  # seed outside the sweep
    _write(runs, m=2, seed=0, base_rate="A", direction="inflated", action="Quiet", entity="other")
    _write(runs, m=2, seed=1, base_rate="A", direction="understated", action="Incomplete", entity="other")
    config = tmp_path / "sweep.yaml"
    config.write_text(yaml.safe_dump(SWEEP))
    out = tmp_path / "figs"

    assert main(["--runs", str(runs), "--config", str(config), "--out", str(out)]) == 0
    for name in ("p_public_by_shift.png", "p_public_by_shift_direction.png", "actions_by_shift.png",
                 "behaviour_by_model.png"):
        assert (out / name).stat().st_size > 0

    table = pd.read_csv(out / "midpoint_counts.csv")
    pooled = table[table["direction"] == "pooled"].set_index("m")
    assert pooled.loc[2, "n"] == 16 and pooled.loc[2, "p_public"] == pytest.approx(0.75)
    assert pooled.loc[128, "p_public"] == 1.0 and pooled.loc[128, "ci_high"] == 1.0
    split = table[table["direction"] == "inflated"].set_index("m")
    assert split.loc[2, "n"] == 8
    assert "fake: 32 primary runs" in capsys.readouterr().out

    behaviour = pd.read_csv(out / "behaviour.csv")
    assert len(behaviour) == 32
    assert behaviour["corrections"].mean() == pytest.approx(28 / 32)
    assert behaviour["committed"].mean() == pytest.approx(0.5)
    assert behaviour["says_downstream"].sum() == 28  # the prefix's "downstream" is not the agent's
    assert behaviour["says_minor"].sum() == 4
