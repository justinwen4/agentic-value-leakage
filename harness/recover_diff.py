"""Rebuild ``diff.patch`` for finished runs by replaying their recorded tool calls.

    python -m harness.recover_diff RUN_DIR [RUN_DIR ...]

Runs captured before ``_capture_diff`` took the generated base lost any work
the agent committed during the episode. The task directory is gone, but the
trajectory holds every tool call, prefix included. This regenerates the cell
from ``meta.json`` (its HEAD must equal ``meta.git.head``), re-executes each
call in order through ``harness.tools.execute``, compares every capped output
with the recorded one, and captures the diff against the generated base.

Outputs are compared after normalizing what differs between two executions
of the same calls: the workspace path, commit and object hashes, pytest
timings and banner padding, pip wheel details, ``date``, git and ``ls -l``
dates. Calls that name the old workspace or a commit hash from the original
episode are rewritten before they run: each matched output pairs the
recorded hashes with the replayed ones in order, and later arguments get the
replayed hash (a recorded prefix gets the same-length prefix). Every rewrite
is listed in the replay record. Nothing in the run folder is overwritten
blind: the old diff is kept as ``diff_captured.patch`` and the replay record,
mismatches included, goes to ``diff_recovery.json``. A run with any mismatch
keeps its old ``diff.patch`` unless ``--accept-mismatch`` is given. Regrade
afterwards with ``python -m harness.grade --runs RUN_DIR --force``.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from harness.run import _capture_diff, _read_events, project_revision
from harness.taskenv import ensure_episode_venv, neutral_task_dir, remove_neutral_workspace
from harness.tools import AskSignal, cap_output, execute
from taskgen.generate import generate, load_entities

_HEX = re.compile(r"\b[0-9a-f]{7,64}\b")
_PYTEST_TIME = re.compile(r"\bin \d+\.\d+s\b")
_BANNER = re.compile(r"^=+ (.*?) =+$", re.M)
_WHEEL = re.compile(r"size=\d+|pip-ephem-wheel-cache-\w+|wheels(/[0-9a-f]+)+")
_LS_DATE = re.compile(r"\b[A-Z][a-z]{2} +\d{1,2} +(\d{1,2}:\d{2}|\d{4})\b")
_GIT_DATE = re.compile(r"^( *Date: +).*$", re.M)
_WORKSPACE = re.compile(r"/(private/)?tmp/ws-[0-9a-f]{8}")
_DATE_CMD = re.compile(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun) [A-Z][a-z]{2} +\d{1,2} \d{2}:\d{2}:\d{2} [A-Z]{2,5} \d{4}\b")


def normalize(text: str) -> str:
    text = _WORKSPACE.sub("<ws>", text or "")
    text = _DATE_CMD.sub("<date>", text)
    text = _GIT_DATE.sub(r"\1<date>", text)
    text = _LS_DATE.sub("<date>", text)
    text = _PYTEST_TIME.sub("in <t>s", text)
    text = _BANNER.sub(r"== \1 ==", text)
    text = _WHEEL.sub("<wheel>", text)
    return _HEX.sub("<hex>", text)


def _strings(value, fn):
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {k: _strings(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [_strings(v, fn) for v in value]
    return value


class Translator:
    """Maps the original episode's workspace path and hashes onto the replay's."""

    def __init__(self, old_dir: str, new_dir: Path) -> None:
        old = str(old_dir).removeprefix("/private")
        new = str(new_dir).removeprefix("/private")
        self.paths = [("/private" + old, str(new_dir)), (old, new)]
        self.hashes: dict[str, str] = {}

    def learn(self, recorded: str, replayed: str) -> None:
        """Pair hashes position by position; call only when the normalized outputs match."""
        for old, new in zip(_HEX.findall(_WORKSPACE.sub("", recorded)), _HEX.findall(_WORKSPACE.sub("", replayed))):
            if old != new:
                self.hashes.setdefault(old, new)

    def _hash(self, match: re.Match) -> str:
        token = match.group(0)
        if token in self.hashes:
            return self.hashes[token]
        for old, new in self.hashes.items():
            if old.startswith(token):
                return new[:len(token)]
            if token.startswith(old):
                return new
        return token

    def rewrite(self, text: str) -> str:
        for old, new in self.paths:
            text = text.replace(old, new)
        return _HEX.sub(self._hash, text)


def recorded_calls(events: list[dict]) -> list[tuple[dict, dict]]:
    """``(call, tool_event)`` pairs in execution order."""
    calls = {}
    for event in events:
        for call in event.get("tool_calls") or []:
            calls[call["id"]] = call
    return [(calls[e["tool_call_id"]], e) for e in events if e.get("role") == "tool"]


def recover(run_dir: Path, *, accept_mismatch: bool = False) -> str:
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    events = _read_events(run_dir / "trajectory.jsonl")
    entity = load_entities()[meta["entity"]]
    task_dir = neutral_task_dir(entity["package_name"])
    try:
        regen = generate(
            template=meta["template"], entity_key=meta["entity"], direction=meta["direction"],
            m=int(meta["m"]), base_rate=str(meta["base_rate"]), seed=int(meta["seed"]),
            readme_variant=meta.get("readme_variant", "none"), out=task_dir,
        )
        base = meta["git"]["head"]
        if regen["git"]["head"] != base:
            return f"FAIL {run_dir}: regenerated HEAD {regen['git']['head']} != meta {base}"
        ensure_episode_venv(task_dir)

        mismatches, rewrites = [], []
        translate = Translator(meta["task_dir"], task_dir)
        pairs = recorded_calls(events)
        for n, (call, event) in enumerate(pairs, start=1):
            args = _strings(call.get("args"), translate.rewrite)
            if args != call.get("args"):
                rewrites.append({"call": n, "args": json.dumps(args)[:300]})
            result = execute(task_dir, call["name"], args, ask_enabled=bool(meta["ask_enabled"]))
            output = "end run, action=Ask" if isinstance(result, AskSignal) else result
            shown, _ = cap_output(output)
            if normalize(shown) == normalize(event.get("output")):
                translate.learn(event.get("output") or "", shown)
            else:
                lines = difflib.unified_diff(normalize(event.get("output")).splitlines(),
                                             normalize(shown).splitlines(), "recorded", "replayed", lineterm="", n=1)
                mismatches.append({
                    "call": n, "name": call["name"], "args": json.dumps(call.get("args"))[:300],
                    "diff": "\n".join(lines)[:2000],
                })
        diff = _capture_diff(task_dir, base)
    finally:
        remove_neutral_workspace(task_dir)

    record = {
        "method": "replay of recorded tool calls; diff against meta.git.head",
        "recovered_at": datetime.now(timezone.utc).isoformat(),
        **project_revision(),
        "calls": len(pairs),
        "mismatched_calls": len(mismatches),
        "mismatches": mismatches,
        "rewritten_calls": rewrites,
        "diff_bytes": len(diff),
        "applied": not mismatches or accept_mismatch,
    }
    (run_dir / "diff_recovery.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if not record["applied"]:
        return f"MISMATCH {run_dir}: {len(mismatches)} of {len(pairs)} calls differ; diff.patch left as is"
    captured = run_dir / "diff_captured.patch"
    if not captured.exists():
        (run_dir / "diff.patch").rename(captured)
    (run_dir / "diff.patch").write_text(diff, encoding="utf-8")
    return f"recovered {run_dir}: {len(pairs)} calls replayed, {len(mismatches)} mismatched, diff {len(diff)} bytes"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild diff.patch by replaying recorded tool calls.")
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--accept-mismatch", action="store_true")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args(argv)
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        lines = list(pool.map(lambda d: recover(d, accept_mismatch=args.accept_mismatch), args.run_dirs))
    for line in lines:
        print(line)
    return 0 if all(line.startswith("recovered") for line in lines) else 1


if __name__ == "__main__":
    raise SystemExit(main())
