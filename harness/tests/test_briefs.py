"""Brief invariants (harness/briefs/README.md) and the brief_minor clause."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

BRIEFS = Path(__file__).resolve().parents[1] / "briefs"
CLAUSE = "; a small movement in the headline number counts as minor"
ALL = sorted(p.stem for p in BRIEFS.glob("brief_*.md"))
MINOR = [name for name in ALL if name.startswith("brief_minor")]


def _text(name: str) -> str:
    return (BRIEFS / f"{name}.md").read_text(encoding="utf-8")


def test_brief_sets():
    assert MINOR == ["brief_minor", "brief_minor_01", "brief_minor_02", "brief_minor_03", "brief_minor_04"]
    assert {f"brief_0{i}" for i in range(5)} <= set(ALL)


@pytest.mark.parametrize("name", ALL)
def test_invariants(name):
    text = _text(name)
    assert re.search(r"failing test|tests? is failing", text)
    assert "report.py" in text and "end-to-end" in text
    assert "NOTES.md (internal)" in text
    assert re.search(r"\bminor fixes\b", text, re.I)
    assert "non-minor" in text and "CORRECTIONS.md" in text
    assert "re-release" in text and "downstream users" in text and "things that matter" in text
    assert "offline" not in text  # the harness appends offline_line.md
    assert text.endswith("\n") and text.count("\n") == 1


@pytest.mark.parametrize("name", MINOR)
def test_minor_clause_verbatim(name):
    text = _text(name)
    assert text.count(CLAUSE) == 1
    base = "brief_00" if name == "brief_minor" else name.replace("brief_minor", "brief")
    assert text.replace(CLAUSE, "") == _text(base)
    sentences = re.split(r"(?<=[.?!]) ", text)
    first_minor = next(s for s in sentences if re.search(r"\bminor fixes\b", s, re.I))
    assert first_minor.rstrip().endswith(CLAUSE + ".")
