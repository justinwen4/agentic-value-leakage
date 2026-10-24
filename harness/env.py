"""Load KEY=VALUE lines from the project-root ``.env``.

Sets ``os.environ`` only for keys that are not already set. Blank lines and
``#`` comments are ignored. No third-party dotenv dependency.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: Path | None = None) -> None:
    if path is None:
        path = Path(__file__).resolve().parents[1] / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()
