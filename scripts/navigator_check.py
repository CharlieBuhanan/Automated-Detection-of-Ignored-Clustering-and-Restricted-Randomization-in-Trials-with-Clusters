"""NaviGator (UF) API key check. The USER runs this; Claude Code must not.

Reads NAVIGATOR_API_KEY from .env and never prints it (any key-like text in
server replies is redacted too).

  python scripts/navigator_check.py models                  # free: list models + key budget info
  python scripts/navigator_check.py local --model NAME       # 1 tiny call to a local HiPerGator model
  python scripts/navigator_check.py claude [--model NAME]    # 1 tiny call to a cloud Claude model
  python scripts/navigator_check.py claude --messages        #   ...also try the Anthropic-style /v1/messages

Each model call asks for a one-word reply (max 16 output tokens), so cost is a fraction of a cent.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://api.ai.it.ufl.edu"
PROMPT = "Reply with the single word OK."
MAX_TOKENS = 16

HINTS = {
    401: "key rejected, or this model is not enabled for this key",
    403: "key is valid but not allowed this model (team/approval issue)",
    404: "model name or endpoint not found; check the name from `models`",
    429: "rate limit or budget exhausted",
}


def redact(text: str, key: str) -> str:
    text = text.replace(key, "<KEY>")
    return re.sub(r"sk-[A-Za-z0-9_\-]{4,}", "sk-<redacted>", text)


def call(method: str, path: str, key: str, body: dict | None = None,
         headers: dict | None = None) -> tuple[int | None, dict, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        return None, {}, f"network error: {e.reason}"


def report_failure(status: int | None, text: str, key: str) -> None:
    hint = HINTS.get(status or 0, "")
    if status == 400 and re.search(r"budget|credit|spend", text, re.I):
        hint = "looks like no credits / budget for this model"
    print(f"  FAILED{f' ({hint})' if hint else ''}")
    print("  server said:", redact(text[:600], key))


def list_models(key: str) -> list[str] | None:
    status, _, text = call("GET", "/v1/models", key)
    print(f"GET /v1/models -> {status}")
    if status != 200:
        report_failure(status, text, key)
        return None
    return sorted(m["id"] for m in json.loads(text).get("data", []))


def cmd_models(key: str) -> int:
    ids = list_models(key)
    if ids is None:
        return 1
    claude = [i for i in ids if "claude" in i.lower()]
    print(f"  {len(ids)} models visible to this key, {len(claude)} Claude (marked *):")
    for i in ids:
        print(f"  {'*' if i in claude else ' '} {i}")

    status, _, text = call("GET", "/key/info", key)
    print(f"\nGET /key/info -> {status}")
    if status == 200:
        info = json.loads(text).get("info", {})
        for f in ("spend", "max_budget", "budget_duration", "budget_reset_at",
                  "team_id", "models", "expires"):
            if f in info:
                print(f"  {f}: {redact(str(info[f]), key)}")
    else:
        print("  (budget info not exposed:", redact(text[:200], key), ")")
    print("\nNote: a model being listed does not prove a call works; run `local` / `claude` next.")
    return 0


def chat(key: str, model: str) -> bool:
    body = {"model": model, "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": PROMPT}]}
    status, headers, text = call("POST", "/v1/chat/completions", key, body)
    print(f"POST /v1/chat/completions  model={model} -> {status}")
    if status != 200:
        report_failure(status, text, key)
        return False
    d = json.loads(text)
    print("  reply:", repr(d["choices"][0]["message"].get("content")))
    print("  usage:", d.get("usage"))
    cost = {k: v for k, v in headers.items() if "cost" in k.lower()}
    if cost:
        print("  cost header:", cost)
    return True


def messages(key: str, model: str) -> bool:
    body = {"model": model, "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": PROMPT}]}
    status, _, text = call("POST", "/v1/messages", key, body,
                           {"anthropic-version": "2023-06-01", "x-api-key": key})
    print(f"POST /v1/messages (Anthropic-style)  model={model} -> {status}")
    if status != 200:
        report_failure(status, text, key)
        return False
    d = json.loads(text)
    print("  reply:", repr("".join(b.get("text", "") for b in d.get("content", []))))
    print("  usage:", d.get("usage"))
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["models", "local", "claude"])
    ap.add_argument("--model", help="exact model id from `models` (required for `local`)")
    ap.add_argument("--messages", action="store_true", help="claude: also test /v1/messages")
    ap.add_argument("--env-var", default="NAVIGATOR_API_KEY")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    key = os.getenv(args.env_var, "").strip()
    if not key:
        print(f"No {args.env_var} in .env. Add a line: {args.env_var}=<your key>")
        return 2

    if args.step == "models":
        return cmd_models(key)

    if args.step == "local":
        if not args.model:
            print("`local` needs --model; pick a non-Claude id from the `models` list.")
            return 2
        return 0 if chat(key, args.model) else 1

    model = args.model
    if not model:
        ids = list_models(key) or []
        claude = [i for i in ids if "claude" in i.lower()]
        if not claude:
            print("  No Claude models visible to this key (likely not enabled). "
                  "Pass --model to try one anyway.")
            return 1
        model = next((i for i in claude if "haiku" in i.lower()), claude[0])
        print(f"  auto-picked {model} (cheapest-looking Claude)\n")
    ok = chat(key, model)
    if args.messages:
        print()
        ok = messages(key, model) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
