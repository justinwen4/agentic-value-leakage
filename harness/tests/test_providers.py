"""Prompt-cache markers and usage accounting on the Chat Completions provider."""
from __future__ import annotations

import pytest
from openai.types.chat import ChatCompletion

from harness.grade import usage_totals
from harness.providers.openai_compat import OpenAICompatProvider

EPHEMERAL = {"type": "ephemeral"}

MESSAGES = [
    {"role": "system", "content": "You are a software engineer."},
    {"role": "user", "content": "Make the test pass."},
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "bash", "arguments": "{\"cmd\": \"ls\"}"}}],
    },
    {"role": "tool", "tool_call_id": "c1", "content": "README.md\nexit_code: 0"},
]


class _FakeCompletions:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return ChatCompletion.model_validate({
            "id": "r1",
            "object": "chat.completion",
            "created": 0,
            "model": kwargs["model"],
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "done"},
            }],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 5,
                "total_tokens": 125,
                "cost": 0.0012,
                "prompt_tokens_details": {"cached_tokens": 100},
            },
        })


class _FakeClient:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()
        self.chat = self


def _send(model: str, monkeypatch) -> tuple[dict, object]:
    monkeypatch.setenv("FAKE_KEY", "x")
    provider = OpenAICompatProvider(base_url=None, api_key_env="FAKE_KEY", model=model, temperature=1.0)
    client = _FakeClient()
    provider._client = client
    resp = provider.complete(MESSAGES, [])
    (request,) = client.completions.requests
    return request, resp


def _markers(message: dict) -> list[dict]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [part["cache_control"] for part in content if "cache_control" in part]


def test_anthropic_ids_mark_the_system_and_last_message(monkeypatch):
    request, _ = _send("anthropic/claude-opus-4.8", monkeypatch)
    sent = request["messages"]
    assert [_markers(m) for m in sent] == [[EPHEMERAL], [], [], [EPHEMERAL]]
    assert sent[0]["content"] == [{"type": "text", "text": MESSAGES[0]["content"], "cache_control": EPHEMERAL}]
    assert sent[-1]["content"] == [{"type": "text", "text": MESSAGES[-1]["content"], "cache_control": EPHEMERAL}]
    assert sent[-1]["tool_call_id"] == "c1"
    assert sent[1:3] == MESSAGES[1:3]
    assert isinstance(MESSAGES[0]["content"], str) and isinstance(MESSAGES[-1]["content"], str)
    assert request["extra_body"] == {"usage": {"include": True}}


@pytest.mark.parametrize("model", ["openai/gpt-5.5", "google/gemini-3.1-pro-preview"])
def test_other_ids_send_no_markers(model, monkeypatch):
    request, _ = _send(model, monkeypatch)
    assert request["messages"] == MESSAGES
    assert all(_markers(m) == [] for m in request["messages"])
    assert request["extra_body"] == {"usage": {"include": True}}


def test_usage_is_stored_whole_and_totalled(monkeypatch):
    _, resp = _send("anthropic/claude-opus-4.8", monkeypatch)
    assert resp.usage["cost"] == 0.0012
    assert resp.usage["prompt_tokens_details"]["cached_tokens"] == 100
    anthropic_style = {"prompt_tokens": 50, "completion_tokens": 2, "cache_read_input_tokens": 40, "cost": 0.0008}
    totals = usage_totals([
        {"role": "meta", "usage": resp.usage},
        {"role": "meta", "usage": anthropic_style},
    ])
    assert totals["input_tokens"] == 170
    assert totals["cached_input_tokens"] == 140
    assert totals["provider_cost_usd"] == pytest.approx(0.002)
    assert usage_totals([{"role": "meta", "usage": {"prompt_tokens": 1}}])["provider_cost_usd"] is None
