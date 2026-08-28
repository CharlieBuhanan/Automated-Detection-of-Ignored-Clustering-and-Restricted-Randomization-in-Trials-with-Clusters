"""Group G -- provenance: can this number be traced back to what produced it?

A number nobody can trace back to the conditions that made it is not a result.
The CLI exposes neither temperature nor seed, so identical bytes are unreachable
and the write-up must not claim them. What replaces them is a completely recorded
*procedure* -- and the point of this file is that a recording with a hole in it
**fails** rather than being quietly written down with the hole.

Two layers, tested separately. `run_environment.json` holds what must be
identical for every paper in a round; the run log holds what legitimately varies.
G11 compares two rounds using only the first.

Offline and free. The stream assertions run on canned events, and the end-to-end
cases drive `fake_claude.py`, which emits the real CLI 2.1.197 shapes -- including
a `usage` block, `permission_denials`, `fast_mode_state` and a
`claude_code_version`, none of which it had before this group was written.

Case numbers refer to `TEST_PLAN.md`.
"""

from __future__ import annotations

import json

import pytest

from conftest import REPO_ROOT, assistant_text, stream

import reading_room as rr


# The shape a good paper produces, as the real CLI emits it. Every test below is
# a single field away from this, which is what makes the failures legible.


def init_event(**overrides) -> dict:
    event = {"type": "system", "subtype": "init", "tools": [],
             "mcp_servers": [], "model": rr.MODEL,
             "claude_code_version": "2.1.197", "session_id": "s_1"}
    event.update(overrides)
    return {k: v for k, v in event.items() if v is not None}


def result_event(**overrides) -> dict:
    event = {"type": "result", "subtype": "success", "is_error": False,
             "session_id": "s_1", "duration_ms": 4210, "duration_api_ms": 4008,
             "ttft_ms": 612, "num_turns": 1, "stop_reason": "end_turn",
             "terminal_reason": "completed", "total_cost_usd": 0.0121,
             "permission_denials": [], "fast_mode_state": "off",
             "service_tier": "standard", "inference_geo": "us",
             "context_window": 200000, "max_output_tokens": 64000,
             "usage": {"input_tokens": 4, "cache_creation_input_tokens": 179,
                       "cache_read_input_tokens": 0, "output_tokens": 96,
                       "speed": "standard"}}
    event.update(overrides)
    return {k: v for k, v in event.items() if v is not None}


def good_stream(*, init=None, result=None) -> str:
    return stream(
        init_event(**(init or {})),
        {"type": "assistant", "request_id": "req_01",
         "message": {"role": "assistant", "model": rr.MODEL,
                     "content": [{"type": "text", "text": '{"decision": "no"}'}]}},
        result_event(**(result or {})),
    )


def test_a_clean_stream_passes_every_provenance_check():
    rr.check_paper_provenance(good_stream(), paper="abc123")


# ------------------------------------------------------------ G2: CLI version


def test_g2_two_cli_versions_in_one_round_discards_it():
    """The CLI auto-updates. A round that straddled one is two experiments."""
    with pytest.raises(rr.RoundDiscarded) as excinfo:
        rr.check_round_provenance(["2.1.197", "2.1.197", "2.1.198"])

    message = str(excinfo.value)
    assert "2.1.198" in message, "both versions must be named"
    assert "G2" in message


def test_g2_one_version_throughout_passes():
    rr.check_round_provenance(["2.1.197"] * 50)


def test_g2_missing_versions_do_not_manufacture_a_second_version():
    """G4 is what fails a paper with no version; G2 only compares the ones there."""
    rr.check_round_provenance(["2.1.197", None, "", "2.1.197"])


# ----------------------------------------------------------------- G3: model


def test_g3_a_different_reported_model_discards_the_round():
    text = good_stream(init={"model": "claude-haiku-4-5-20251001"})
    with pytest.raises(rr.RoundDiscarded) as excinfo:
        rr.check_paper_provenance(text, paper="abc123", model=rr.MODEL)

    message = str(excinfo.value)
    assert "haiku" in message, "the model that actually ran must be named"
    assert "G3" in message


def test_g3_the_pinned_model_passes():
    rr.check_paper_provenance(good_stream(), model=rr.MODEL)


def test_g3_the_bare_alias_is_the_whole_id():
    """No dated snapshot exists. `claude-sonnet-5` IS the complete model ID.

    Pinned as a test because the write-up must say "claude-sonnet-5, CLI 2.1.197"
    and must not imply a snapshot that the API would reject.
    """
    import re
    assert rr.MODEL == "claude-sonnet-5"
    assert not re.search(r"-20\d{6}$", rr.MODEL), \
        "a dated snapshot suffix would be rejected by the API -- none exists"


# ------------------------------------------------- G4: claude_code_version


def test_g4_a_stream_with_no_version_field_is_refused():
    text = good_stream(init={"claude_code_version": None})
    with pytest.raises(rr.Refuse, match="G4"):
        rr.check_paper_provenance(text, paper="abc123")


def test_g4_a_stream_with_no_init_event_at_all_is_refused():
    text = stream(assistant_text('{"decision": "no"}'), result_event())
    with pytest.raises(rr.Refuse, match="G4"):
        rr.check_paper_provenance(text, paper="abc123")


# ------------------------------------------------------- G5: no result event


def test_g5_a_stream_cut_before_its_result_event_is_a_retry():
    """A killed process has no duration, usage or cost -- and none may be invented."""
    text = stream(init_event(),
                  {"type": "assistant", "request_id": "req_01",
                   "message": {"content": [{"type": "text", "text": "{"}]}})
    with pytest.raises(rr.SemanticFailure) as excinfo:
        rr.check_paper_provenance(text, paper="abc123")
    assert excinfo.value.case == "G5"


def test_g5_is_a_retry_not_a_round_failure():
    """One killed process is one paper's problem; the walls did not move."""
    text = stream(init_event(), assistant_text("{}"))
    with pytest.raises(rr.SemanticFailure):
        rr.check_paper_provenance(text)


# --------------------------------------------------------------- G6: request_id


def test_g6_a_reply_with_no_request_id_is_a_retry():
    text = stream(init_event(),
                  {"type": "assistant",
                   "message": {"content": [{"type": "text", "text": "{}"}]}},
                  result_event())
    with pytest.raises(rr.SemanticFailure) as excinfo:
        rr.check_paper_provenance(text, paper="abc123")
    assert excinfo.value.case == "G6"
    assert "trace" in str(excinfo.value), \
        "the reason it matters is that support cannot trace the call without it"


def test_g6_the_request_id_is_captured_into_the_run_log():
    assert rr.paper_provenance(good_stream())["request_id"] == "req_01"


# ------------------------------------------- G7: a missing field is null, not 0


def test_g7_absent_cost_is_absent_rather_than_zero():
    """A fabricated 0 is indistinguishable from a free call.

    This is the whole of G7 in one assertion: the round's total cost would
    silently become a lie, and no reader could tell.
    """
    row = rr.paper_provenance(good_stream(result={"total_cost_usd": None}))
    assert "total_cost_usd" not in row
    assert row.get("total_cost_usd") is None


def test_g7_absent_usage_fields_are_absent():
    text = good_stream(result={"usage": None})
    row = rr.paper_provenance(text)
    for field in ("input_tokens", "output_tokens", "billed_input_tokens"):
        assert field not in row, f"{field} must be missing, never defaulted"


def test_g7_present_fields_are_captured_verbatim():
    row = rr.paper_provenance(good_stream())
    assert row["total_cost_usd"] == 0.0121
    assert row["duration_ms"] == 4210
    assert row["ttft_ms"] == 612
    assert row["billed_input_tokens"] == 183
    assert row["claude_code_version"] == "2.1.197"
    assert row["stop_reason"] == "end_turn"


def test_g7_a_missing_field_does_not_stop_the_round():
    """HANDLE, not RETRY: log the hole and carry on."""
    rr.check_paper_provenance(good_stream(result={"total_cost_usd": None}))


def test_g7_every_captured_field_has_a_run_log_column():
    """A field captured and then dropped on the floor is worse than not captured."""
    captured = set(rr.paper_provenance(good_stream()))
    assert captured <= set(rr.PROVENANCE_COLUMNS), \
        f"no run-log column for {sorted(captured - set(rr.PROVENANCE_COLUMNS))}"


# ------------------------------------------------------- G8: permission_denials


def test_g8_a_permission_denial_discards_the_round():
    """Something attempted an action, whether or not it succeeded."""
    text = good_stream(result={"permission_denials": [
        {"tool_name": "Read", "tool_input": {"file_path": "ground_truth.csv"}}]})
    with pytest.raises(rr.RoundDiscarded) as excinfo:
        rr.check_paper_provenance(text, paper="abc123")
    assert "G8" in str(excinfo.value)


def test_g8_an_empty_denial_list_passes():
    rr.check_paper_provenance(good_stream(result={"permission_denials": []}))


def test_g8_the_denial_count_reaches_the_run_log():
    assert rr.paper_provenance(good_stream())["permission_denials"] == 0


# ------------------------------------------------------------- G9: max_tokens


def test_g9_a_truncated_reply_is_a_truncation_not_a_parse_failure():
    """DC24's retry rate is only meaningful if the ledger says which kind.

    A rate driven by output-cap truncations says the paper is too long. A rate
    driven by parse failures says the promptbook's format instruction is losing.
    Collapsing them into one number answers neither question.
    """
    text = good_stream(result={"stop_reason": "max_tokens"})
    with pytest.raises(rr.SemanticFailure) as excinfo:
        rr.check_paper_provenance(text, paper="abc123")
    assert excinfo.value.case == "G9"
    assert rr.FAILURE_TRUNCATION != rr.FAILURE_PARSE


def test_g9_a_normal_stop_reason_passes():
    rr.check_paper_provenance(good_stream(result={"stop_reason": "end_turn"}))


# ------------------------------------------------------------ G10: git commit


def git_repo(tmp_path, *, dirty: bool):
    """A throwaway git repo with one commit, optionally with an edit on top."""
    import subprocess
    run = lambda *a: subprocess.run(a, cwd=str(tmp_path), capture_output=True,
                                    check=True)
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@t.t")
    run("git", "config", "user.name", "t")
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    run("git", "add", "a.txt")
    run("git", "commit", "-q", "-m", "one")
    if dirty:
        (tmp_path / "a.txt").write_text("two", encoding="utf-8")
    return tmp_path


def test_g10_a_clean_tree_is_a_bare_sha(tmp_path):
    commit = rr.git_commit(git_repo(tmp_path, dirty=False))
    assert len(commit) == 40 and not commit.endswith("-dirty")


def test_g10_a_dirty_tree_is_recorded_as_dirty(tmp_path):
    """Never a clean sha over a dirty tree.

    A clean sha there points a future reader at a commit that did not produce
    this round -- they would check out that sha, get different code, and have no
    way to know. The suffix is the difference between a reproducible procedure
    and a misleading one.
    """
    commit = rr.git_commit(git_repo(tmp_path, dirty=True))
    assert commit.endswith("-dirty")
    assert len(commit) == 40 + len("-dirty")


def test_g10_a_non_git_directory_says_unknown_rather_than_guessing(tmp_path):
    """`unknown` is honest, and it makes G11 refuse rather than compare to a guess."""
    assert rr.git_commit(tmp_path / "not_a_repo") == "unknown"


# ---------------------------------------- G11: two rounds, comparable or not


def environment(**overrides) -> dict:
    base = {"model": rr.MODEL, "effort": rr.EFFORT,
            "system_prompt_sha256": "aaa", "promptbook_version": "v1",
            "promptbook_sha256": "bbb"}
    base.update(overrides)
    return base


@pytest.mark.parametrize("field,value", [
    ("model", "claude-haiku-4-5-20251001"),
    ("effort", "low"),
    ("system_prompt_sha256", "ccc"),
    ("promptbook_version", "v2"),
    ("promptbook_sha256", "ddd"),
])
def test_g11_a_changed_condition_refuses_the_comparison(field, value):
    """A plateau computed across a config change measures the change.

    That is not a pedantic point: it would end the refinement loop early, on an
    artefact, and the study's stopping rule is exactly this comparison.
    """
    with pytest.raises(rr.Refuse) as excinfo:
        rr.compare_run_environments(environment(), environment(**{field: value}))
    assert field in str(excinfo.value)
    assert "G11" in str(excinfo.value)


def test_g11_identical_conditions_compare_fine():
    rr.compare_run_environments(environment(), environment())


def test_g11_incidental_differences_do_not_block_a_comparison():
    """Two rounds legitimately differ in time, host and round number."""
    rr.compare_run_environments(
        environment(started_at="09:00", host="a", round=1),
        environment(started_at="17:00", host="b", round=2))


# --------------------------------------------------------- G12: serving path


@pytest.mark.parametrize("field,value", [
    ("fast_mode_state", "on"),
    ("service_tier", "priority"),
])
def test_g12_a_different_serving_path_discards_the_round(field, value):
    with pytest.raises(rr.RoundDiscarded) as excinfo:
        rr.check_paper_provenance(good_stream(result={field: value}),
                                  paper="abc123")
    assert "G12" in str(excinfo.value)


def test_g12_a_non_standard_speed_in_usage_discards_the_round():
    """`speed` rides in the usage block, not on the result event itself."""
    usage = dict(result_event()["usage"], speed="fast")
    with pytest.raises(rr.RoundDiscarded, match="G12"):
        rr.check_paper_provenance(good_stream(result={"usage": usage}))


def test_g12_an_absent_serving_field_is_not_a_failure():
    """Absent is G7's problem (log null), not evidence of a different path."""
    rr.check_paper_provenance(good_stream(result={"fast_mode_state": None}))


# ------------------------------------------- G1: the run record itself


def test_g1_a_missing_run_environment_refuses_scoring(tmp_path):
    with pytest.raises(rr.Refuse) as excinfo:
        rr.load_run_environment(tmp_path / "run_environment.json")
    message = str(excinfo.value)
    assert "G1" in message
    assert "unprovenanced" in message


def test_g1_a_corrupt_run_environment_refuses_scoring(tmp_path):
    path = tmp_path / "run_environment.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(rr.Refuse, match="G1"):
        rr.load_run_environment(path)


def test_g1_a_written_record_round_trips(tmp_path, clean_room):
    written = rr.build_run_environment(
        task="exclusion", round_no=1,
        argv=rr.build_argv(settings_path=clean_room.settings_path),
        promptbook_version="v1", promptbook_text="E1. A rule.",
        settings_path=clean_room.settings_path, tools_offered=[],
        claude_code_version="2.1.197", started_at="2026-08-27T00:00:00+00:00",
        finished_at="2026-08-27T00:05:00+00:00", repo_root=REPO_ROOT)
    path = rr.write_run_environment(tmp_path / "run_environment.json", written)
    assert rr.load_run_environment(path) == written


def test_the_run_record_carries_every_field_the_test_plan_names(clean_room):
    """The list is in TEST_PLAN's 'What run_environment.json must contain'.

    Asserted rather than trusted, because a field that quietly stopped being
    written would only be noticed when someone tried to reproduce the round --
    which is precisely too late.
    """
    written = rr.build_run_environment(
        task="exclusion", round_no=1,
        argv=rr.build_argv(settings_path=clean_room.settings_path),
        promptbook_version="v1", promptbook_text="E1. A rule.",
        settings_path=clean_room.settings_path, tools_offered=[],
        claude_code_version="2.1.197", started_at="2026-08-27T00:00:00+00:00",
        repo_root=REPO_ROOT)

    for field in ("model", "effort", "thinking", "claude_code_version", "argv",
                  "system_prompt_sha256", "system_prompt_path",
                  "settings_sha256", "promptbook_version", "promptbook_sha256",
                  "git_commit", "tools_offered", "host", "os", "python_version",
                  "started_at", "finished_at"):
        assert field in written, f"run_environment.json is missing {field}"

    assert written["thinking"] == "adaptive", \
        "the only on-mode on Sonnet 5; --effort is the only lever"
    assert written["effort"] == rr.EFFORT
    assert written["tools_offered"] == []


def test_the_record_holds_the_argv_verbatim_including_the_system_prompt(clean_room):
    """argv is the only field that records what was ACTUALLY sent.

    Everything else in the record is a summary a reader has to take on trust;
    the argv is the thing they can check the summary against.
    """
    argv = rr.build_argv(settings_path=clean_room.settings_path)
    written = rr.build_run_environment(
        task="exclusion", round_no=1, argv=argv, promptbook_version="v1",
        promptbook_text="E1.", settings_path=clean_room.settings_path,
        tools_offered=[], claude_code_version="2.1.197",
        started_at="2026-08-27T00:00:00+00:00", repo_root=REPO_ROOT)

    assert written["argv"] == argv
    assert rr.load_system_prompt() in written["argv"]
    assert written["system_prompt_sha256"] == rr.sha256_text(rr.load_system_prompt())


# ----------------------------------------- end to end, against a real child


def test_the_fake_cli_emits_the_shape_the_harness_reads(clean_room, fake_claude):
    """If the fake cannot forge a field, the offline suite is testing a fiction.

    That is not hypothetical: both live probes found defects the offline suite
    could not, and both times the cause was the fake emitting a shape the real
    CLI does not have.
    """
    probe = rr.preflight(clean_room, claude=str(fake_claude.path),
                         repo_root=REPO_ROOT)
    assert probe.claude_code_version == "2.1.197"
    assert probe.input_tokens == 183

    row = rr.paper_provenance(probe.stdout)
    for field in ("request_id", "session_id", "duration_ms", "ttft_ms",
                  "stop_reason", "total_cost_usd", "service_tier",
                  "context_window", "claude_code_version", "billed_input_tokens"):
        assert field in row, f"fake_claude.py cannot forge {field}"


def test_a_g8_denial_from_a_real_child_process_discards_the_round(clean_room, fake_claude):
    """A denial is invisible to every other check: exit 0, no tool_use, tools []."""
    fake_claude.set(result={"permission_denials": [{"tool_name": "Read"}]})
    probe = rr.preflight(clean_room, claude=str(fake_claude.path),
                         repo_root=REPO_ROOT)
    rr.scan_stream_for_tools(probe.stdout)          # A1/A2 see nothing wrong
    assert probe.tools == []                        # A14 sees nothing wrong
    with pytest.raises(rr.RoundDiscarded, match="G8"):
        rr.check_paper_provenance(probe.stdout)
