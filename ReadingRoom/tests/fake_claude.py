"""A fake `claude` for the offline suite. Replays canned replies, spawns nothing.

The real CLI costs quota and needs a network. Groups C, E, F and G are about what
the harness does with a reply, not about getting a good one, so they run against
this instead -- which also lets a test ask for a reply no real model would
produce (a truncated JSON, a `tool_use` block, a hang, a 12,000-token usage
block).

**Every field the real CLI emits and the harness reads must be forgeable here**,
or the offline suite is testing a shape the real stream does not have -- which is
exactly the failure both live probes exposed. The defaults below are copied from
a real CLI 2.1.197 stream, so a test that overrides nothing gets the real shape.

HOW IT IS DRIVEN
    Entirely through the environment, because that is all the harness lets
    through: it builds the argv itself and its env allowlist is fixed. The suite
    adds these names to `ENV_ALLOWLIST` for the duration of a test.

        FAKE_CLAUDE_MODE     what to do (see MODES below)
        FAKE_CLAUDE_REPLY    the assistant text to emit, for mode=reply
        FAKE_CLAUDE_STREAM   verbatim stdout, for mode=raw
        FAKE_CLAUDE_EXIT     exit code, default 0
        FAKE_CLAUDE_SLEEP    seconds to sleep before replying (F9)
        FAKE_CLAUDE_LOG      file to append one line per invocation to, so a
                             test can assert on the argv and cwd it really saw
        FAKE_CLAUDE_INIT     JSON dict merged into the `system/init` event
                             (G2/G3/G4/A14 -- drop a field by setting it null)
        FAKE_CLAUDE_RESULT   JSON dict merged into the `result` event
                             (G5/G7/G8/G9/G12 -- same null convention)
        FAKE_CLAUDE_USAGE    JSON dict merged into `result.usage` (A17/G7)

MODES
    reply      emit FAKE_CLAUDE_REPLY as a normal assistant text block
    raw        emit FAKE_CLAUDE_STREAM verbatim, byte for byte
    tool_use   emit a tool_use block  (A1)
    tool_result emit a tool_result block (A2)
    no_result  emit init + assistant and then stop, as a killed process does (G5)
    echo       emit a valid Decision echoing the token found in the prompt --
               the happy path, used by every test that needs a round to succeed
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

TOKEN = re.compile(r"BEGIN PAPER ([0-9a-f]{8,})")

# Copied from a real CLI 2.1.197 stream. A test that overrides nothing sees the
# shape the real CLI produces, so "passes offline" means something.
CLI_VERSION = "2.1.197"
MODEL = "claude-sonnet-5"

# A17. The pinned system prompt measured 183 billed input tokens on the two-word
# preflight probe; the CLI's default agentic persona measured 12,198. The default
# here is the sealed number, so a test has to *ask* for the leak.
DEFAULT_USAGE = {
    "input_tokens": 4,
    "cache_creation_input_tokens": 179,
    "cache_read_input_tokens": 0,
    "output_tokens": 96,
    "service_tier": "standard",
    "speed": "standard",
}

DEFAULT_INIT = {
    "type": "system",
    "subtype": "init",
    "tools": [],
    "mcp_servers": [],
    "model": MODEL,
    "claude_code_version": CLI_VERSION,
    "permissionMode": "default",
    "session_id": "fake-session-0001",
}

DEFAULT_RESULT = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "session_id": "fake-session-0001",
    "duration_ms": 4210,
    "duration_api_ms": 4008,
    "ttft_ms": 612,
    "num_turns": 1,
    "stop_reason": "end_turn",
    "terminal_reason": "completed",
    "total_cost_usd": 0.0121,
    "permission_denials": [],
    "fast_mode_state": "off",
    "service_tier": "standard",
    "inference_geo": "us",
    "context_window": 200000,
    "max_output_tokens": 64000,
}


def emit(event: dict) -> None:
    sys.stdout.write(json.dumps(event) + "\n")


def assistant(text: str, *, request_id: str = "req_fake_0001") -> dict:
    return {"type": "assistant",
            "request_id": request_id,
            "message": {"role": "assistant", "model": MODEL,
                        "content": [{"type": "text", "text": text}]}}


def overlay(base: dict, var: str) -> dict:
    """Merge a JSON env override onto a default event.

    `null` deletes the key rather than setting it to None, which is what the G
    cases need: "the CLI omitted `claude_code_version`" is a different stream
    from "the CLI sent `claude_code_version: null`", and only the first one
    happens in practice.
    """
    raw = os.environ.get(var, "")
    if not raw.strip():
        return dict(base)
    merged = dict(base)
    for key, value in json.loads(raw).items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def main() -> int:
    mode = os.environ.get("FAKE_CLAUDE_MODE", "echo")
    prompt = sys.stdin.read()

    log = os.environ.get("FAKE_CLAUDE_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "argv": sys.argv[1:], "cwd": os.getcwd(),
                "env_keys": sorted(os.environ),
                "prompt_chars": len(prompt),
                "prompt_head": prompt[:200],
            }) + "\n")

    sleep = float(os.environ.get("FAKE_CLAUDE_SLEEP", "0"))
    if sleep:
        time.sleep(sleep)

    if mode == "raw":
        sys.stdout.write(os.environ.get("FAKE_CLAUDE_STREAM", ""))
        return int(os.environ.get("FAKE_CLAUDE_EXIT", "0"))

    emit(overlay(DEFAULT_INIT, "FAKE_CLAUDE_INIT"))

    if mode == "tool_use":
        emit({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "tu_1", "name": "Read",
             "input": {"file_path": "../data/ground_truth.csv"}}]}})
    elif mode == "tool_result":
        emit({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tu_1", "content": "paper_id,label"}]}})
    elif mode == "reply":
        emit(assistant(os.environ.get("FAKE_CLAUDE_REPLY", "")))
    else:                                                       # echo, no_result
        match = TOKEN.search(prompt)
        token = match.group(1) if match else "unknown"
        emit(assistant(json.dumps({
            "decision": "no",
            "reasoning": "Cluster randomized trial with parallel arms; no exclusion applies.",
            "promptbook_evidence": "E1",
            "confidence": 0.82,
            "paper_id": token,
        })))

    # G5. A killed or timed-out process never reaches its result event, and the
    # harness must retry rather than invent a duration, a usage or a cost.
    if mode != "no_result":
        # Usage is filled in first so that FAKE_CLAUDE_RESULT={"usage": null} can
        # delete the whole block -- G7's "the CLI sent no usage at all", which is
        # a different stream from one whose numbers happen to be zero.
        result = dict(DEFAULT_RESULT)
        result["usage"] = overlay(DEFAULT_USAGE, "FAKE_CLAUDE_USAGE")
        emit(overlay(result, "FAKE_CLAUDE_RESULT"))

    return int(os.environ.get("FAKE_CLAUDE_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main())
