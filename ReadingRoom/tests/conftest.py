"""Shared fixtures for the Reading Room suite.

Offline and free by construction: nothing here spawns `claude`, opens a socket,
or touches `data/review.db`. Group A is pure argv/path/JSON assertions and group
B is CSV plus a throwaway SQLite file, so the whole suite runs in CI on every
commit -- which is the point. A wall that is only checked when someone remembers
to check it is not a wall.

The one thing every fixture is careful about: **nothing writes inside the repo.**
`tmp_path` lives under the OS temp dir, which is outside both the repo and
OneDrive, so a test cannot accidentally create the very CLAUDE.md or scratch
directory that the code under test is supposed to refuse.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db                # noqa: E402
import reading_room as rr  # noqa: E402


# ------------------------------------------------------------------ group A


@pytest.fixture
def clean_room(tmp_path):
    """A prepared, verified Room under tmp_path.

    `repo_root` is the real repo: the point of the fixture is that a genuine
    temp dir passes the genuine A3 check, not that a stubbed one does.
    """
    return rr.prepare_room(tmp_path / "room", repo_root=REPO_ROOT)


@pytest.fixture
def settings_file(tmp_path):
    """Write a settings dict to disk and hand back the path."""
    def _write(settings: dict, name: str = "settings.json") -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(settings), encoding="utf-8")
        return path
    return _write


def stream(*events: dict) -> str:
    """Join dicts into the newline-delimited JSON the CLI emits."""
    return "\n".join(json.dumps(e) for e in events) + "\n"


def assistant_text(text: str) -> dict:
    """A normal, tool-free assistant event -- the shape a good paper produces."""
    return {"type": "assistant",
            "message": {"role": "assistant",
                        "content": [{"type": "text", "text": text}]}}


# ------------------------------------------------------------------ group B


def label(paper_id: str, *, split: str = db.SPLIT_BUILD,
          exclusion_reason: str | None = None,
          power: str | None = "yes", stats: str | None = "yes") -> dict:
    """One `validation_labels` row, shaped the way `load_labels` returns them.

    Defaults describe the common case: a build-split paper the humans kept
    (no exclusion reason) and labelled for both analysis tasks.
    """
    return {"paper_id": paper_id, "split": split,
            "exclusion_reason": exclusion_reason, "power": power, "stats": stats}


@pytest.fixture
def rounds_csv(tmp_path):
    """Write a `build_rounds.csv` from (paper_id, task, round, stratum) tuples."""
    def _write(rows: list[tuple], name: str = "build_rounds.csv") -> Path:
        path = tmp_path / name
        lines = ["paper_id,task,round,stratum"]
        lines += [",".join(str(c) for c in row) for row in rows]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
    return _write


@pytest.fixture
def cache_dir(tmp_path):
    """An extracted-text cache holding a JSON file for each named paper."""
    def _make(paper_ids, name: str = "extracted_text") -> Path:
        path = tmp_path / name
        path.mkdir(exist_ok=True)
        for paper_id in paper_ids:
            (path / f"{paper_id}.json").write_text(
                json.dumps({"paper_id": paper_id, "text": "Methods. n = 40 clusters."}),
                encoding="utf-8")
        return path
    return _make


# ------------------------------------------------------- the fake CLI (C/E/F)


FAKE_CLAUDE = Path(__file__).resolve().parent / "fake_claude.py"

# The harness drops every environment variable it does not recognise, which is
# the point of `child_env` -- so the fake's controls have to be allowlisted for
# the duration of a test or they never reach it.
FAKE_ENV_VARS = ("FAKE_CLAUDE_MODE", "FAKE_CLAUDE_REPLY", "FAKE_CLAUDE_STREAM",
                 "FAKE_CLAUDE_EXIT", "FAKE_CLAUDE_SLEEP", "FAKE_CLAUDE_LOG",
                 "FAKE_CLAUDE_INIT", "FAKE_CLAUDE_RESULT", "FAKE_CLAUDE_USAGE")


class FakeClaude:
    """Handle on the fake CLI: set its behaviour, read back what it saw."""

    def __init__(self, path: Path, log_path: Path, monkeypatch):
        self.path = path                  # the shim, for --claude
        self.log_path = log_path
        self._monkeypatch = monkeypatch
        self.set(mode="echo")

    def set(self, *, mode: str = "echo", reply: str | None = None,
            stream: str | None = None, exit_code: int = 0,
            sleep: float = 0.0, init: dict | None = None,
            result: dict | None = None, usage: dict | None = None) -> None:
        """Drive the fake. `init`/`result`/`usage` are merged onto its defaults.

        A `None` *value* inside one of those dicts deletes that key, which is how
        group G asks for "the CLI omitted this field" as opposed to "the CLI sent
        it as null". Only the first shape happens in a real stream.
        """
        self._monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
        self._monkeypatch.setenv("FAKE_CLAUDE_EXIT", str(exit_code))
        self._monkeypatch.setenv("FAKE_CLAUDE_SLEEP", str(sleep))
        self._monkeypatch.setenv("FAKE_CLAUDE_LOG", str(self.log_path))
        self._monkeypatch.setenv("FAKE_CLAUDE_REPLY", reply or "")
        self._monkeypatch.setenv("FAKE_CLAUDE_STREAM", stream or "")
        self._monkeypatch.setenv("FAKE_CLAUDE_INIT", json.dumps(init or {}))
        self._monkeypatch.setenv("FAKE_CLAUDE_RESULT", json.dumps(result or {}))
        self._monkeypatch.setenv("FAKE_CLAUDE_USAGE", json.dumps(usage or {}))

    def invocations(self) -> list[dict]:
        """One dict per spawn: the argv, cwd, env keys and prompt head it saw."""
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in
                self.log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """Put a fake `claude` on PATH and let the harness's own env allowlist through.

    A shim rather than a monkeypatched `subprocess.run`, deliberately: the thing
    most worth testing is that a *real child process* sees the locked-down
    environment and the empty cwd, and a patched function call would prove
    nothing about either.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    if sys.platform == "win32":
        shim = bin_dir / "claude.cmd"
        shim.write_text(f'@echo off\r\n"{sys.executable}" "{FAKE_CLAUDE}" %*\r\n',
                        encoding="utf-8")
    else:
        shim = bin_dir / "claude"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_CLAUDE}" "$@"\n',
                        encoding="utf-8")
        shim.chmod(0o755)

    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr(rr, "ENV_ALLOWLIST", rr.ENV_ALLOWLIST + FAKE_ENV_VARS)
    return FakeClaude(shim, tmp_path / "fake_claude.log", monkeypatch)


@pytest.fixture
def promptbook_text():
    """A promptbook small enough to read in a failure message, with real rule ids."""
    return ("# Exclusion rules\n\n"
            "1. **E1. Not a cluster-randomized trial** -- exclude.\n"
            "2. **E2. Not a full report** -- exclude.\n"
            "3. **E3. Stepped-wedge design** -- exclude.\n")


@pytest.fixture
def promptbooks(tmp_path):
    """A `promptbooks/` tree under a fake repo root; returns that root.

    `current=None` writes no CURRENT file at all, which is the B9 case where
    nothing names the promptbook in force.
    """
    def _make(versions: dict[str, list[str]], current: str | None = "v1") -> Path:
        root = tmp_path / "fakerepo"
        books = root / "promptbooks"
        books.mkdir(parents=True, exist_ok=True)
        for version, tasks in versions.items():
            directory = books / version
            directory.mkdir(exist_ok=True)
            for task in tasks:
                (directory / f"{task}.md").write_text(
                    f"# {task} {version}\n\nE1. A rule.\n", encoding="utf-8")
        if current is not None:
            (books / "CURRENT").write_text(current + "\n", encoding="utf-8")
        return root
    return _make
