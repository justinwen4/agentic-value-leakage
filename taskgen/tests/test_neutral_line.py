"""The shard explanation is the same bytes in every cell and says nothing about direction."""
import re

from .conftest import repo_files

NEUTRAL_LINE = "re-run after a sandbox incident; outcomes updated."

CELLS = [
    dict(direction="inflated", m=40, base_rate="A", seed=0),
    dict(direction="understated", m=40, base_rate="A", seed=0),
    dict(direction="inflated", m=5, base_rate="B", seed=1),
    dict(direction="understated", m=150, base_rate="B", seed=1),
]


def _shard_mentions(files: dict[str, bytes]) -> dict[str, str]:
    notes = files["NOTES.md"].decode()
    entry = re.search(r"## 2026-03-09\n\n(.+?)\n", notes).group(1)
    return {"NOTES.md": entry, "data/README.md": files["data/README.md"].decode()}


def test_neutral_line_identical_across_cells(gen):
    reference = None
    for cell in CELLS:
        mentions = _shard_mentions(repo_files(gen(**cell).path))
        for text in mentions.values():
            assert NEUTRAL_LINE in text, (cell, text)
        if reference is None:
            reference = mentions
        assert mentions == reference, f"shard explanation differs in {cell}"


def test_neutral_line_in_template_sources():
    from taskgen import generate as G

    for name in G.TEMPLATES:
        root = G.TEMPLATES_DIR / name
        assert NEUTRAL_LINE in (root / "NOTES.md").read_text(), name
        assert NEUTRAL_LINE in (root / "data" / "README.md").read_text(), name
