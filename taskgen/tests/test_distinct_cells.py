"""No two cells of a grid may generate byte-identical task repos.

The grid here mirrors the shape of a config (directions x m x base rates x
seeds). When configs/midpoint_sweep.yaml exists its grid is used instead.
"""
from __future__ import annotations

import hashlib
import itertools
from pathlib import Path

import yaml

from taskgen import generate as G

from .conftest import repo_files

CONFIG = Path(__file__).resolve().parents[2] / "configs" / "midpoint_sweep.yaml"
FALLBACK_GRID = dict(directions=["inflated", "understated"], m=[5, 40], base_rates=["A", "B"], seeds=[0, 1])


def _grid() -> list[dict]:
    grid = FALLBACK_GRID
    if CONFIG.exists():
        cfg = yaml.safe_load(CONFIG.read_text())
        grid = dict(
            directions=cfg.get("directions", grid["directions"]),
            m=cfg.get("m", grid["m"]),
            base_rates=cfg.get("base_rates", grid["base_rates"]),
            seeds=list(range(min(cfg.get("n_per_cell", 2), 2))),
        )
    return [
        dict(direction=d, m=m, base_rate=b, seed=s)
        for d, m, b, s in itertools.product(grid["directions"], grid["m"], grid["base_rates"], grid["seeds"])
    ]


def _digest(files: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode())
        h.update(files[rel])
    return h.hexdigest()


def test_distinct_cells(gen):
    seen: dict[str, dict] = {}
    for cell in _grid():
        digest = _digest(repo_files(gen(**cell).path))
        assert digest not in seen, f"cells {seen[digest]} and {cell} generated identical repos"
        seen[digest] = cell


def test_data_differs_between_cells(gen):
    """The manipulation lives in the CSVs: directions/m must change the rerun shard."""
    a = gen(direction="inflated", m=40, base_rate="A", seed=0)
    b = gen(direction="understated", m=40, base_rate="A", seed=0)
    spec = G.TEMPLATES[a.meta["template"]]
    fa, fb = repo_files(a.path), repo_files(b.path)
    assert fa[spec.rerun_csv] != fb[spec.rerun_csv]
