"""Run a config grid: generate a task repo, run one episode, keep the raw artifacts.

Run directory layout matches BUILD.md exactly::

    runs/{model.name}/{entity}/{direction}/{m}/{seed}/

``base_rate`` is stored in ``meta.json`` and is not part of the path. Two cells
that differ only in ``base_rate`` would write the same directory, so seed lists
for different base rates must be disjoint: ``seeds`` may be a mapping
``{A: [...], B: [...]}``. A config may also list ``arms``, each a mapping of
top-level keys it overrides (e.g. ``prefill``); arm is not part of the path
either, so arms need disjoint seeds too. This module refuses a grid that
collides, across arms included.

After each episode the runtime leak scan (``harness.leakcheck``) runs over
every tool output, replayed prefix included; ``meta.json`` records
``leaked`` and ``leak_findings``, and ``harness.grade`` copies ``leaked``
into ``grade.json`` so analysis can drop the cell.

Resume skips a cell when ``grade.json`` exists, and also when
``final_message.txt`` exists, unless ``--force``. ``grade.json`` is written by
a later step; the final-message check is what makes this step resume-safe.

``m`` and ``entities`` are each a list shared by every model, or a mapping
from ``models[].name`` to a list or a single value: the controls run at each
model's own m50, and each pilot model runs its own set of entities. A model
missing from a mapping is an error before any cell runs; ``m: null``, or a
null entry for a model, is refused as empty.

``prefill: none`` (or null, or ``steps: 0``) skips the frozen prefix.
``prefill: default`` replays the recording for the model under test,
``taskgen/prefills/<model.name>_prefix.json``, in full (or its first
``steps`` calls). A model with no recording is an error before any cell
runs; another model's recording is never substituted. ``meta.json`` records
``prefill`` as ``{path, steps}`` or null.

``meta.json`` also records ``project_commit``, this repository's HEAD when the
cell started, and ``project_tree_clean``, whether tracked files matched it
(untracked files are not counted).
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
from harness.leakcheck import scan_trajectory
from harness.prefill import check_platform, normalize_prefill, prefix_path, read_calls
from harness.providers import make_provider
from harness.providers.openai_compat import cache_mode
from harness.taskenv import ensure_episode_venv, neutral_task_dir, remove_neutral_workspace, task_python
from harness.tools import OUTPUT_CAP, sandboxed
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
        check_platform(path)
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
    The index is reset afterwards. The episode ``.venv`` is the harness's,
    not the agent's work, and is left out even in repositories whose
    ``.gitignore`` does not list it.
    """
    _git(task_dir, "add", "-A")
    _git(task_dir, "rm", "-r", "-q", "--cached", "--ignore-unmatch", ".venv")
    proc = _git(task_dir, "-c", "color.ui=never", "diff", "--cached", "--binary", "HEAD")
    _git(task_dir, "reset", "-q")
    return proc.stdout


def _read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def arm_configs(cfg: dict) -> list[dict]:
    """The config itself, or one merged config per entry of ``arms``.

    Each arm is a mapping whose keys override the top level (e.g.
    ``prefill``, ``seeds``); its optional ``name`` is recorded in
    ``meta.json`` as ``arm``.
    """
    arms = cfg.get("arms")
    if not arms:
        return [cfg]
    base = {key: value for key, value in cfg.items() if key != "arms"}
    return [{**base, **arm, "arm": arm.get("name", str(index))} for index, arm in enumerate(arms)]


def _seeds(cfg: dict, base_rate: str) -> list[int]:
    """``seeds`` is a list shared by every base rate or a mapping ``{A: [...], B: [...]}``."""
    seeds = cfg["seeds"]
    if isinstance(seeds, dict):
        if base_rate not in seeds:
            raise SystemExit(f"seeds has no list for base rate {base_rate!r}")
        seeds = seeds[base_rate]
    return [int(seed) for seed in seeds]


_EMPTY_M = "config m is empty; set the grid (prefix_check.yaml takes its m from the midpoint sweep)"


def per_model(cfg: dict, key: str) -> dict[str, list]:
    """``cfg[key]`` is a list for every model or a mapping ``{model name: [...] or value}``."""
    value = cfg.get(key)
    empty = _EMPTY_M if key == "m" else f"config {key} is empty"
    if not value:
        raise SystemExit(empty)
    names = [model["name"] for model in cfg["models"]]
    if not isinstance(value, dict):
        return {name: list(value) for name in names}
    missing = [name for name in names if name not in value]
    if missing:
        raise SystemExit(f"{key} has no entry for model(s) {missing}; the mapping names {sorted(value)}")
    out = {}
    for name in names:
        values = value[name] if isinstance(value[name], list) else [value[name]]
        if not values or any(v is None for v in values):
            raise SystemExit(f"{empty} (model {name!r})")
        out[name] = values
    return out


def _cells(cfg: dict) -> list[dict]:
    m_by_model = per_model(cfg, "m")
    entities_by_model = per_model(cfg, "entities")
    cells = []
    for model in cfg["models"]:
        for entity, direction, m, base_rate in itertools.product(
            entities_by_model[model["name"]],
            cfg["directions"],
            m_by_model[model["name"]],
            cfg["base_rates"],
        ):
            for seed in _seeds(cfg, str(base_rate)):
                cells.append({
                    "model": model,
                    "entity": entity,
                    "direction": direction,
                    "m": int(m),
                    "base_rate": str(base_rate),
                    "seed": seed,
                    "arm": cfg.get("arm"),
                })
    return cells


def _check_collisions(cells: list[dict], runs_dir: Path) -> None:
    seen: dict[Path, str] = {}
    for cell in cells:
        path = _run_dir(
            runs_dir, cell["model"]["name"], cell["entity"], cell["direction"], cell["m"], cell["seed"],
        )
        marker = f"{cell.get('arm')}:{cell['base_rate']}:{cell['seed']}"
        previous = seen.get(path)
        if previous is not None and previous != marker:
            raise SystemExit(
                f"run directory collision at {path}: arm and base_rate are not part of the path "
                f"({previous} vs {marker}). Use disjoint seeds per base rate and per arm."
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


def project_revision(root: Path = _PROJECT_ROOT) -> dict:
    """This repository's HEAD and whether tracked files match it; nulls outside a checkout."""
    try:
        head = _git(root, "rev-parse", "HEAD").stdout.strip()
        dirty = _git(root, "status", "--porcelain", "--untracked-files=no").stdout.strip()
    except (RuntimeError, OSError):
        return {"project_commit": None, "project_tree_clean": None}
    return {"project_commit": head, "project_tree_clean": not dirty}


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
            readme_variant=cfg.get("readme_variant", "none"),
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
            check_platform(path)
            prefill_calls = read_calls(path, spec["steps"])
            prefill_meta = {"path": str(path.relative_to(_PROJECT_ROOT)), "steps": len(prefill_calls)}
        meta.update({
            "model_name": model["name"],
            "model_id": model["model"],
            "provider": model["provider"],
            "brief": cfg["brief"],
            "arm": cfg.get("arm"),
            "ask_enabled": bool(cfg["ask_enabled"]),
            "prefill": prefill_meta,
            "cache": cache_mode(model["model"]),
            "output_cap": dict(OUTPUT_CAP),
            **project_revision(),
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
        findings = scan_trajectory(_read_events(run_dir / "trajectory.jsonl"), cell["entity"])

        diff = _capture_diff(task_dir)
        (run_dir / "diff.patch").write_text(diff, encoding="utf-8")
        meta.update({
            "finished": _now(),
            "stopped_reason": result.stopped_reason,
            "n_turns": result.n_turns,
            "leaked": bool(findings),
            "leak_findings": findings,
        })
        _write_meta(run_dir / "meta.json", meta)
        text = result.final_message
        if text and not text.endswith("\n"):
            text += "\n"
        (run_dir / "final_message.txt").write_text(text, encoding="utf-8")
        leak = f" LEAKED ({len(findings)} findings)" if findings else ""
        return f"done {label} stopped={result.stopped_reason} turns={result.n_turns}{leak}"
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
    arms = arm_configs(yaml.safe_load(args.config.read_text(encoding="utf-8")))
    try:
        for arm in arms:
            check_prefix_files(arm)
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    jobs = [(arm, cell) for arm in arms for cell in _cells(arm)]
    runs_dir = args.runs_dir
    _check_collisions([cell for _, cell in jobs], runs_dir)
    failed = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(
                run_cell, arm, cell, runs_dir,
                _brief_text(arm["brief"], bool(arm["ask_enabled"])), args.force,
            )
            for arm, cell in jobs
        ]
        for future in as_completed(futures):
            line = future.result()
            print(line, flush=True)
            if line.startswith("FAIL"):
                failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
