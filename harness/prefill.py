"""Replay frozen tool calls against one task directory.

Recordings store ``{{PLACEHOLDER}}`` strings. This module forward-substitutes
the run's entity, executes each call, and splices the fresh outputs into the
conversation. It does not import the recorder.
"""
from __future__ import annotations

import json
from pathlib import Path

from harness.tools import AskSignal, cap_output, execute
from taskgen.generate import entity_values, substitute
from taskgen.prefill import sed_flavor


PREFILLS_DIR = Path(__file__).resolve().parents[1] / "taskgen" / "prefills"
_MODES = ("default", "none")


def normalize_prefill(raw) -> dict | None:
    """Return ``{mode: "default", steps}`` or None when prefill is off.

    Accepted forms: ``null``, ``none``, ``default``, or a mapping
    ``{mode: default|none, steps: N}``. ``steps`` is optional and means
    "replay only the first N recorded calls"; ``None`` replays the whole
    recording. ``steps: 0`` means no prefill. There is no ``path`` form:
    the recording is always the one for the model under test.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = {"mode": raw}
    if not isinstance(raw, dict):
        raise ValueError("prefill must be null, 'none', 'default', or a mapping {mode, steps}")
    if "path" in raw:
        raise ValueError(
            "prefill.path is not supported: the recording is chosen by the model name "
            "(taskgen/prefills/<model_key>_prefix.json)"
        )
    mode = raw.get("mode")
    if mode not in _MODES:
        raise ValueError(f"prefill.mode must be one of {_MODES}")
    if mode == "none":
        return None
    steps = raw.get("steps")
    if steps is None:
        return {"mode": "default", "steps": None}
    if isinstance(steps, bool) or not isinstance(steps, int):
        raise ValueError("prefill.steps must be an integer")
    if steps < 0:
        raise ValueError("prefill.steps must be >= 0")
    if steps == 0:
        return None
    return {"mode": "default", "steps": steps}


def prefix_path(model_key: str, prefills_dir: Path | None = None) -> Path:
    """The recording for ``model_key``: ``<prefills_dir>/<model_key>_prefix.json``.

    Raises ``FileNotFoundError`` when that file does not exist. No other
    model's recording is ever substituted.
    """
    if not isinstance(model_key, str) or not model_key or "/" in model_key:
        raise ValueError(f"invalid model key: {model_key!r}")
    root = Path(prefills_dir) if prefills_dir is not None else PREFILLS_DIR
    path = root / f"{model_key}_prefix.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"no recorded prefix for model {model_key!r}: expected {path}. "
            f"Record one with `python -m taskgen.prefill record --model-key {model_key}` "
            f"or set `prefill: none`."
        )
    return path


def _load_recording(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("calls"), list):
        raise ValueError(f"{path} has no calls list")
    meta = data.get("meta")
    if not isinstance(meta, dict):
        raise ValueError(f"{path} has no meta block")
    kept = meta.get("kept_calls")
    if isinstance(kept, bool) or not isinstance(kept, int) or kept != len(data["calls"]):
        raise ValueError(
            f"{path}: meta.kept_calls ({kept!r}) does not match the number of calls ({len(data['calls'])})"
        )
    return data


def recording_meta(path: Path) -> dict:
    """The ``meta`` block of a recording (model_key, model_id, kept_calls, recorded_with)."""
    return _load_recording(path)["meta"]


class PlatformMismatchError(RuntimeError):
    """The host's sed flavor differs from the one the recording was made with."""


def check_platform(path: Path, host_sed: str | None = None) -> None:
    """Refuse a recording made under a different sed flavor than this host's."""
    meta = recording_meta(path)
    platform = meta.get("platform")
    recorded = platform.get("sed") if isinstance(platform, dict) else None
    if not recorded:
        raise ValueError(
            f"{path} has no meta.platform.sed, so its host cannot be checked; re-record it."
        )
    host = host_sed if host_sed is not None else sed_flavor()
    if recorded != host:
        raise PlatformMismatchError(
            f"Prefix {path} (model {meta.get('model_key')!r}) was recorded with {recorded} sed "
            f"on {platform.get('os')}, but this host has {host} sed. "
            f"It replays as recorded only on a host with {recorded} sed; "
            f"set `prefill: none` to disable the prefix."
        )


def read_calls(path: Path, steps: int | None = None) -> list[dict]:
    """Load the first ``steps`` recorded calls; all of them when ``steps`` is None."""
    data = _load_recording(path)
    calls = data["calls"]
    if steps is None:
        steps = len(calls)
    if steps < 1:
        raise ValueError("steps must be >= 1 to load recorded calls")
    if steps > len(calls):
        raise ValueError(
            f"prefill steps {steps} exceeds {len(calls)} recorded calls in {path}"
        )
    return calls[:steps]


def _map_strings(value, fn):
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, list):
        return [_map_strings(item, fn) for item in value]
    if isinstance(value, dict):
        return {key: _map_strings(item, fn) for key, item in value.items()}
    return value


def prepare_calls(calls: list[dict], entity: dict) -> list[dict]:
    """Forward-substitute placeholders in assistant text and arguments."""
    values = entity_values(entity)
    prepared = []
    for call in calls:
        text = call.get("text")
        args = call.get("args")
        if args is None:
            args = {}
        prepared.append({
            "text": substitute(text, values, complete=False) if isinstance(text, str) else text,
            "name": call["name"],
            "args": _map_strings(args, lambda s: substitute(s, values, complete=False)),
        })
    return prepared


def replay_prefill(task_dir, calls: list[dict], entity: dict, *, ask_enabled: bool, emit) -> tuple[list[dict], bool, str]:
    """Execute ``calls`` against ``task_dir`` and emit trajectory events.

    Returns ``(messages, asked, last_text)``. Messages are the assistant and
    tool messages to append after the brief. ``asked`` is true when a call
    ended the run. Events are marked ``prefill: true``. Outputs are capped as
    in the live loop, with ``output_full`` on a cut event.
    """
    concrete = prepare_calls(calls, entity)
    messages: list[dict] = []
    last_text = ""
    for index, call in enumerate(concrete):
        call_id = f"prefill_{index:03d}"
        text = call.get("text")
        if isinstance(text, str) and text:
            last_text = text
        else:
            text = None
        name = call["name"]
        args = call["args"] if isinstance(call["args"], dict) else {}
        emit(
            "assistant",
            content=text,
            tool_calls=[{"id": call_id, "name": name, "args": args}],
            prefill=True,
        )
        messages.append({
            "role": "assistant",
            "content": text,
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }],
        })
        result = execute(task_dir, name, args, ask_enabled=ask_enabled)
        if isinstance(result, AskSignal):
            output = "end run, action=Ask"
            emit("tool", tool_call_id=call_id, name=name, output=output, prefill=True)
            messages.append({"role": "tool", "tool_call_id": call_id, "content": output})
            if not last_text:
                last_text = result.question
            return messages, True, last_text
        shown, full = cap_output(result)
        extra = {"output_full": full} if full is not None else {}
        emit("tool", tool_call_id=call_id, name=name, output=shown, prefill=True, **extra)
        messages.append({"role": "tool", "tool_call_id": call_id, "content": shown})
    return messages, False, last_text
