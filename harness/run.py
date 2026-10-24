"""Run a config grid: generate a task repo, run one episode, keep the raw artifacts.

Run directory layout matches BUILD.md exactly::

    runs/{model.name}/{entity}/{direction}/{m}/{seed}/

``base_rate`` is stored in ``meta.json`` and is not part of the path. Two cells
that differ only in ``base_rate`` would write the same directory, so seed lists
for different base rates must be disjoint. This module refuses a grid that
collides.

Resume skips a cell when ``grade.json`` exists, and also when
``final_message.txt`` exists, unless ``--force``. ``grade.json`` is written by
a later step; the final-message check is what makes this step resume-safe.

``prefill: none`` (or null, or ``steps: 0``) skips the frozen prefix.
``prefill: default`` replays the recording for the model under test,
``taskgen/prefills/<model.name>_prefix.json``, in full (or its first
``steps`` calls). A model with no recording is an error before any cell
runs; another model's recording is never substituted. ``meta.json`` records
``prefill`` as ``{path, steps}`` or null.
"""
from __future__ import annotations

import argparse
import itertools
import json
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml

from harness.agent import run_episode
from harness.env import load_env
from harness.prefill import normalize_prefill, prefix_path, read_calls
from harness.providers import make_provider
from harness.taskenv import ensure_episode_venv, neutral_task_dir, remove_neutral_workspace, task_python
from harness.tools import sandboxed
from taskgen.generate import generate, load_entities

_SECRET_ENVS = ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def check_prefix_files(cfg: dict) -> list[Path]:
    """Every model in ``cfg`` must have its own recording when prefill is on.

    Raises ``FileNotFoundError`` naming the first missing file. Returns the
    resolved paths in config order.
    """
    spec = normalize_prefill(cfg.get("prefill"))
    if spec is None:
        return []
    paths = []
    for model in cfg["models"]:
        path = prefix_path(model["name"])
        read_calls(path, spec["steps"])
        paths.append(path)
    return paths


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(text: str) -> str:
    import os
    for name in _SECRET_ENVS:
        value = os.environ.get(name) or ""
        if value:
            text = text.replace(value, f"${name}")
    return text


class JsonlLogger:
    """Append one JSON object per line and flush so a crash keeps the prefix."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("w", encoding="utf-8")

    def __call__(self, event: dict) -> None:
        self._fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def _brief_text(brief: str, ask_enabled: bool) -> str:
    briefs = Path(__file__).resolve().parent / "briefs"
    text = (briefs / f"{brief}.md").read_text(encoding="utf-8").strip()
    if not ask_enabled:
        offline = (briefs / "offline_line.md").read_text(encoding="utf-8").strip()
        text = text + "\n" + offline
    return text


def _run_dir(runs_dir: Path, model_name: str, entity: str, direction: str, m: int, seed: int) -> Path:
    return runs_dir / model_name / entity / direction / str(m) / str(seed)


def _skip_reason(run_dir: Path, force: bool) -> str | None:
    if force:
        return None
    if (run_dir / "grade.json").exists():
        return "grade.json exists"
    if (run_dir / "final_message.txt").exists():
        return "final_message.txt exists"
    return None


def _write_meta(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def _git(task_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(task_dir), *args],
        check=False,
        capture_output=True,
        text=True,
        errors="replace",
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return proc


def _capture_diff(task_dir: Path) -> str:
    """Staged diff against HEAD, including files that were untracked.

    The task directory is a discarded temporary clone, so staging is safe.
    The index is reset afterwards.
    """
    _git(task_dir, "add", "-A")
    proc = _git(task_dir, "-c", "color.ui=never", "diff", "--cached", "HEAD")
    _git(task_dir, "reset", "-q")
    return proc.stdout


def _cells(cfg: dict) -> list[dict]:
    cells = []
    for model, entity, direction, m, base_rate, seed in itertools.product(
        cfg["models"],
        cfg["entities"],
        cfg["directions"],
        cfg["m"],
        cfg["base_rates"],
        cfg["seeds"],
    ):
        cells.append({
            "model": model,
            "entity": entity,
            "direction": direction,
            "m": int(m),
            "base_rate": str(base_rate),
            "seed": int(seed),
        })
    return cells


def _check_collisions(cells: list[dict], runs_dir: Path) -> None:
    seen: dict[Path, str] = {}
    for cell in cells:
        path = _run_dir(
            runs_dir, cell["model"]["name"], cell["entity"], cell["direction"], cell["m"], cell["seed"],
        )
        marker = f"{cell['base_rate']}:{cell['seed']}"
        previous = seen.get(path)
        if previous is not None and previous != marker:
            raise SystemExit(
                f"run directory collision at {path}: base_rate is not part of the path "
                f"({previous} vs {marker}). Use disjoint seeds per base rate."
            )
        seen[path] = marker


def runtime_meta(python: Path | None = None) -> dict:
    """Interpreter and sandbox facts recorded on every run's ``meta.json``.

    Pass the episode interpreter. The default is the shared task interpreter,
    which unit tests still check; a cell records the copy inside its workspace
    so ``meta.json`` does not store a home-directory path.
    """
    chosen = Path(python) if python is not None else task_python()
    return {
        "task_python": str(chosen),
        "sandboxed": sandboxed(),
    }


def _label(cell: dict) -> str:
    return (
        f"{cell['model']['name']}/{cell['entity']}/{cell['direction']}/"
        f"{cell['m']}/{cell['seed']}"
    )


def run_cell(cfg: dict, cell: dict, runs_dir: Path, brief_text: str, force: bool) -> str:
    label = _label(cell)
    run_dir = _run_dir(
        runs_dir, cell["model"]["name"], cell["entity"], cell["direction"], cell["m"], cell["seed"],
    )
    reason = _skip_reason(run_dir, force)
    if reason:
        return f"skip {label} ({reason})"

    entity = load_entities()[cell["entity"]]
    task_dir = neutral_task_dir(entity["package_name"])
    logger: JsonlLogger | None = None
    try:
        started = _now()
        meta = generate(
            template=cfg["template"],
            entity_key=cell["entity"],
            direction=cell["direction"],
            m=cell["m"],
            base_rate=cell["base_rate"],
            seed=cell["seed"],
            out=task_dir,
            meta_path=run_dir / "meta.json",
        )
        episode_python = ensure_episode_venv(task_dir) / "python"
        model = cell["model"]
        spec = normalize_prefill(cfg.get("prefill"))
        prefill_calls = None
        prefill_meta = None
        if spec:
            path = prefix_path(model["name"])
            prefill_calls = read_calls(path, spec["steps"])
            prefill_meta = {"path": str(path.relative_to(_PROJECT_ROOT)), "steps": len(prefill_calls)}
        meta.update({
            "model_name": model["name"],
            "model_id": model["model"],
            "provider": model["provider"],
            "brief": cfg["brief"],
            "ask_enabled": bool(cfg["ask_enabled"]),
            "prefill": prefill_meta,
            "started": started,
            **runtime_meta(episode_python),
        })
        _write_meta(run_dir / "meta.json", meta)

        provider = make_provider(model)
        logger = JsonlLogger(run_dir / "trajectory.jsonl")
        result = run_episode(
            provider,
            task_dir,
            brief_text,
            ask_enabled=bool(cfg["ask_enabled"]),
            max_turns=int(cfg.get("max_turns", 60)),
            log=logger,
            prefill_calls=prefill_calls,
            prefill_entity=entity if prefill_calls else None,
        )
        logger.close()
        logger = None

        diff = _capture_diff(task_dir)
        (run_dir / "diff.patch").write_text(diff, encoding="utf-8")
        meta.update({
            "finished": _now(),
            "stopped_reason": result.stopped_reason,
            "n_turns": result.n_turns,
        })
        _write_meta(run_dir / "meta.json", meta)
        text = result.final_message
        if text and not text.endswith("\n"):
            text += "\n"
        (run_dir / "final_message.txt").write_text(text, encoding="utf-8")
        return f"done {label} stopped={result.stopped_reason} turns={result.n_turns}"
    except Exception as exc:
        detail = _redact(traceback.format_exc())
        print(detail, file=sys.stderr, flush=True)
        return f"FAIL {label} {type(exc).__name__}: {_redact(str(exc))}"
    finally:
        if logger is not None:
            logger.close()
        remove_neutral_workspace(task_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate task repos and run agent episodes.")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--force", action="store_true", help="rerun cells that already finished")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args(argv)
    if args.concurrency < 1:
        print("concurrency must be >= 1", file=sys.stderr)
        return 2

    load_env()
    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    try:
        check_prefix_files(cfg)
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    cells = _cells(cfg)
    runs_dir = args.runs_dir
    _check_collisions(cells, runs_dir)
    brief_text = _brief_text(cfg["brief"], bool(cfg["ask_enabled"]))
    failed = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(run_cell, cfg, cell, runs_dir, brief_text, args.force) for cell in cells
        ]
        for future in as_completed(futures):
            line = future.result()
            print(line, flush=True)
            if line.startswith("FAIL"):
                failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
