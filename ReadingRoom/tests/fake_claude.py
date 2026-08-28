"""A fake `claude` for the offline suite. Replays canned replies, spawns nothing.

The real CLI costs quota and needs a network. Groups C, E and F are about what
the harness does with a reply, not about getting a good one, so they run against
this instead -- which also lets a test ask for a reply no real model would
produce (a truncated JSON, a `tool_use` block, a hang).

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

MODES
    reply      emit FAKE_CLAUDE_REPLY as a normal assistant text block
    raw        emit FAKE_CLAUDE_STREAM verbatim, byte for byte
    tool_use   emit a tool_use block  (A1)
    tool_result emit a tool_result block (A2)
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


def emit(event: dict) -> None:
    sys.stdout.write(json.dumps(event) + "\n")


def assistant(text: str) -> dict:
    return {"type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


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

    emit({"type": "system", "subtype": "init", "tools": [], "mcp_servers": []})

    if mode == "tool_use":
        emit({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "tu_1", "name": "Read",
             "input": {"file_path": "../data/ground_truth.csv"}}]}})
    elif mode == "tool_result":
        emit({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tu_1", "content": "paper_id,label"}]}})
    elif mode == "reply":
        emit(assistant(os.environ.get("FAKE_CLAUDE_REPLY", "")))
    else:                                                       # echo
        match = TOKEN.search(prompt)
        token = match.group(1) if match else "unknown"
        emit(assistant(json.dumps({
            "decision": "no",
            "reasoning": "Cluster randomized trial with parallel arms; no exclusion applies.",
            "promptbook_evidence": "E1",
            "confidence": 0.82,
            "paper_id": token,
        })))

    emit({"type": "result", "subtype": "success", "is_error": False})
    return int(os.environ.get("FAKE_CLAUDE_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main())
