"""Exactly one failing test at HEAD; the one-line fix makes everything pass."""
import re
import shutil

import pytest

from taskgen import generate as G

from .conftest import run_pytest

CELLS = [
    dict(direction="inflated", m=40, base_rate="A"),
    dict(direction="understated", m=15, base_rate="B"),
]


@pytest.mark.parametrize("cell", CELLS, ids=lambda c: f"{c['direction']}-m{c['m']}-{c['base_rate']}")
def test_exactly_one_failure_then_green(gen, tmp_path, cell):
    g = gen(**cell)
    spec = G.TEMPLATES[g.meta["template"]]

    code, out = run_pytest(g.path)
    assert code != 0
    failed = re.findall(r"^FAILED (\S+)", out, flags=re.M)
    assert failed == [spec.failing_test], out
    assert re.search(r"\b1 failed\b", out), out

    work = tmp_path / "fixed"
    shutil.copytree(g.path, work, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    G.apply_fix(work, spec, g.entity["module_name"])
    code, out = run_pytest(work)
    assert code == 0, out
    assert "failed" not in out, out


def test_fix_is_one_line(gen):
    g = gen()
    spec = G.TEMPLATES[g.meta["template"]]
    assert "\n" not in spec.fix_before and "\n" not in spec.fix_after
    loader = (g.path / G.substitute(spec.fix_file, {"MODULE_NAME": g.entity["module_name"]})).read_text()
    assert loader.count(spec.fix_before) == 1
