"""Provider response types shared by the agent loop."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict
    raw_arguments: str = "{}"
    parse_error: str | None = None


@dataclass
class ProviderResponse:
    text: str | None
    tool_calls: list[ToolCall]
    raw: dict
    usage: dict
    model: str
    upstream: str | None = None


class Provider(Protocol):
    model: str

    def complete(self, messages: list, tools: list) -> ProviderResponse:
        """One chat completion with tool definitions."""
