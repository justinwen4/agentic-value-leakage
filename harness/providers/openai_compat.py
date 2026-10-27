"""One Chat Completions provider for api.openai.com and OpenAI-compatible hosts.

``base_url`` omitted or empty talks to the OpenAI default. Set it to
``https://openrouter.ai/api/v1`` (and ``api_key_env`` to the matching variable
name) to use OpenRouter. Model ids come from the caller, not from this module.

Prompt caching is on for every model. An ``anthropic/`` model id gets
``cache_control: {"type": "ephemeral"}`` on the system message and on the last
message of each request (OpenRouter passes it through on content parts);
OpenAI and Google models cache automatically and get nothing extra. Every
request asks for ``usage: {"include": true}`` so OpenRouter returns
``usage.cost`` and the cached-token details. Caching changes cost and
latency, not outputs.

``provider_order`` (optional, per model in the config) sends OpenRouter's
routing object ``provider: {order: [...], allow_fallbacks: true}``, so the
named upstream serves every request it can and an unavailable one still
routes elsewhere. It is for cache stability: the weights are the same on
every upstream. The upstream OpenRouter reports for each response is kept as
``ProviderResponse.upstream``.
"""
from __future__ import annotations

import json
import os
import sys
import time

from openai import APIConnectionError, OpenAI

from harness.providers.base import ProviderResponse, ToolCall

_MAX_TRIES = 5
_EPHEMERAL = {"type": "ephemeral"}


def cache_mode(model: str) -> str:
    """``anthropic_ephemeral`` for an ``anthropic/`` id, else ``automatic``."""
    return "anthropic_ephemeral" if model.startswith("anthropic/") else "automatic"


def _with_cache_marker(message: dict) -> dict:
    """A copy of ``message`` whose last content part carries ``cache_control``.

    String content becomes a one-part list. A message with no content (an
    assistant turn that only calls tools) is returned unchanged.
    """
    content = message.get("content")
    if isinstance(content, str) and content:
        parts = [{"type": "text", "text": content}]
    elif isinstance(content, list) and content:
        parts = [dict(part) for part in content]
    else:
        return message
    parts[-1]["cache_control"] = dict(_EPHEMERAL)
    return {**message, "content": parts}


def cache_messages(model: str, messages: list[dict]) -> list[dict]:
    """The request's messages with cache markers for ``model``; input is not mutated."""
    out = list(messages)
    if cache_mode(model) != "anthropic_ephemeral" or not out:
        return out
    for index, message in enumerate(out):
        if message.get("role") == "system":
            out[index] = _with_cache_marker(message)
    out[-1] = _with_cache_marker(out[-1])
    return out


def _parse_arguments(raw: object) -> tuple[dict, str | None, str]:
    """Return ``(args, parse_error, arguments_json_to_replay)``.

    A parse failure is reported back to the model as a tool error by the agent
    loop. The replayed arguments stay valid JSON so the next request is well formed.
    """
    if raw is None:
        return {}, None, "{}"
    if isinstance(raw, dict):
        return raw, None, json.dumps(raw)
    if not isinstance(raw, str):
        return {}, f"arguments were {type(raw).__name__}, expected a JSON object", "{}"
    text = raw.strip()
    if text == "":
        return {}, None, "{}"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"could not parse tool arguments as JSON: {exc}. arguments were: {raw}", "{}"
    if not isinstance(parsed, dict):
        return {}, f"tool arguments must be a JSON object, got {type(parsed).__name__}", "{}"
    return parsed, None, text


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, APIConnectionError):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status == 429 or 500 <= status <= 599):
        return True
    module = type(exc).__module__
    if module.startswith("httpx") or module.startswith("httpcore"):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None) if response is not None else None
        if status is None:
            return True
        return status == 429 or status >= 500
    return False


class OpenAICompatProvider:
    def __init__(
        self,
        *,
        base_url: str | None,
        api_key_env: str,
        model: str,
        temperature: float,
        extra_headers: dict | None = None,
        provider_order: list[str] | None = None,
    ) -> None:
        key = os.environ.get(api_key_env, "")
        if not key:
            raise RuntimeError(f"environment variable {api_key_env} is not set")
        kwargs: dict = {"api_key": key, "max_retries": 0, "timeout": 180.0}
        if base_url:
            kwargs["base_url"] = base_url
        if extra_headers:
            kwargs["default_headers"] = dict(extra_headers)
        self.model = model
        self.temperature = temperature
        self.cache = cache_mode(model)
        self._extra_body: dict = {"usage": {"include": True}}
        if provider_order:
            self._extra_body["provider"] = {"order": list(provider_order), "allow_fallbacks": True}
        self._client = OpenAI(**kwargs)

    def complete(self, messages: list, tools: list) -> ProviderResponse:
        payload_tools = [
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec["description"],
                    "parameters": spec["parameters"],
                },
            }
            for spec in tools
        ]
        last: Exception | None = None
        for attempt in range(_MAX_TRIES):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=cache_messages(self.model, messages),
                    tools=payload_tools,
                    tool_choice="auto",
                    temperature=self.temperature,
                    extra_body=self._extra_body,
                )
                return self._parse(resp)
            except Exception as exc:
                last = exc
                if attempt == _MAX_TRIES - 1 or not _is_transient(exc):
                    raise
                status = getattr(exc, "status_code", None)
                print(
                    f"provider transient error ({type(exc).__name__} status={status}), "
                    f"retry {attempt + 1}/{_MAX_TRIES}",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(2 ** attempt)
        assert last is not None
        raise last

    def _parse(self, resp) -> ProviderResponse:
        raw = resp.model_dump(mode="json")
        usage = raw.get("usage") or {}
        choices = resp.choices or []
        if not choices:
            raise RuntimeError("provider returned no choices")
        msg = choices[0].message
        calls: list[ToolCall] = []
        for index, tc in enumerate(msg.tool_calls or []):
            fn = getattr(tc, "function", None)
            if fn is None:
                calls.append(ToolCall(
                    id=getattr(tc, "id", None) or f"call_{index}",
                    name="",
                    args={},
                    raw_arguments="{}",
                    parse_error="tool call had no function payload",
                ))
                continue
            args, err, replay = _parse_arguments(getattr(fn, "arguments", None))
            calls.append(ToolCall(
                id=getattr(tc, "id", None) or f"call_{index}",
                name=getattr(fn, "name", None) or "",
                args=args,
                raw_arguments=replay,
                parse_error=err,
            ))
        return ProviderResponse(
            text=msg.content,
            tool_calls=calls,
            raw=raw,
            usage=usage if isinstance(usage, dict) else {},
            model=self.model,
            upstream=raw.get("provider") if isinstance(raw.get("provider"), str) else None,
        )
