"""Shared fixtures: generate task repos once per session and reuse them."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from taskgen import generate as G
from taskgen.generate import reverse_substitute

TEMPLATE_NAMES = ("lab_eval", "charity_program")
DEFAULT_ENTITY = {"lab_eval": "ambervale", "charity_program": "brightwater"}
DEFAULT_CELL = dict(direction="inflated", m=40, base_rate="A", seed=0)
IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache"}


def repo_files(root: Path) -> dict[str, bytes]:
    """relpath -> bytes for every file under root, skipping git internals and caches."""
    out = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if IGNORED_DIRS & set(rel.parts):
            continue
        out[rel.as_posix()] = path.read_bytes()
    return out


def git_log(root: Path) -> str:
    return subprocess.run(
        ["git", "log", "--format=%ad|%an|%ae|%s", "--date=iso"],
        cwd=root, check=True, capture_output=True, text=True,
    ).stdout


def run_pytest(task_dir: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rf", "--tb=no", "-p", "no:cacheprovider"],
        cwd=task_dir, capture_output=True, text=True,
        env={"PATH": "", "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(Path.home())},
    )
    return proc.returncode, proc.stdout + proc.stderr


def run_report(task_dir: Path) -> str:
    return G.run_report(task_dir)


def parse_resolved(report_stdout: str) -> tuple[int, int]:
    m = re.search(r"(?:Resolved|Confirmed): (\d+)/(\d+)", report_stdout)
    assert m, report_stdout
    return int(m.group(1)), int(m.group(2))


class Generated:
    def __init__(self, path: Path, meta: dict, entity: dict):
        self.path = path
        self.meta = meta
        self.entity = entity


@pytest.fixture(scope="session")
def entities() -> dict[str, dict]:
    return G.load_entities()


@pytest.fixture(scope="session", params=TEMPLATE_NAMES)
def template(request) -> str:
    return request.param


@pytest.fixture(scope="session")
def gen(tmp_path_factory, entities, template):
    """gen(entity_key, **cell) -> Generated; cached per (entity, cell).

    The template comes from the ``template`` fixture, so every test that uses
    ``gen`` runs once for lab_eval and once for charity_program. The default
    entity is a neutral of that template's kind.
    """
    cache: dict[tuple, Generated] = {}
    counter = {"n": 0}

    def _gen(entity_key: str | None = None, *, tag: str | None = None, **overrides) -> Generated:
        if entity_key is None:
            entity_key = DEFAULT_ENTITY[template]
        cell = {**DEFAULT_CELL, **overrides, "template": template}
        key = (entity_key, tag, tuple(sorted(cell.items())))
        if key not in cache:
            counter["n"] += 1
            out = tmp_path_factory.mktemp(f"{template}-{counter['n']:02d}")
            meta = G.generate(entity_key=entity_key, out=out, verify=False, **cell)
            cache[key] = Generated(out, meta, entities[entity_key])
        return cache[key]

    return _gen
