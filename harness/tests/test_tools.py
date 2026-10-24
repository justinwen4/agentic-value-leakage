"""Jailed tools against a generated task directory under /tmp."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from harness.taskenv import task_python
from harness.tools import bash, list_dir, read_file, sandboxed, write_file
from taskgen.generate import generate

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRATCH = Path("/tmp/avl-harness-tools")


@pytest.fixture(scope="module")
def task_dir():
    if _SCRATCH.exists():
        shutil.rmtree(_SCRATCH)
    repo = _SCRATCH / "repo"
    generate(
        template="lab_eval",
        entity_key="ambervale",
        direction="inflated",
        m=20,
        base_rate="A",
        seed=0,
        out=repo,
        meta_path=_SCRATCH / "meta.json",
        verify=False,
    )
    yield repo
    shutil.rmtree(_SCRATCH, ignore_errors=True)


def _body(output: str) -> str:
    return output.rsplit("exit_code:", 1)[0]


def test_read_file_refuses_outside(task_dir):
    out = read_file(task_dir, "/etc/passwd")
    assert out.startswith("error:")
    assert "outside" in out


def test_read_file_refuses_relative_escape(task_dir):
    out = read_file(task_dir, "../../../../../../etc/passwd")
    assert "outside" in out


def test_write_file_refuses_outside(task_dir):
    target = Path("/tmp/avl-jail-should-not-write")
    if target.exists():
        target.unlink()
    out = write_file(task_dir, str(target), "nope")
    assert "outside" in out
    assert not target.exists()


def test_list_dir_refuses_parent(task_dir):
    out = list_dir(task_dir, "..")
    assert "outside" in out


def test_symlink_escape_refused(task_dir):
    link = task_dir / "escape"
    link.symlink_to(PROJECT_ROOT)
    out = read_file(task_dir, "escape/pyproject.toml")
    assert "outside" in out


def test_interpreter_is_task_venv(task_dir):
    bin_dir = str(Path(task_dir).resolve() / ".venv" / "bin")
    out = bash(task_dir, "command -v python python3 pytest pip")
    assert "exit_code: 0" in out
    paths = [line for line in _body(out).splitlines() if line.strip()]
    assert len(paths) == 4
    for path in paths:
        assert path.startswith(bin_dir + "/")
        assert str(PROJECT_ROOT) not in path
        assert "agentic-value-leakage" not in path
        assert "/Users/" not in path
    path_out = bash(task_dir, 'printf %s "$PATH"')
    body = _body(path_out)
    assert str(PROJECT_ROOT) not in body
    assert "/Users/" not in body
    assert "agentic-value-leakage" not in body
    home = bash(task_dir, 'printf %s "$HOME"')
    assert _body(home).strip() == "/home/dev"


def test_command_env_is_allowlisted(task_dir):
    out = bash(task_dir, "env")
    assert "exit_code: 0" in out
    body = _body(out)
    env = {}
    for line in body.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = value
    assert env["HOME"] == "/home/dev"
    assert env["LANG"] == "C.UTF-8"
    assert env["PIP_NO_INDEX"] == "1"
    assert env["PIP_FIND_LINKS"]
    assert "/Users/" not in env["PIP_FIND_LINKS"]
    assert "VIRTUAL_ENV" not in env
    for name in (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "ALL_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
    ):
        assert name not in env
    assert str(PROJECT_ROOT) not in body
    assert "value-leakage" not in body
    assert "agentic" not in body
    assert "/Users/" not in body


def test_project_packages_not_importable(task_dir):
    for name in ("taskgen", "harness"):
        out = bash(task_dir, f'python -c "import {name}"')
        assert "ModuleNotFoundError" in out
        assert "exit_code: 0" not in out


def test_task_libraries_importable(task_dir):
    out = bash(task_dir, 'python -c "import pandas, numpy, pytest"')
    assert "ModuleNotFoundError" not in out
    assert "exit_code: 0" in out


def test_task_python_path_is_outside_project():
    python = task_python()
    assert python.is_file()
    assert PROJECT_ROOT not in python.resolve().parents
    assert "agentic-value-leakage" not in str(python)


@pytest.mark.skipif(not sandboxed(), reason="no sandbox mechanism on this host")
def test_network_denied(task_dir):
    out = bash(task_dir, "curl -sS -m 5 https://example.com")
    assert "exit_code: 0" not in out
    assert "<html" not in out.lower()
    py = bash(
        task_dir,
        "python -c \"import urllib.request; urllib.request.urlopen('https://example.com', timeout=5)\"",
    )
    assert "exit_code: 0" not in py
    assert "<html" not in py.lower()


@pytest.mark.skipif(
    not sandboxed() or sys.platform != "darwin",
    reason="no sandbox mechanism on this host" if not sandboxed() else "write denial is macOS sandbox-exec only",
)
def test_outside_write_denied(task_dir):
    denied = Path.home() / "avl_x_denied_test"
    allowed = Path("/tmp/avl_x_ok_test")
    denied.unlink(missing_ok=True)
    allowed.unlink(missing_ok=True)
    try:
        out = bash(task_dir, f"touch {denied}")
        assert not denied.exists()
        assert "exit_code: 0" not in out
        ok = bash(task_dir, f"touch {allowed}")
        assert allowed.is_file(), ok
        assert "exit_code: 0" in ok
    finally:
        denied.unlink(missing_ok=True)
        allowed.unlink(missing_ok=True)


def test_pytest_and_report_still_run(task_dir):
    out = bash(task_dir, "pytest -q")
    assert "1 failed" in out
    report = bash(task_dir, "python report.py")
    assert "exit_code: 0" in report, report


def test_runtime_meta_records_interpreter_and_sandbox():
    from harness.run import runtime_meta

    fields = runtime_meta()
    assert set(fields) == {"task_python", "sandboxed"}
    assert isinstance(fields["sandboxed"], bool)
    python = Path(fields["task_python"])
    assert python.is_file()
    assert "agentic-value-leakage" not in str(python)
    assert PROJECT_ROOT not in python.parents


def test_unsandboxed_warning_is_once(task_dir, monkeypatch, capsys):
    monkeypatch.setattr("harness.tools.sandbox_backend", lambda: None)
    monkeypatch.setattr("harness.tools._unsandboxed_warned", False)
    first = bash(task_dir, "echo one")
    second = bash(task_dir, "echo two")
    assert "exit_code: 0" in first
    assert "exit_code: 0" in second
    err = capsys.readouterr().err
    assert err.count("no sandbox mechanism available") == 1


def test_timeout_kills_process_group(task_dir, monkeypatch):
    monkeypatch.setattr("harness.tools._BASH_TIMEOUT_S", 1)
    out = bash(task_dir, "sleep 30 # avl-timeout-marker")
    assert "timed out" in out
    assert "exit_code:" not in out
