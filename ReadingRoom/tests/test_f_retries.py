"""Group F -- retries, concurrency and the ledger (F1-F12).

DC24 makes the retry rate a reportable number, so it has to be right: one row
per *attempt*, and the failure kind recorded, because a rate driven by rate
limits says nothing about the promptbook while a rate driven by parse failures
says everything.

These spawn a real child process -- the fake `claude` shim from `conftest.py`.
Free and offline, but a genuine `subprocess.run`, which is the point: what is
worth testing is that a real child sees the locked-down environment and the
empty cwd, and a patched function call would prove neither.

Case numbers refer to `TEST_PLAN.md`.
"""

from __future__ import annotations

import json

import pytest

from conftest import REPO_ROOT, label

import db
import reading_room as rr
import schemas


PROMPT = "promptbook\n\nBEGIN PAPER {token}\ntext\nEND PAPER {token}\n"


def send(room, fake, *, token="a1b2c3d4a1b2c3d4", paper_id="P1", attempt=1,
         **kwargs) -> rr.Attempt:
    return rr.run_paper(PROMPT.format(token=token), room=room, token=token,
                        paper_id=paper_id, attempt=attempt,
                        claude=str(fake.path), repo_root=REPO_ROOT, **kwargs)


# ------------------------------------------------- the child really is sealed


def test_the_child_runs_in_an_empty_room_outside_the_repo(clean_room, fake_claude):
    from pathlib import Path
    send(clean_room, fake_claude)
    cwd = Path(fake_claude.invocations()[0]["cwd"]).resolve()
    assert REPO_ROOT not in cwd.parents and cwd != REPO_ROOT
    assert cwd.name == "a1b2c3d4a1b2c3d4", "the room is keyed on the blinded token"


def test_the_child_sees_no_secrets(clean_room, fake_claude, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "FAKE-NOT-A-KEY")
    monkeypatch.setenv("ZOTERO_API_KEY", "FAKE-NOT-A-KEY")
    send(clean_room, fake_claude)
    keys = fake_claude.invocations()[0]["env_keys"]
    assert not [k for k in keys if "API_KEY" in k or "TOKEN" in k.upper()]
    assert "CLAUDE_CONFIG_DIR" in keys


def test_the_child_gets_the_sealed_argv(clean_room, fake_claude):
    send(clean_room, fake_claude)
    argv = fake_claude.invocations()[0]["argv"]
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--max-turns") + 1] == "1"
    assert argv[argv.index("--allowed-tools") + 1] == ""
    for flag in rr.FORBIDDEN_FLAGS:
        assert flag not in argv


def test_the_paper_arrives_on_stdin_not_as_a_path(clean_room, fake_claude):
    """Wall 3. A path would be a file the next paper could read."""
    send(clean_room, fake_claude)
    invocation = fake_claude.invocations()[0]
    assert invocation["prompt_chars"] > 0
    assert "BEGIN PAPER" in invocation["prompt_head"]


# --------------------------------------------------------- F1/F2: the retries


def test_f1_a_second_attempt_after_a_parse_failure(clean_room, fake_claude, tmp_path):
    """One judgment recorded, and exactly one retry on the ledger for it."""
    ledger = tmp_path / "ledger.csv"
    rows = []

    fake_claude.set(mode="reply", reply="Here is my answer: {oops")
    first = send(clean_room, fake_claude, attempt=1)
    with pytest.raises(schemas.ParseFailure):
        schemas.parse_decision(rr.assistant_text(first.stdout), task="exclusion")
    rows.append({"timestamp": "t", "task": "exclusion", "round": 1,
                 "paper_id": "P1", "token": first.token, "attempt": 1,
                 "outcome": "failure", "failure_kind": rr.FAILURE_PARSE})

    fake_claude.set(mode="echo")
    second = send(clean_room, fake_claude, token="bbbbbbbbbbbbbbbb", attempt=2)
    decision, _ = schemas.parse_decision(rr.assistant_text(second.stdout),
                                         task="exclusion", paper_id=None)
    rows.append({"timestamp": "t", "task": "exclusion", "round": 1,
                 "paper_id": "P1", "token": second.token, "attempt": 2,
                 "outcome": "ok", "failure_kind": ""})

    assert decision.decision == "no"
    rr.append_ledger(ledger, rows)
    stats = rr.retry_rate(rows)
    assert stats == {"attempts": 2, "papers": 1, "retries": 1,
                     "retry_rate": 0.5, "by_kind": {rr.FAILURE_PARSE: 1}}


def test_f2_three_failures_give_up_on_the_paper_not_the_round():
    """MAX_ATTEMPTS is the budget; the round survives a paper that spends it."""
    assert rr.MAX_ATTEMPTS == 3
    rows = [{"paper_id": "P1", "attempt": n, "failure_kind": rr.FAILURE_PARSE}
            for n in (1, 2, 3)]
    stats = rr.retry_rate(rows)
    assert stats["attempts"] == 3 and stats["retries"] == 2


def test_f3_the_ledger_has_one_row_per_attempt(tmp_path):
    ledger = tmp_path / "ledger.csv"
    rr.append_ledger(ledger, [
        {"paper_id": "P1", "attempt": 1, "outcome": "failure",
         "failure_kind": rr.FAILURE_PARSE},
        {"paper_id": "P1", "attempt": 2, "outcome": "ok", "failure_kind": ""},
        {"paper_id": "P2", "attempt": 1, "outcome": "ok", "failure_kind": ""},
    ])
    import csv
    rows = list(csv.DictReader(ledger.open(encoding="utf-8")))
    assert len(rows) == 3, "per attempt, not per paper"
    assert rr.retry_rate(rows)["papers"] == 2


def test_f3_appending_twice_does_not_rewrite_the_header(tmp_path):
    ledger = tmp_path / "ledger.csv"
    rr.append_ledger(ledger, [{"paper_id": "P1", "attempt": 1}])
    rr.append_ledger(ledger, [{"paper_id": "P2", "attempt": 1}])
    text = ledger.read_text(encoding="utf-8")
    assert text.count("paper_id") == 1


def test_f3_process_and_parse_failures_are_distinguishable(tmp_path):
    """A rate driven by rate limits says nothing about the promptbook."""
    rows = [{"paper_id": "P1", "attempt": 1, "failure_kind": rr.FAILURE_PROCESS},
            {"paper_id": "P1", "attempt": 2, "failure_kind": rr.FAILURE_PARSE},
            {"paper_id": "P1", "attempt": 3, "failure_kind": ""}]
    assert rr.retry_rate(rows)["by_kind"] == {rr.FAILURE_PROCESS: 1,
                                              rr.FAILURE_PARSE: 1}


def test_retry_rate_of_a_clean_round_is_zero():
    rows = [{"paper_id": f"P{n}", "attempt": 1, "failure_kind": ""} for n in range(50)]
    assert rr.retry_rate(rows)["retry_rate"] == 0.0


# ------------------------------------------------------------ F4: resumable


def test_f4_completed_papers_keep_their_raw_files(clean_room, fake_claude, tmp_path):
    """An interrupted round loses the papers in flight, never the ones done."""
    raw_dir = tmp_path / "raw"
    attempt = send(clean_room, fake_claude)
    path = rr.write_raw(attempt, raw_dir)
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == attempt.stdout
    assert rr.assistant_text(path.read_text(encoding="utf-8"))


def test_f4_the_raw_file_is_the_verbatim_stream(clean_room, fake_claude, tmp_path):
    """Saved before parsing: if parsing mangles it, you need the original."""
    fake_claude.set(mode="raw", stream="line one\nnot json\n{\"type\":\"x\"}\n")
    attempt = send(clean_room, fake_claude)
    path = rr.write_raw(attempt, tmp_path / "raw")
    assert path.read_text(encoding="utf-8") == "line one\nnot json\n{\"type\":\"x\"}\n"


# ---------------------------------------------------------------- F6: keying


def test_f6_two_workers_cannot_collide_on_a_filename(clean_room, fake_claude, tmp_path):
    """Impossible by construction: the filename is the token, which is unique."""
    raw_dir = tmp_path / "raw"
    paths = set()
    for token in ("1111111111111111", "2222222222222222"):
        attempt = send(clean_room, fake_claude, token=token, paper_id="P1")
        paths.add(rr.write_raw(attempt, raw_dir))
    assert len(paths) == 2


def test_f6_the_attempt_number_is_in_the_filename(clean_room, fake_claude, tmp_path):
    """So a retry never overwrites the evidence of what it is retrying."""
    raw_dir = tmp_path / "raw"
    first = rr.write_raw(send(clean_room, fake_claude, attempt=1), raw_dir)
    second = rr.write_raw(send(clean_room, fake_claude, token="cccccccccccccccc",
                               attempt=2), raw_dir)
    assert "attempt1" in first.name and "attempt2" in second.name


def test_f6_concurrent_papers_get_separate_rooms(clean_room, fake_claude):
    from concurrent.futures import ThreadPoolExecutor
    tokens = [f"{n:016x}" for n in range(6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda t: send(clean_room, fake_claude, token=t), tokens))
    cwds = {inv["cwd"] for inv in fake_claude.invocations()}
    assert len(cwds) == 6, "one paper, one room (A11)"


# -------------------------------------------------------- F7/F8: the database


def test_f7_a_duplicate_judgment_is_rejected(tmp_path):
    """DC19: append-only, and the UNIQUE constraint is what enforces it."""
    import sqlite3
    conn = db.connect(tmp_path / "t.db")
    try:
        kwargs = dict(paper_id="P1", task="exclusion", pass_name=db.PASS_PRIMARY,
                      model_used=rr.MODEL, decision="no", reasoning="r",
                      promptbook_evidence="E1", confidence=0.5,
                      promptbook_version="v1")
        assert db.insert_judgment(conn, judgment_index=1, **kwargs) == 1
        with pytest.raises(sqlite3.IntegrityError):
            db.insert_judgment(conn, judgment_index=1, **kwargs)
    finally:
        conn.close()


def test_f8_judgment_index_increments_project_wide_not_within_a_round(tmp_path):
    """The 2nd judgment of a paper is index 2 even if it came from round 5."""
    conn = db.connect(tmp_path / "t.db")
    try:
        kwargs = dict(paper_id="P1", task="exclusion", pass_name=db.PASS_PRIMARY,
                      model_used=rr.MODEL, decision="no", reasoning="r",
                      promptbook_evidence="E1", confidence=0.5)
        assert db.insert_judgment(conn, promptbook_version="v0", **kwargs) == 1
        assert db.insert_judgment(conn, promptbook_version="v1", **kwargs) == 2
        # A different task counts separately -- tasks are never conflated.
        assert db.insert_judgment(conn, promptbook_version="v1",
                                  **{**kwargs, "task": "power_analysis"}) == 1
    finally:
        conn.close()


# ----------------------------------------------------- F9/F10: the CLI misbehaves


def test_f9_a_hung_cli_is_killed_and_recorded(clean_room, fake_claude):
    fake_claude.set(mode="echo", sleep=5)
    attempt = send(clean_room, fake_claude, timeout=1)
    assert attempt.timed_out is True
    assert attempt.ok is False
    assert "timed out" in attempt.stderr


def test_f10_a_non_zero_exit_is_a_failure_not_a_crash(clean_room, fake_claude):
    fake_claude.set(mode="echo", exit_code=1)
    attempt = send(clean_room, fake_claude)
    assert attempt.exit_code == 1
    assert attempt.ok is False


def test_f10_a_clean_exit_is_ok(clean_room, fake_claude):
    assert send(clean_room, fake_claude).ok is True


# ------------------------------------------------------------- F11: no CLI


def test_f11_a_missing_cli_refuses_before_any_paper(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(rr.Refuse) as excinfo:
        rr.find_claude("claude")
    message = str(excinfo.value)
    assert "F11" in message
    assert "npm install" in message, "say how to fix it"


def test_f11_an_absolute_path_that_does_not_exist_refuses(tmp_path):
    with pytest.raises(rr.Refuse, match="F11"):
        rr.find_claude(str(tmp_path / "nope.exe"))


def test_f11_an_absolute_path_that_exists_is_taken_as_given(fake_claude):
    """On Windows the CLI is a .cmd shim that `which` finds only by extension."""
    assert rr.find_claude(str(fake_claude.path)) == str(fake_claude.path)


def test_f11_the_cli_is_found_on_path(fake_claude):
    assert rr.find_claude("claude")


# ------------------------------------------------------- F12: the raw file


def test_f12_an_unwritable_raw_dir_refuses_rather_than_scoring(clean_room,
                                                               fake_claude, tmp_path):
    attempt = send(clean_room, fake_claude)
    blocked = tmp_path / "blocked"
    blocked.write_text("I am a file, not a directory", encoding="utf-8")
    with pytest.raises(rr.Refuse) as excinfo:
        rr.write_raw(attempt, blocked)
    assert "F12" in str(excinfo.value)


def test_f12_no_partial_file_is_left_behind(clean_room, fake_claude, tmp_path):
    raw_dir = tmp_path / "raw"
    path = rr.write_raw(send(clean_room, fake_claude), raw_dir)
    assert path.is_file()
    assert not list(raw_dir.glob("*.partial")), (
        "a half-written raw file must never be left where it could be scored")


# ------------------------------------------------- one round, end to end


def test_a_whole_small_round_runs_and_validates(clean_room, fake_claude, tmp_path,
                                                promptbook_text):
    """The happy path through every layer: prompt, spawn, scan, parse, check."""
    known = rr.promptbook_rule_ids(promptbook_text, "exclusion")
    raw_dir = tmp_path / "raw"
    results = []

    for n in range(4):
        body = rr.clean_paper_text(f"Methods: cluster randomized trial {n}.")
        token = rr.new_token(body.text)
        prompt = rr.build_prompt(promptbook=promptbook_text, token=token,
                                 text=body.text, task="exclusion")
        attempt = rr.run_paper(prompt, room=clean_room, token=token,
                               paper_id=f"P{n}", claude=str(fake_claude.path),
                               repo_root=REPO_ROOT)
        rr.write_raw(attempt, raw_dir)

        rr.scan_stream_for_tools(attempt.stdout, paper=f"P{n}")
        reply = rr.assistant_text(attempt.stdout)
        rr.check_no_real_paper_ids(reply, token, {"XHFTHUCG", "3JVAWNIE"})
        decision, _ = schemas.parse_decision(reply, task="exclusion", paper_id=None)
        rr.check_token_echo(decision, token)
        rr.check_decision(decision, task="exclusion", token=token, known_rules=known)
        results.append(decision)

    assert len(results) == 4
    assert all(d.decision == "no" for d in results)
    assert len(list(raw_dir.glob("*.jsonl"))) == 4


def test_a_round_where_the_room_leaks_is_discarded(clean_room, fake_claude):
    """The one that matters: a tool call anywhere kills the round, not the paper."""
    fake_claude.set(mode="tool_use")
    attempt = send(clean_room, fake_claude, paper_id="LEAKY")
    with pytest.raises(rr.RoundDiscarded, match="LEAKY"):
        rr.scan_stream_for_tools(attempt.stdout, paper="LEAKY")


def test_a_tool_result_alone_also_discards_the_round(clean_room, fake_claude):
    fake_claude.set(mode="tool_result")
    attempt = send(clean_room, fake_claude)
    with pytest.raises(rr.RoundDiscarded):
        rr.scan_stream_for_tools(attempt.stdout, paper="P1")
