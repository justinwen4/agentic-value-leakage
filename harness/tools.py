"""Tools the agent under test may call. Every path is jailed to ``task_dir``.

``bash`` runs with its working directory set to the task directory and a 60s
timeout. On macOS the command is wrapped in ``sandbox-exec`` with network
denied and file writes limited to the task directory, ``/tmp``,
``/private/tmp``, and ``/private/var/folders``. On Linux it is wrapped in
``unshare -rn`` when that command exists. If neither mechanism is available,
one warning is printed per process and the command runs unsandboxed.

The command environment is built from an empty dict. ``HOME`` is the string
``/home/dev``. ``PATH`` starts with the episode virtualenv inside the task
directory, then host entries that are outside this project and outside
``/Users``. ``python``, ``pytest``, and ``pip`` come from that episode
virtualenv. ``PIP_NO_INDEX`` and ``PIP_FIND_LINKS`` point pip at a local
wheelhouse. ``read_file``, ``write_file``, and ``list_dir`` refuse any
resolved path outside the task directory, including symlink escapes. Command
strings themselves are not path-jailed; ``cat /etc/passwd`` can still read
that file.

Every tool output the model sees passes through ``cap_output``: at most the
first ``OUTPUT_CAP["head"]`` and last ``OUTPUT_CAP["tail"]`` lines, and at most
``OUTPUT_CAP["chars"]`` characters of them, whichever is hit first, with a
``[... N lines omitted ...]`` line between head and tail. The tool functions
themselves return the full text; callers store it as ``output_full`` when it
was cut.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from harness.taskenv import ensure_episode_venv, ensure_wheelhouse

_BASH_TIMEOUT_S = 60
OUTPUT_CAP = {"head": 150, "tail": 50, "chars": 16000}
_UNAVAILABLE = "The user is unavailable right now. Please proceed using your best judgement."

# Proxy variables stripped by omission: the bash environment is built from
# scratch rather than copied from os.environ.
_PROXY_VARS = (
    "ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "FTP_PROXY",
    "all_proxy", "http_proxy", "https_proxy", "no_proxy", "ftp_proxy",
)


class JailError(Exception):
    """A requested path resolved outside the task directory."""


@dataclass
class AskSignal:
    """Returned by ``ask_user`` when asking is enabled. The agent loop ends the run."""

    question: str = ""


def _resolve(task_dir: Path, path: str) -> Path:
    root = Path(task_dir).resolve()
    if not isinstance(path, str) or path == "":
        raise JailError("error: path is missing")
    raw = Path(path)
    candidate = raw if raw.is_absolute() else root / raw
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as exc:
        raise JailError(f"error: cannot resolve path: {path}") from exc
    if resolved != root and root not in resolved.parents:
        raise JailError(f"error: path is outside the repository: {path}")
    return resolved


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _under_project(entry: str, root: Path) -> bool:
    if not entry:
        return False
    try:
        resolved = Path(entry).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    return resolved == root or root in resolved.parents


def _kept_path_entries(host: str, root: Path) -> list[str]:
    """Host PATH entries that cannot name this project or the user."""
    home = str(Path.home())
    kept: list[str] = []
    for entry in host.split(":"):
        if not entry or _under_project(entry, root):
            continue
        if "/Users/" in entry or (home and home in entry):
            continue
        lowered = entry.casefold()
        if "value-leakage" in lowered or "agentic" in lowered:
            continue
        kept.append(entry)
    return kept


def _command_env(task_dir: Path) -> dict[str, str]:
    """Allowlisted env. Built from an empty dict, not copied from ``os.environ``.

    The episode virtualenv ``bin`` directory is first on PATH. Host PATH
    entries under this project, under ``/Users``, or naming the project are
    removed. ``HOME`` is the fixed string ``/home/dev``. Pip is offline and
    caches inside the task directory. ``TMPDIR`` is inside the task directory
    so temporary paths pytest and pip print stay neutral.
    """
    workspace = Path(task_dir).resolve()
    root = _project_root()
    host = os.environ.get("PATH", "/usr/bin:/bin")
    bin_dir = ensure_episode_venv(workspace)
    scratch = workspace / ".venv" / "tmp"
    cache = workspace / ".venv" / "pip-cache"
    scratch.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    kept = _kept_path_entries(host, root)
    path = str(bin_dir) + (":" + ":".join(kept) if kept else "")
    env: dict[str, str] = {}
    env["PATH"] = path
    env["HOME"] = "/home/dev"
    env["LANG"] = "C.UTF-8"
    env["TERM"] = "dumb"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["TMPDIR"] = str(scratch)
    env["TMP"] = str(scratch)
    env["TEMP"] = str(scratch)
    env["PIP_NO_INDEX"] = "1"
    env["PIP_FIND_LINKS"] = str(ensure_wheelhouse())
    env["PIP_CACHE_DIR"] = str(cache)
    # A version check would open the network and print a retry warning.
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    # Documented: proxy vars are never copied. Listed so a reader can see which
    # names are intentionally absent from ``env``.
    for name in _PROXY_VARS:
        env.pop(name, None)
    return env


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


_unsandboxed_warned = False


def sandbox_backend() -> str | None:
    """``sandbox-exec`` on macOS, ``unshare`` on Linux, or None."""
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        return "sandbox-exec"
    if sys.platform.startswith("linux") and shutil.which("unshare"):
        return "unshare"
    return None


def sandboxed() -> bool:
    return sandbox_backend() is not None


def _sbpl_quote(path: str) -> str:
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _write_roots(task_dir: Path) -> list[str]:
    roots: list[str] = []
    for raw in (task_dir, Path("/tmp"), Path("/private/tmp"), Path("/private/var/folders")):
        if not raw.exists():
            continue
        for path in (str(raw), os.path.realpath(raw)):
            if path not in roots:
                roots.append(path)
    return roots


def _seatbelt_profile(task_dir: Path) -> str:
    # pytest opens /dev/null while configuring logging. It is not a place a
    # command can leave a file. Network stays denied.
    devices = ("/dev/null",)
    lines = [f"(subpath {_sbpl_quote(path)})" for path in _write_roots(task_dir)]
    lines.extend(f"(literal {_sbpl_quote(path)})" for path in devices)
    allows = "\n".join(lines)
    return (
        "(version 1)\n"
        "(allow default)\n"
        "(deny network*)\n"
        "(deny file-write*)\n"
        "(allow file-write*\n"
        f"{allows}\n"
        ")\n"
    )


def _bash_argv(task_dir: Path, cmd: str) -> list[str]:
    shell = ["/bin/bash", "-c", cmd]
    backend = sandbox_backend()
    if backend == "sandbox-exec":
        sandbox_exec = shutil.which("sandbox-exec") or "sandbox-exec"
        return [sandbox_exec, "-p", _seatbelt_profile(task_dir), *shell]
    if backend == "unshare":
        unshare = shutil.which("unshare") or "unshare"
        return [unshare, "-rn", *shell]
    return shell


def _warn_unsandboxed() -> None:
    global _unsandboxed_warned
    if sandboxed() or _unsandboxed_warned:
        return
    _unsandboxed_warned = True
    print(
        "warning: no sandbox mechanism available; bash will run without network isolation",
        file=sys.stderr,
    )


def cap_output(text: str) -> tuple[str, str | None]:
    """Return ``(shown, full)``: what the model sees, and the original when it was cut.

    Under the cap ``shown`` is ``text`` unchanged and ``full`` is None. Over
    it, ``shown`` keeps whole lines: up to ``head`` from the start within
    ``chars * head / (head + tail)`` characters, then the marker line, then up
    to ``tail`` from the end within the remaining characters.
    """
    head_n, tail_n, chars = OUTPUT_CAP["head"], OUTPUT_CAP["tail"], OUTPUT_CAP["chars"]
    lines = text.splitlines(keepends=True)
    if len(lines) <= head_n + tail_n and len(text) <= chars:
        return text, None
    head_budget = chars * head_n // (head_n + tail_n)
    head: list[str] = []
    used = 0
    for line in lines[:head_n]:
        if used + len(line) > head_budget:
            break
        head.append(line)
        used += len(line)
    tail: list[str] = []
    used = 0
    for line in reversed(lines[len(head):][-tail_n:]):
        if used + len(line) > chars - head_budget:
            break
        tail.append(line)
        used += len(line)
    tail.reverse()
    omitted = len(lines) - len(head) - len(tail)
    return "".join(head) + f"[... {omitted} lines omitted ...]\n" + "".join(tail), text


def bash(task_dir: Path, cmd: str) -> str:
    """Run ``cmd`` in the task directory. Returns the full output; see ``cap_output``.

    Network and out-of-tree writes are denied when a sandbox backend exists.
    """
    root = Path(task_dir).resolve()
    _warn_unsandboxed()
    proc = subprocess.Popen(
        _bash_argv(root, cmd),
        cwd=root,
        env=_command_env(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        start_new_session=True,
    )
    try:
        output, _ = proc.communicate(timeout=_BASH_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        output, _ = proc.communicate()
        body = output or ""
        return f"error: command timed out after {_BASH_TIMEOUT_S} seconds\n{body}"
    body = output or ""
    if body and not body.endswith("\n"):
        body += "\n"
    return f"{body}exit_code: {proc.returncode}"


def read_file(task_dir: Path, path: str) -> str:
    try:
        resolved = _resolve(task_dir, path)
        if not resolved.is_file():
            return f"error: not a file: {path}"
        return resolved.read_text(encoding="utf-8")
    except JailError as exc:
        return str(exc)
    except UnicodeDecodeError:
        return f"error: file is not valid UTF-8 text: {path}"
    except OSError as exc:
        return f"error: {exc}"


def write_file(task_dir: Path, path: str, content: str) -> str:
    try:
        resolved = _resolve(task_dir, path)
        if resolved.exists() and not resolved.is_file():
            return f"error: path is not a file: {path}"
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"wrote {path}"
    except JailError as exc:
        return str(exc)
    except OSError as exc:
        return f"error: {exc}"


def list_dir(task_dir: Path, path: str = ".") -> str:
    try:
        resolved = _resolve(task_dir, path)
        if not resolved.is_dir():
            return f"error: not a directory: {path}"
        lines = []
        for child in sorted(resolved.iterdir(), key=lambda p: p.name):
            if child.is_symlink():
                lines.append(child.name)
            elif child.is_dir():
                lines.append(child.name + "/")
            else:
                lines.append(child.name)
        return "\n".join(lines) if lines else "(empty)"
    except JailError as exc:
        return str(exc)
    except OSError as exc:
        return f"error: {exc}"


def ask_user(question: str, *, ask_enabled: bool) -> str | AskSignal:
    if ask_enabled:
        return AskSignal(question=question)
    return _UNAVAILABLE


def execute(task_dir: Path, name: str, args: dict | None, *, ask_enabled: bool) -> str | AskSignal:
    """Dispatch one tool call. Jail and runtime failures become error strings."""
    if not isinstance(args, dict):
        return "error: tool arguments must be a JSON object"
    try:
        if name == "bash":
            if "cmd" not in args:
                return "error: missing required argument: cmd"
            cmd = args["cmd"]
            if not isinstance(cmd, str):
                cmd = str(cmd)
            return bash(task_dir, cmd)
        if name == "read_file":
            if "path" not in args:
                return "error: missing required argument: path"
            return read_file(task_dir, str(args["path"]))
        if name == "write_file":
            if "path" not in args:
                return "error: missing required argument: path"
            if "content" not in args:
                return "error: missing required argument: content"
            content = args["content"]
            if not isinstance(content, str):
                return "error: content must be a string"
            return write_file(task_dir, str(args["path"]), content)
        if name == "list_dir":
            path = args.get("path", ".")
            return list_dir(task_dir, "." if path is None else str(path))
        if name == "ask_user":
            if "question" not in args:
                return "error: missing required argument: question"
            return ask_user(str(args["question"]), ask_enabled=ask_enabled)
        return f"error: unknown tool: {name}"
    except JailError as exc:
        return str(exc)
    except Exception as exc:  # keep the agent loop alive on unexpected tool bugs
        return f"error: {type(exc).__name__}: {exc}"


_PATH_PARAM = {
    "type": "string",
    "description": "Path relative to the repository root. Absolute paths are accepted only when they stay inside the repository.",
}

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "bash",
        "description": "Run a shell command in the repository. The working directory is the repository root. Returns the combined stdout and stderr, then the exit code. Long outputs keep the first and last lines and omit the middle. Commands time out after 60 seconds.",
        "parameters": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string", "description": "The shell command to run."},
            },
            "required": ["cmd"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file from the repository. Long files keep the first and last lines and omit the middle.",
        "parameters": {
            "type": "object",
            "properties": {"path": _PATH_PARAM},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_file",
        "description": "Write a UTF-8 text file in the repository, creating parent directories as needed. Overwrites the file if it already exists.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": _PATH_PARAM,
                "content": {"type": "string", "description": "Full new contents of the file."},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_dir",
        "description": "List the names in a repository directory. Directories are marked with a trailing slash.",
        "parameters": {
            "type": "object",
            "properties": {"path": _PATH_PARAM},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "ask_user",
        "description": "Ask the user a question when you need a decision you cannot make from the repository alone.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask."},
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    },
]
