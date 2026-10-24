"""Runtime leak scan of what the agent can observe.

Every tool output in a run (replayed prefix included) is scanned for strings
that would tell the agent about the study: the project repository's path or
name, the ``runs/`` bookkeeping, the condition words ``inflated`` and
``understated``, the word ``seed``, every model name and id in ``configs/``,
any ``/Users/`` path or any ``/home/`` other than the fixed ``/home/dev``,
and every entity's key and fields except the current entity's own.

``leak_needles`` builds the list once per cell; ``scan_outputs`` reports one
line per hit with the output index, so a finding can be traced to a call.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from taskgen.generate import load_entities

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CONFIGS_DIR = _PROJECT_ROOT / "configs"
_LITERALS = ("value-leakage", "runs/", "/Users/")
_WORDS = ("inflated", "understated", "seed")
_ENTITY_FIELDS = ("display_name", "package_name", "module_name", "email_domain", "github_org")
# Any /home/<user> other than the fixed /home/dev set by harness.tools.
_HOME_RE = re.compile(r"/home/(?!dev(?![A-Za-z0-9_-]))[^\s/'\";:]+")


def config_model_names(configs_dir: Path | None = None) -> set[str]:
    """Every ``models[].name`` and ``models[].model`` in ``configs/*.yaml``."""
    root = Path(configs_dir) if configs_dir is not None else _CONFIGS_DIR
    names: set[str] = set()
    for path in sorted(root.glob("*.yaml")):
        try:
            cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(cfg, dict):
            continue
        for model in cfg.get("models") or []:
            if not isinstance(model, dict):
                continue
            for field in ("name", "model"):
                value = model.get(field)
                if isinstance(value, str) and value:
                    names.add(value)
    return names


def _word(needle: str) -> re.Pattern:
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(needle)}(?![A-Za-z0-9_])", re.IGNORECASE)


def _substring(needle: str) -> re.Pattern:
    return re.compile(re.escape(needle), re.IGNORECASE)


def leak_needles(
    *,
    entity_key: str,
    entities: dict[str, dict] | None = None,
    model_names: set[str] | None = None,
    project_root: Path | None = None,
) -> list[tuple[str, re.Pattern]]:
    """``(label, pattern)`` pairs for one cell. ``model_names`` defaults to ``configs/``."""
    if entities is None:
        entities = load_entities()
    if model_names is None:
        model_names = config_model_names()
    root = Path(project_root) if project_root is not None else _PROJECT_ROOT
    needles: list[tuple[str, re.Pattern]] = [
        ("project_path", _substring(str(root))),
        ("home_path", _substring(str(Path.home()))),
    ]
    needles.extend((literal, _substring(literal)) for literal in _LITERALS)
    needles.extend((word, _word(word)) for word in _WORDS)
    needles.append(("/home/", _HOME_RE))
    for name in sorted(model_names):
        needles.append((f"model {name}", _word(name)))
    for key in sorted(entities):
        if key == entity_key:
            continue
        entity = entities[key]
        raw_key = entity.get("key", key)
        if isinstance(raw_key, str) and raw_key:
            needles.append((f"{key} key", _word(raw_key)))
        for field in _ENTITY_FIELDS:
            value = entity.get(field)
            if not isinstance(value, str) or not value:
                continue
            # Display names are plain words ("Meta", "Google"); match whole
            # words so pip's "metadata" is not a hit. The other fields carry
            # punctuation and are matched as substrings.
            pattern = _word(value) if field == "display_name" else _substring(value)
            needles.append((f"{key} {field}", pattern))
        for person in entity.get("staff") or []:
            if not isinstance(person, dict):
                continue
            for field in ("name", "email"):
                value = person.get(field)
                if isinstance(value, str) and value.strip():
                    needles.append((f"{key} staff_{field}", _substring(value.strip())))
    return needles


def scan_text(text: str, needles: list[tuple[str, re.Pattern]]) -> list[str]:
    """Labels of every needle present in ``text``, with a short excerpt."""
    findings = []
    for label, pattern in needles:
        match = pattern.search(text)
        if match is None:
            continue
        start = max(0, match.start() - 30)
        end = min(len(text), match.end() + 30)
        excerpt = text[start:end].replace("\n", "\\n")
        findings.append(f"{label}: {excerpt!r}")
    return findings


def scan_outputs(outputs, needles: list[tuple[str, re.Pattern]]) -> list[str]:
    """One line per hit: ``output <i> <label>: <excerpt>``."""
    findings = []
    for index, output in enumerate(outputs):
        text = output if isinstance(output, str) else ""
        if not text:
            continue
        for line in scan_text(text, needles):
            findings.append(f"output {index} {line}")
    return findings


def trajectory_outputs(events) -> list[str]:
    """Tool outputs from trajectory events (replayed and live), in order."""
    return [
        event.get("output") or ""
        for event in events
        if isinstance(event, dict) and event.get("role") == "tool"
    ]
