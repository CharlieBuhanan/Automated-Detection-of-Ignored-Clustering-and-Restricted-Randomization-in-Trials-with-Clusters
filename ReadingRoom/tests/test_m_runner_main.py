"""Script-level coverage for deferred run selection and serial breach stopping."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import reading_room as rr


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "20_reading_room.py"
CHECKER = Path(__file__).resolve().parents[2] / "scripts" / "21_check_responses.py"


def load_runner_module():
    spec = importlib.util.spec_from_file_location("reading_room_runner_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_checker_module():
    spec = importlib.util.spec_from_file_location("reading_room_checker_test", CHECKER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_checker_uses_the_frozen_version_and_separates_versioned_runs(monkeypatch, tmp_path):
    checker = load_checker_module()
    books = tmp_path / "promptbooks" / "v1"
    books.mkdir(parents=True)
    (books / "data_analysis.md").write_text("# Rules\n\nD1. Rule.\n", encoding="utf-8")
    raw = tmp_path / "raw"
    legacy = raw / "data_analysis_r1"
    legacy.mkdir(parents=True)
    (legacy / "run_environment.json").write_text('{"promptbook_version": "v1"}', encoding="utf-8")
    (raw / "data_analysis_v2_r1").mkdir()

    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "RAW_ROOT", raw)

    version, _, rules = checker.promptbook_context_for_version("data_analysis", "v1")
    assert version == "v1" and rules["data_analysis"] == {"D1"}
    assert checker.locate_raw_dir("data_analysis", 1, "v1") == legacy
    assert checker.locate_raw_dir("data_analysis", 1, "v2") == raw / "data_analysis_v2_r1"


def test_main_resume_and_force_select_the_right_attempts(monkeypatch, tmp_path, capsys):
    """The CLI flags reach `main`, not merely the retry-state unit helper."""
    run = load_runner_module()
    paper = SimpleNamespace(paper_id="P1", text_path=tmp_path / "P1.json",
                            stratum="build")
    plan = SimpleNamespace(n=1, papers=[paper], skipped=[])
    raw_dir = tmp_path / "raw" / "exclusion_r1"
    prior = {"paper_id": "P1", "attempt": "1", "exit_code": "1",
             "token": "old", "raw_path": "old.jsonl"}

    monkeypatch.setattr(run, "RAW_ROOT", tmp_path / "raw")
    monkeypatch.setattr(run, "CHECKED_ROOT", tmp_path / "checked")
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setattr(run.rr, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(run, "read_csv", lambda path: [prior] if path.name == "index.csv" else [])
    monkeypatch.setattr(run.rr, "resolve_promptbook", lambda *a, **k: ("v2", tmp_path / "book.md", "E1"))
    monkeypatch.setattr(run.rr, "load_labels", lambda conn: [])
    monkeypatch.setattr(run.rr, "load_verdicts", lambda: {})
    monkeypatch.setattr(run.rr, "load_round", lambda *a, **k: plan)
    monkeypatch.setattr(run.db, "connect", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(run.rr, "read_paper_text", lambda path: SimpleNamespace(
        is_empty=False, refs_method="stripped", chars=10, refs_removed=0, notes="", text="text"))
    monkeypatch.setattr(run.rr, "check_round_text_preparation", lambda methods: None)

    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--task", "exclusion", "--round", "1", "--resume", "--dry-run"])
    assert run.main() == 0
    output = capsys.readouterr().out
    assert "--resume" in output and "1 to go" in output

    # Force selects a prior clean response too; resume would hold it awaiting its checker row.
    prior["exit_code"] = "0"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--task", "exclusion", "--round", "1", "--force", "--dry-run"])
    assert run.main() == 0
    assert "--force" in capsys.readouterr().out


def test_main_serial_breach_stops_before_the_next_paper(monkeypatch, tmp_path):
    """A tool-use response ends the actual script loop with later papers unspent."""
    run = load_runner_module()
    papers = [SimpleNamespace(paper_id=f"P{i}", text_path=tmp_path / f"P{i}.json", stratum="build")
              for i in (1, 2)]
    plan = SimpleNamespace(n=2, papers=papers, skipped=[])
    calls, writes = [], []
    room = SimpleNamespace(root=tmp_path / "room", settings_path=tmp_path / "settings.json")
    probe = SimpleNamespace(tools=[], input_tokens=1, claude_code_version="test")

    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setattr(run, "RAW_ROOT", tmp_path / "raw")
    monkeypatch.setattr(run, "CHECKED_ROOT", tmp_path / "checked")
    monkeypatch.setattr(run, "LEDGER", tmp_path / "ledger.csv")
    monkeypatch.setattr(run.rr, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(run, "read_csv", lambda path: [])
    monkeypatch.setattr(run, "write_csv", lambda *a: writes.append(a))
    monkeypatch.setattr(run, "now", lambda: "2026-08-28T00:00:00+00:00")
    monkeypatch.setattr(run.rr, "resolve_promptbook", lambda *a, **k: ("v2", tmp_path / "book.md", "E1"))
    monkeypatch.setattr(run.rr, "load_labels", lambda conn: [])
    monkeypatch.setattr(run.rr, "load_verdicts", lambda: {})
    monkeypatch.setattr(run.rr, "load_round", lambda *a, **k: plan)
    monkeypatch.setattr(run.db, "connect", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(run.rr, "read_paper_text", lambda path: SimpleNamespace(
        is_empty=False, refs_method="stripped", chars=10, refs_removed=0, notes="", text="text"))
    monkeypatch.setattr(run.rr, "check_round_text_preparation", lambda methods: None)
    monkeypatch.setattr(run.rr, "find_claude", lambda path: "claude")
    monkeypatch.setattr(run.rr, "prepare_room", lambda **k: room)
    monkeypatch.setattr(run.rr, "preflight", lambda *a, **k: probe)
    monkeypatch.setattr(run.rr, "build_prompt", lambda **k: "prompt")
    monkeypatch.setattr(run.rr, "new_token", lambda text: "token")
    monkeypatch.setattr(run.rr, "write_raw", lambda attempt, raw: tmp_path / "raw" / "first.jsonl")
    monkeypatch.setattr(run.rr, "assert_no_tools_offered", lambda *a, **k: None)
    monkeypatch.setattr(run.rr, "scan_stream_for_tools", lambda *a, **k: (_ for _ in ()).throw(rr.RoundDiscarded("tool used")))
    monkeypatch.setattr(run.rr, "stream_usage", lambda stdout: {})
    monkeypatch.setattr(run.rr, "paper_provenance", lambda stdout: {})
    monkeypatch.setattr(run.rr, "check_round_provenance", lambda rows: None)
    monkeypatch.setattr(run.rr, "build_argv", lambda **k: [])
    monkeypatch.setattr(run.rr, "build_run_environment", lambda **k: {"git_commit": "test"})
    monkeypatch.setattr(run.rr, "write_run_environment", lambda *a: None)

    def run_paper(*args, **kwargs):
        calls.append(kwargs["paper_id"])
        return rr.Attempt(kwargs["paper_id"], "token", kwargs["attempt"], 0, "stream", "", 0.1)

    monkeypatch.setattr(run.rr, "run_paper", run_paper)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--task", "exclusion", "--round", "1"])

    assert run.main() == 2
    assert calls == ["P1"]
    assert len(writes) == 2
