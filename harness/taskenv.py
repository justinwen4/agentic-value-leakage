"""Dedicated interpreter for generated task repositories.

The project's own virtualenv is never placed on the agent's PATH. Episodes
copy it into a neutral workspace and run ``python``, ``python3``, ``pytest``,
and ``pip`` from that copy. Wheels for an offline ``pip install`` live in a
generic directory under ``/tmp``.
"""
from __future__ import annotations

import fcntl
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

_PACKAGES = ("pandas", "numpy", "pytest")
_MARKER = ".packages-ok"
_EPISODE_MARKER = ".episode-ready"
_WHEEL_PACKAGES = ("setuptools", "wheel", "pandas", "pytest")
_WHEELHOUSE = Path("/tmp/pywheels")
_cache: dict[str, Path] = {}
_WS_RE = re.compile(r"ws-[0-9a-f]{8}")
_FORBIDDEN_COMPONENTS = frozenset({"inflated", "understated", "runs", "k"})


def _venv_root() -> Path:
    raw = os.environ.get("TASK_PYTHON_VENV")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".cache" / "task-python" / "venv").resolve()


def _base_executable() -> Path:
    """Interpreter that created this process's virtualenv, not the venv itself."""
    candidate = getattr(sys, "_base_executable", None)
    if candidate:
        path = Path(candidate)
        if path.is_file():
            return path
    for name in ("python3", "python"):
        path = Path(sys.base_prefix) / "bin" / name
        if path.is_file():
            return path
    raise RuntimeError("cannot find the base interpreter for the task virtualenv")


def _ready(root: Path) -> bool:
    return (root / "bin" / "python").is_file() and (root / _MARKER).is_file()


class _Lock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh = None

    def __enter__(self) -> "_Lock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("a+")
        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            if self._fh is not None:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            if self._fh is not None:
                self._fh.close()


def _run(argv: list[str]) -> None:
    proc = subprocess.run(argv, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"{argv[0]} failed ({proc.returncode}): {detail}")


def task_venv_bin() -> Path:
    """Return the task virtualenv's ``bin`` directory, creating the env if needed."""
    root = _venv_root()
    key = str(root)
    cached = _cache.get(key)
    if cached is not None and _ready(root):
        return cached
    with _Lock(root.parent / f".{root.name}.lock"):
        if not _ready(root):
            root.parent.mkdir(parents=True, exist_ok=True)
            _run([str(_base_executable()), "-m", "venv", str(root)])
            _run([str(root / "bin" / "pip"), "install", "-q", *_PACKAGES])
            (root / _MARKER).write_text("\n".join(_PACKAGES) + "\n", encoding="utf-8")
    bin_dir = root / "bin"
    _cache[key] = bin_dir
    return bin_dir


def task_python() -> Path:
    """Absolute path of the task interpreter (the venv ``python``, not its symlink target)."""
    return Path(os.path.abspath(task_venv_bin() / "python"))


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _tmp_root() -> Path:
    return Path("/tmp").resolve()


def wheelhouse_dir() -> Path:
    """Neutral directory of pre-downloaded wheels. Not inside a task repo."""
    return _WHEELHOUSE.resolve()


def assert_neutral_workspace(task_dir: Path, package_name: str) -> Path:
    """Reject a working directory whose path can name the project, user, or entity key.

    The only non-generic component allowed is ``package_name`` itself, as the
    final path component. ``/private/tmp`` is accepted because macOS resolves
    ``/tmp`` there.
    """
    resolved = Path(task_dir).resolve()
    text = str(resolved)
    lowered = text.casefold()
    for needle in ("value-leakage", "agentic", "/users/"):
        if needle in lowered:
            raise RuntimeError(f"workspace path is not neutral: {resolved}")
    home = str(Path.home().resolve())
    project = str(_project_root())
    if (home and home in text) or project in text:
        raise RuntimeError(f"workspace path is not neutral: {resolved}")
    if resolved.name != package_name:
        raise RuntimeError(
            f"workspace path must end in the package name {package_name!r}: {resolved}"
        )
    if _WS_RE.fullmatch(resolved.parent.name) is None:
        raise RuntimeError(f"workspace path is not neutral: {resolved}")
    if resolved.parent.parent != _tmp_root():
        raise RuntimeError(f"workspace path is not neutral: {resolved}")
    from taskgen.generate import load_entities

    banned = {key.casefold() for key in load_entities()}
    banned.update(part.casefold() for part in _FORBIDDEN_COMPONENTS)
    for part in resolved.parts[:-1]:
        if part.casefold() in banned:
            raise RuntimeError(f"workspace path is not neutral: {resolved}")
    return resolved


def neutral_task_dir(package_name: str) -> Path:
    """Create ``/tmp/ws-<8 hex>/<package_name>`` and return its resolved path."""
    if (
        not package_name
        or package_name in {".", ".."}
        or "/" in package_name
        or package_name.startswith(".")
    ):
        raise ValueError(f"invalid package name: {package_name!r}")
    tmp = Path("/tmp")
    allocated: Path | None = None
    for _ in range(8):
        root = tmp / f"ws-{secrets.token_hex(4)}"
        try:
            root.mkdir()
        except FileExistsError:
            continue
        allocated = root
        break
    if allocated is None:
        raise RuntimeError("could not allocate a neutral workspace")
    task = allocated / package_name
    task.mkdir()
    return assert_neutral_workspace(task, package_name)


def remove_neutral_workspace(task_dir: Path) -> None:
    """Remove the ``ws-<hex>`` directory that contains ``task_dir``."""
    resolved = Path(task_dir).resolve()
    parent = resolved.parent
    if _WS_RE.fullmatch(parent.name) and parent.parent == _tmp_root():
        shutil.rmtree(parent, ignore_errors=True)
        return
    shutil.rmtree(resolved, ignore_errors=True)


def ensure_wheelhouse() -> Path:
    """Download setuptools, wheel, pandas, and pytest wheels once, offline-usable later."""
    root = wheelhouse_dir()
    marker = root / ".complete"
    expected = "\n".join(_WHEEL_PACKAGES) + "\n"
    if marker.is_file() and marker.read_text(encoding="utf-8") == expected and any(root.glob("*.whl")):
        return root
    with _Lock(Path("/tmp") / ".pywheels.lock"):
        if marker.is_file() and marker.read_text(encoding="utf-8") == expected and any(root.glob("*.whl")):
            return root
        root.mkdir(parents=True, exist_ok=True)
        pip = task_venv_bin() / "pip"
        _run([str(pip), "download", "-d", str(root), *_WHEEL_PACKAGES])
        if not any(root.glob("*.whl")):
            raise RuntimeError(f"wheelhouse at {root} contains no wheels")
        marker.write_text(expected, encoding="utf-8")
    text = str(root).casefold()
    if "/users/" in text or "value-leakage" in text or "agentic" in text:
        raise RuntimeError(f"wheelhouse path is not neutral: {root}")
    return root


def _copy_venv(src: Path, dest: Path) -> None:
    if sys.platform == "darwin":
        proc = subprocess.run(
            ["cp", "-cR", str(src), str(dest)],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return
        if dest.exists():
            shutil.rmtree(dest)
    shutil.copytree(src, dest, symlinks=True)


def _rewrite_venv_paths(dest: Path, old_root: str, new_root: str) -> None:
    """Point shebangs and pyvenv.cfg at the copied tree.

    The source tree records its own location. Leaving that string in place
    would send ``pip`` back at the shared environment.
    """
    old_b = old_root.encode()
    new_b = new_root.encode()
    targets = [dest / "pyvenv.cfg"]
    bin_dir = dest / "bin"
    if bin_dir.is_dir():
        targets.extend(path for path in bin_dir.iterdir() if path.is_file() and not path.is_symlink())
    for path in targets:
        if not path.is_file():
            continue
        data = path.read_bytes()
        if old_b not in data or b"\0" in data:
            continue
        path.write_bytes(data.replace(old_b, new_b))


def ensure_episode_venv(task_dir: Path) -> Path:
    """Copy the shared task interpreter into ``task_dir/.venv`` and return its ``bin``.

    pandas, numpy, and pytest are already installed in the copy, so pytest
    runs before ``pip install -e .``. Writes stay inside the task directory.
    """
    root = Path(task_dir).resolve()
    dest = root / ".venv"
    if (dest / "bin" / "python").is_file() and (dest / _EPISODE_MARKER).is_file():
        return dest / "bin"
    source_bin = task_venv_bin()
    source = source_bin.parent
    old_root = str(source.resolve())
    if dest.exists():
        shutil.rmtree(dest)
    _copy_venv(source, dest)
    new_root = str(dest)
    _rewrite_venv_paths(dest, old_root, new_root)
    if old_root.encode() in (dest / "pyvenv.cfg").read_bytes():
        raise RuntimeError("episode virtualenv still records the shared environment path")
    pip_script = (dest / "bin" / "pip").read_bytes()
    if old_root.encode() in pip_script or not pip_script.startswith(b"#!" + new_root.encode() + b"/"):
        raise RuntimeError("episode pip shebang was not rewritten into the workspace")
    (dest / _EPISODE_MARKER).write_text("ok\n", encoding="utf-8")
    (dest / "tmp").mkdir(exist_ok=True)
    (dest / "pip-cache").mkdir(exist_ok=True)
    return dest / "bin"
