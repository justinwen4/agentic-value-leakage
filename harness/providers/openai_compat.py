"""One Chat Completions provider for api.openai.com and OpenAI-compatible hosts.

``base_url`` omitted or empty talks to the OpenAI default. Set it to
``https://openrouter.ai/api/v1`` (and ``api_key_env`` to the matching variable
name) to use OpenRouter. Model ids come from the caller, not from this module.
"""
from __future__ import annotations

import json
import os
import sys
import time

from openai import APIConnectionError, OpenAI

from harness.providers.base import ProviderResponse, ToolCall

_MAX_TRIES = 5


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
                    messages=messages,
                    tools=payload_tools,
                    tool_choice="auto",
                    temperature=self.temperature,
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
        )
