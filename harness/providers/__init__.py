"""Construct a provider from a model config dict. Only ``openai_compat`` for now."""
from __future__ import annotations

from harness.providers.openai_compat import OpenAICompatProvider


def make_provider(cfg: dict):
    kind = cfg.get("provider")
    if kind == "openai_compat":
        headers = cfg.get("extra_headers") or None
        order = cfg.get("provider_order") or None
        if order is not None and (not isinstance(order, list) or not all(isinstance(p, str) for p in order)):
            raise ValueError(f"provider_order must be a list of provider names, got {order!r}")
        return OpenAICompatProvider(
            base_url=cfg.get("base_url") or None,
            api_key_env=cfg["api_key_env"],
            model=cfg["model"],
            temperature=float(cfg.get("temperature", 1.0)),
            extra_headers=headers,
            provider_order=order,
        )
    raise ValueError(f"unknown provider: {kind!r}")
