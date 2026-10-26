"""Config grid expansion: per-base-rate seeds, arms, and run-directory collisions."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from harness.run import _cells, _check_collisions, arm_configs

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
