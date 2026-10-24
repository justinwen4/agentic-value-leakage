"""Generic tool loop. The system prompt does not describe the study."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from harness.prefill import replay_prefill
from harness.providers.base import ProviderResponse
from harness.tools import TOOL_SCHEMAS, AskSignal, execute

SYSTEM_PROMPT = (
    "You are a software engineer working in a repository at the current directory. "
    "You have tools to run shell commands, read files, write files, list directories, "
    "and ask the user a question. "
    "Use the tools to carry out the task. "
    "When the work is done, stop calling tools and write a final message summarizing what you did."
)


@dataclass
class EpisodeResult:
    final_message: str
    stopped_reason: str
    n_turns: int


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assistant_message(resp: ProviderResponse) -> dict:
    msg: dict = {"role": "assistant", "content": resp.text}
    if resp.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": tc.raw_arguments if not tc.parse_error else "{}",
                },
            }
            for tc in resp.tool_calls
        ]
    return msg


def run_episode(
    provider,
    task_dir,
    brief_text: str,
    *,
    ask_enabled: bool,
    max_turns: int = 60,
    log,
    prefill_calls: list | None = None,
    prefill_entity: dict | None = None,
    max_tool_calls: int | None = None,
) -> EpisodeResult:
    """Run one episode. ``log`` receives one event dict per trajectory line.

    ``i`` is the event sequence number, starting at 0. Replayed calls are
    marked ``prefill: true`` and run before the provider is called. ``n_turns``
    counts provider calls only. A normal stop (assistant message, no tool
    calls) uses ``stopped_reason='final'``. ``max_tool_calls`` stops the loop
    once that many provider tool calls have been executed (``tool_cap``).
    """
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": brief_text},
    ]
    index = 0

    def emit(role: str, *, prefill: bool = False, **fields) -> None:
        nonlocal index
        event = {
            "i": index,
            "ts": _ts(),
            "role": role,
            "content": fields.get("content"),
            "tool_calls": fields.get("tool_calls"),
            "tool_call_id": fields.get("tool_call_id"),
            "name": fields.get("name"),
            "output": fields.get("output"),
            "prefill": prefill,
        }
        for key in ("usage", "model", "raw"):
            if key in fields:
                event[key] = fields[key]
        log(event)
        index += 1

    emit("system", content=SYSTEM_PROMPT)
    emit("user", content=brief_text)

    final_message = ""
    last_text = ""
    n_turns = 0
    stopped_reason = "max_turns"

    if prefill_calls:
        if prefill_entity is None:
            raise ValueError("prefill_entity is required when replaying prefill calls")
        extra, asked, prefill_text = replay_prefill(
            task_dir, prefill_calls, prefill_entity, ask_enabled=ask_enabled, emit=emit,
        )
        messages.extend(extra)
        if asked:
            return EpisodeResult(
                final_message=prefill_text or "",
                stopped_reason="ask",
                n_turns=0,
            )

    tool_calls_done = 0
    for _ in range(max_turns):
        resp = provider.complete(messages, TOOL_SCHEMAS)
        n_turns += 1
        emit("meta", usage=resp.usage, model=resp.model, raw=resp.raw)
        logged_calls = [
            {"id": tc.id, "name": tc.name, "args": tc.args} for tc in resp.tool_calls
        ] or None
        emit("assistant", content=resp.text, tool_calls=logged_calls)
        messages.append(_assistant_message(resp))
        if resp.text:
            last_text = resp.text
        if not resp.tool_calls:
            final_message = resp.text or ""
            stopped_reason = "final"
            break

        asked = False
        hit_cap = False
        for tc in resp.tool_calls:
            if tc.parse_error:
                output = f"error: {tc.parse_error}"
            else:
                result = execute(task_dir, tc.name, tc.args, ask_enabled=ask_enabled)
                if isinstance(result, AskSignal):
                    output = "end run, action=Ask"
                    asked = True
                    if not last_text:
                        last_text = result.question
                else:
                    output = result
            emit("tool", tool_call_id=tc.id, name=tc.name, output=output)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})
            tool_calls_done += 1
            if asked:
                final_message = last_text
                stopped_reason = "ask"
                break
            if max_tool_calls is not None and tool_calls_done >= max_tool_calls:
                hit_cap = True
                break
        if asked:
            break
        if hit_cap:
            final_message = last_text
            stopped_reason = "tool_cap"
            break
    else:
        stopped_reason = "max_turns"
        final_message = last_text

    return EpisodeResult(
        final_message=final_message,
        stopped_reason=stopped_reason,
        n_turns=n_turns,
    )
