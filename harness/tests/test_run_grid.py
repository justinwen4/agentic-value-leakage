"""Config grid expansion: per-base-rate seeds, per-model m and entities, arms, and run-directory collisions."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from harness.run import _cells, _check_collisions, arm_configs, project_revision

BASE = {
    "models": [{"name": "m1"}], "entities": ["ambervale"], "directions": ["inflated", "understated"],
    "m": [4, 8], "base_rates": ["A", "B"], "brief": "brief_00", "ask_enabled": False, "prefill": "none",
}
CONFIGS = Path(__file__).resolve().parents[2] / "configs"


def test_seed_mapping_gives_each_base_rate_its_own_seeds(tmp_path):
    cells = _cells({**BASE, "seeds": {"A": [0, 1], "B": [100, 101]}})
    assert len(cells) == 2 * 2 * 2 * 2
    assert {c["seed"] for c in cells if c["base_rate"] == "A"} == {0, 1}
    assert {c["seed"] for c in cells if c["base_rate"] == "B"} == {100, 101}
    _check_collisions(cells, tmp_path)


def test_shared_seed_list_across_base_rates_collides(tmp_path):
    with pytest.raises(SystemExit, match="collision"):
        _check_collisions(_cells({**BASE, "seeds": [0]}), tmp_path)


def test_arms_override_and_must_not_share_seeds(tmp_path):
    cfg = {**BASE, "seeds": {"A": [0], "B": [100]}, "arms": [
        {"name": "with_prefix", "prefill": "default"},
        {"name": "brief_only", "prefill": "none", "seeds": {"A": [200], "B": [300]}},
    ]}
    arms = arm_configs(cfg)
    assert [a["arm"] for a in arms] == ["with_prefix", "brief_only"]
    assert [a["prefill"] for a in arms] == ["default", "none"]
    assert "arms" not in arms[0]
    _check_collisions([c for a in arms for c in _cells(a)], tmp_path)
    clash = {**cfg, "arms": [{"name": "x", "prefill": "default"}, {"name": "y", "prefill": "none"}]}
    with pytest.raises(SystemExit, match="collision"):
        _check_collisions([c for a in arm_configs(clash) for c in _cells(a)], tmp_path)


def test_empty_m_is_refused():
    with pytest.raises(SystemExit, match="m is empty"):
        _cells({**BASE, "seeds": [0], "m": None})


def test_m_mapping_gives_each_model_its_own_m(tmp_path):
    models = [{"name": "m1"}, {"name": "m2"}, {"name": "m3"}]
    cfg = {**BASE, "models": models, "seeds": {"A": [0], "B": [100]}, "m": {"m1": [12], "m2": 9, "m3": [15, 30]}}
    cells = _cells(cfg)
    by_model = {}
    for c in cells:
        by_model.setdefault(c["model"]["name"], set()).add(c["m"])
    assert by_model == {"m1": {12}, "m2": {9}, "m3": {15, 30}}
    assert len(cells) == (1 + 1 + 2) * 2 * 2
    _check_collisions(cells, tmp_path)
    # A list still applies to every model.
    assert {c["m"] for c in _cells({**cfg, "m": [4]})} == {4}


def test_m_mapping_missing_or_empty_model_is_refused():
    cfg = {**BASE, "models": [{"name": "m1"}, {"name": "m2"}], "seeds": [0]}
    with pytest.raises(SystemExit, match=r"no entry for model\(s\) \['m2'\]"):
        _cells({**cfg, "m": {"m1": [12], "other": [9]}})
    with pytest.raises(SystemExit, match="m is empty.*'m2'"):
        _cells({**cfg, "m": {"m1": [12], "m2": None}})


def test_entities_mapping_gives_each_model_its_own_entities(tmp_path):
    models = [{"name": "m1"}, {"name": "m2"}]
    cfg = {**BASE, "models": models, "seeds": {"A": [0], "B": [100]},
           "entities": {"m1": ["ambervale", "quillon"], "m2": ["saltmarsh"]}}
    cells = _cells(cfg)
    by_model = {}
    for c in cells:
        by_model.setdefault(c["model"]["name"], set()).add(c["entity"])
    assert by_model == {"m1": {"ambervale", "quillon"}, "m2": {"saltmarsh"}}
    assert len(cells) == (2 + 1) * 2 * 2 * 2
    _check_collisions(cells, tmp_path)
    with pytest.raises(SystemExit, match=r"entities has no entry for model\(s\) \['m2'\]"):
        _cells({**cfg, "entities": {"m1": ["ambervale"]}})
    with pytest.raises(SystemExit, match="entities is empty.*'m2'"):
        _cells({**cfg, "entities": {"m1": ["ambervale"], "m2": None}})


@pytest.mark.parametrize("name", ["positive_control.yaml", "noise_baseline.yaml"])
def test_control_configs_take_m_per_model(tmp_path, name):
    cfg = yaml.safe_load((CONFIGS / name).read_text())
    names = [model["name"] for model in cfg["models"]]
    assert set(cfg["m"]) == set(names)
    arms = arm_configs(cfg)
    with pytest.raises(SystemExit, match="m is empty"):
        _cells(arms[0])
    filled = {name: [10 + i] for i, name in enumerate(names)}
    cells = [c for a in arms for c in _cells({**a, "m": filled})]
    _check_collisions(cells, tmp_path)
    assert {(c["model"]["name"], c["m"]) for c in cells} == {(n, v[0]) for n, v in filled.items()}


@pytest.mark.parametrize("name", ["midpoint_sweep.yaml", "prefix_check.yaml"])
def test_step10_configs_expand_without_collisions(tmp_path, name):
    cfg = yaml.safe_load((CONFIGS / name).read_text())
    arms = arm_configs(cfg)
    if name == "prefix_check.yaml":
        # m is filled in from the midpoint sweep; until then the config refuses to run.
        with pytest.raises(SystemExit, match="m is empty"):
            _cells(arms[0])
        arms = [{**arm, "m": [16]} for arm in arms]
    cells = [c for a in arms for c in _cells(a)]
    _check_collisions(cells, tmp_path)
    assert {c["direction"] for c in cells} == {"inflated", "understated"}
    assert {c["entity"] for c in cells} == {"ambervale"}


def test_project_revision_records_head_and_tracked_changes(tmp_path):
    import subprocess

    assert project_revision(tmp_path) == {"project_commit": None, "project_tree_clean": None}

    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.com",
                        "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "a.txt").write_text("one\n")
    git("add", "a.txt")
    git("commit", "-q", "-m", "one")
    head = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert project_revision(tmp_path) == {"project_commit": head, "project_tree_clean": True}
    (tmp_path / "untracked.txt").write_text("x\n")
    assert project_revision(tmp_path)["project_tree_clean"] is True
    (tmp_path / "a.txt").write_text("two\n")
    assert project_revision(tmp_path) == {"project_commit": head, "project_tree_clean": False}
