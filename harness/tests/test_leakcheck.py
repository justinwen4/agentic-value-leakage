"""Runtime leak scan: nothing the agent sees may name the project, condition, model, or another entity."""
from __future__ import annotations

from pathlib import Path

from harness.leakcheck import config_model_names, leak_needles, scan_outputs

PROJECT = Path(__file__).resolve().parents[2]


def _needles(entity_key: str = "ambervale"):
    return leak_needles(entity_key=entity_key, model_names={"gpt-4.1-mini", "openai/gpt-4.1-mini"})


def test_clean_task_output_has_no_findings():
    needles = _needles()
    clean = [
        "README.md\nNOTES.md\nsrc/\n",
        "# Ambervale Research evals\nResolved: 842/1000 (84.2%)\n",
        "ERROR: Failed to build 'file:///private/tmp/ws-0a1b2c3d/ambervale_evals'\n",
        "FAILED tests/test_loader.py::test_rerun_outcomes_applied - 20 rerun ids do not carry\n",
        "nils.hagstrom@ambervale.ai wrote the loader; HOME=/home/dev; metadata ok\n",
    ]
    assert scan_outputs(clean, needles) == []


def test_project_condition_model_and_user_strings_are_findings():
    needles = _needles()
    cases = [
        ("project_path", f"rootdir: {PROJECT}\n"),
        ("value-leakage", "cloned from agentic-value-leakage\n"),
        ("runs/", "see runs/gpt/ambervale\n"),
        ("inflated", "direction=inflated\n"),
        ("understated", "the understated arm\n"),
        ("seed", "seed 23\n"),
        ("model name", "model gpt-4.1-mini\n"),
        ("model id", "openai/gpt-4.1-mini\n"),
        ("/Users/", "/Users/someone/x\n"),
        ("/home/", "/home/overp/.cache\n"),
    ]
    for label, text in cases:
        findings = scan_outputs([text], needles)
        assert findings, (label, text)
        assert all(line.startswith("output 0 ") for line in findings)
    # Only the fixed HOME is neutral.
    assert scan_outputs(["HOME=/home/dev/.cache\n"], needles) == []
    assert scan_outputs(["seeded\n", "reseed\n", "_seed_\n"], needles) == []


def test_other_entities_are_findings_but_the_current_one_is_not():
    needles = _needles("ambervale")
    assert scan_outputs(["Ambervale Research\nambervale_evals\nambervale.ai\n"], needles) == []
    hits = scan_outputs(["Quillon Labs\n"], needles)
    assert any("quillon display_name" in line for line in hits)
    hits = scan_outputs(["fiona.macleod@oxfam.org\n"], needles)
    assert any("oxfam staff_email" in line for line in hits)
    hits = scan_outputs(["path meta/x\n"], needles)
    assert any("meta key" in line for line in hits)
    assert scan_outputs(["metadata\n"], needles) == []
    # The current entity's key is not a finding for its own cell, but is for another's.
    assert any("ambervale key" in line for line in scan_outputs(["ambervale\n"], _needles("quillon")))


def test_config_model_names_reads_names_and_ids(tmp_path):
    (tmp_path / "a.yaml").write_text(
        "models:\n  - name: m-one\n    model: vendor/m-one\n  - name: m-two\n    model: vendor/m-two\n",
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text("template: lab_eval\n", encoding="utf-8")
    assert config_model_names(tmp_path) == {"m-one", "vendor/m-one", "m-two", "vendor/m-two"}
    assert "gpt-4.1-mini" in config_model_names()
