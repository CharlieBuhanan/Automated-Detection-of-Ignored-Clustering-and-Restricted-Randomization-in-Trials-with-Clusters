"""Group A -- isolation: the four walls (A1-A12).

The only group where a failure is FATAL. Everything here answers one question:
if the model reaches for the answers, does something *stop* it, or merely
disapprove?

Offline and free. Nothing spawns `claude`; A1/A2 assert on canned stream-json
text and the rest on argv, paths and a settings file. A12 is scored here on
synthetic rows -- the live canary run that costs money is the last build step,
and `canary_verdict` is the arithmetic it will be judged by.

Case numbers refer to `TEST_PLAN.md`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import REPO_ROOT, assistant_text, stream

import reading_room as rr


# ------------------------------------------------- A1/A2: the stream is proof


def test_a1_tool_use_block_discards_the_round():
    text = stream(
        {"type": "system", "subtype": "init", "tools": []},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "tu_1", "name": "Read",
             "input": {"file_path": "data/ground_truth.csv"}}]}},
    )
    with pytest.raises(rr.RoundDiscarded) as excinfo:
        rr.scan_stream_for_tools(text, paper="a1b2c3d4")

    message = str(excinfo.value)
    assert "a1b2c3d4" in message, "the failing paper must be named"
    assert "Read" in message, "the tool that was called must be named"
    assert "round" in message.lower(), "the blast radius is the round, not the paper"


def test_a2_tool_result_alone_also_discards_the_round():
    """A result cannot exist unless a call happened, logged or not."""
    text = stream(
        assistant_text('{"decision": "no"}'),
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tu_1", "content": "paper_id,label"}]}},
    )
    with pytest.raises(rr.RoundDiscarded):
        rr.scan_stream_for_tools(text)


def test_a1_tool_use_is_caught_however_deeply_nested():
    """The scan walks the whole event, so a new envelope shape cannot hide one."""
    text = stream({"type": "result", "subtype": "success", "usage": {},
                   "steps": [{"turns": [{"blocks": [
                       {"type": "tool_use", "name": "Bash", "input": {}}]}]}]})
    with pytest.raises(rr.RoundDiscarded):
        rr.scan_stream_for_tools(text)


def test_a1_clean_stream_passes():
    text = stream(
        {"type": "system", "subtype": "init", "tools": [], "mcp_servers": []},
        assistant_text('{"decision": "yes", "confidence": 0.8}'),
        {"type": "result", "subtype": "success", "is_error": False},
    )
    rr.scan_stream_for_tools(text)          # must not raise


def test_a1_garbage_lines_are_skipped_not_fatal():
    """A non-JSON line is 21_check_responses' problem, not a wall breach."""
    text = ("not json at all\n"
            "\n"
            "   \n"
            + json.dumps(assistant_text('{"decision": "no"}')) + "\n")
    rr.scan_stream_for_tools(text)


def test_a1_paper_text_quoting_tool_use_is_not_a_false_fatal():
    """A model echoing the words is not a model calling the tool.

    Worth pinning: a false FATAL throws away a paid round, so the scan must key
    on parsed block structure, never on the substring appearing in prose.
    """
    quoted = 'The prompt contained {"type": "tool_use", "name": "Read"} verbatim.'
    rr.scan_stream_for_tools(stream(assistant_text(quoted)))


def test_a1_empty_stream_passes():
    rr.scan_stream_for_tools("")


# ------------------------------------------------------- A3: the empty room


def test_a3_repo_root_itself_is_refused():
    with pytest.raises(rr.Refuse, match="A3"):
        rr.verify_cwd(REPO_ROOT, repo_root=REPO_ROOT)


def test_a3_any_directory_inside_the_repo_is_refused():
    with pytest.raises(rr.Refuse) as excinfo:
        rr.verify_cwd(REPO_ROOT / "data", repo_root=REPO_ROOT)
    assert "data" in str(excinfo.value), "the offending path must be named"


def test_a3_dot_dot_cannot_walk_back_into_the_repo(tmp_path):
    """Both sides are resolved, so a relative escape hatch is still inside."""
    sneaky = tmp_path / ".." / ".." / REPO_ROOT.name
    if not sneaky.resolve() == REPO_ROOT:
        sneaky = REPO_ROOT / "src" / ".." / "data"
    with pytest.raises(rr.Refuse, match="A3"):
        rr.verify_cwd(sneaky, repo_root=REPO_ROOT)


def test_a3_a_parent_of_the_repo_is_refused(tmp_path):
    with pytest.raises(rr.Refuse, match="A3"):
        rr.verify_cwd(REPO_ROOT.parent, repo_root=REPO_ROOT)


def test_a3_a_nonexistent_scratch_dir_is_refused(tmp_path):
    with pytest.raises(rr.Refuse, match="does not exist"):
        rr.verify_cwd(tmp_path / "never_made", repo_root=REPO_ROOT)


def test_a3_a_real_temp_dir_passes(tmp_path):
    rr.verify_cwd(tmp_path, repo_root=REPO_ROOT)


# --------------------------------------------------- A4/A5/A6/A9/A10: argv


def test_build_argv_passes_its_own_verifier(tmp_path):
    """The one argv the room may spawn must satisfy every argv wall."""
    argv = rr.build_argv(settings_path=tmp_path / "settings.json")
    rr.verify_argv(argv)
    assert argv[1] == "-p"
    assert "--verbose" in argv, "stream-json under -p is refused without it (A1)"
    assert rr._flag_value(argv, "--model") == rr.MODEL


@pytest.mark.parametrize("flag", rr.FORBIDDEN_FLAGS)
def test_a4_a9_a10_forbidden_flags_are_refused(flag, tmp_path):
    argv = rr.build_argv(settings_path=tmp_path / "s.json") + [flag, "value"]
    with pytest.raises(rr.Refuse, match=flag):
        rr.verify_argv(argv)


@pytest.mark.parametrize("flag", rr.FORBIDDEN_FLAGS)
def test_a4_a9_a10_forbidden_flags_are_refused_in_equals_form(flag, tmp_path):
    argv = rr.build_argv(settings_path=tmp_path / "s.json") + [f"{flag}=value"]
    with pytest.raises(rr.Refuse, match=flag):
        rr.verify_argv(argv)


def test_a9_short_form_continue_is_refused(tmp_path):
    """`-c` carries a whole prior session and does not look like `--continue`."""
    argv = rr.build_argv(settings_path=tmp_path / "s.json") + ["-c"]
    with pytest.raises(rr.Refuse, match="A9"):
        rr.verify_argv(argv)


def test_a5_non_empty_allowed_tools_is_refused(tmp_path):
    argv = rr.build_argv(settings_path=tmp_path / "s.json")
    argv[argv.index("--allowed-tools") + 1] = "Read"
    with pytest.raises(rr.Refuse, match="A5"):
        rr.verify_argv(argv)


def test_a5_missing_allowed_tools_is_refused(tmp_path):
    argv = rr.build_argv(settings_path=tmp_path / "s.json")
    i = argv.index("--allowed-tools")
    del argv[i:i + 2]
    with pytest.raises(rr.Refuse, match="A5"):
        rr.verify_argv(argv)


def test_a5_a_second_allowed_tools_flag_cannot_smuggle_tools_back_in(tmp_path):
    """The last flag is what the CLI honours, so every occurrence is checked."""
    argv = rr.build_argv(settings_path=tmp_path / "s.json") + ["--allowed-tools", "Bash"]
    with pytest.raises(rr.Refuse, match="A5"):
        rr.verify_argv(argv)


@pytest.mark.parametrize("turns", ["2", "10", "0", "", " "])
def test_a6_max_turns_must_be_exactly_one(turns, tmp_path):
    argv = rr.build_argv(settings_path=tmp_path / "s.json")
    argv[argv.index("--max-turns") + 1] = turns
    with pytest.raises(rr.Refuse, match="A6"):
        rr.verify_argv(argv)


def test_a6_missing_max_turns_is_refused(tmp_path):
    argv = rr.build_argv(settings_path=tmp_path / "s.json")
    i = argv.index("--max-turns")
    del argv[i:i + 2]
    with pytest.raises(rr.Refuse, match="A6"):
        rr.verify_argv(argv)


def test_a6_a_second_max_turns_flag_is_refused(tmp_path):
    argv = rr.build_argv(settings_path=tmp_path / "s.json") + ["--max-turns", "8"]
    with pytest.raises(rr.Refuse, match="A6"):
        rr.verify_argv(argv)


def test_a10_missing_strict_mcp_config_is_refused(tmp_path):
    argv = [a for a in rr.build_argv(settings_path=tmp_path / "s.json")
            if a != "--strict-mcp-config"]
    with pytest.raises(rr.Refuse, match="A10"):
        rr.verify_argv(argv)


def test_interactive_invocation_is_refused(tmp_path):
    argv = [a for a in rr.build_argv(settings_path=tmp_path / "s.json") if a != "-p"]
    with pytest.raises(rr.Refuse, match="non-interactive"):
        rr.verify_argv(argv)


@pytest.mark.parametrize("flag", ["--settings", "--model"])
def test_reproducibility_flags_are_required(flag, tmp_path):
    argv = rr.build_argv(settings_path=tmp_path / "s.json")
    i = argv.index(flag)
    del argv[i:i + 2]
    with pytest.raises(rr.Refuse, match=flag):
        rr.verify_argv(argv)


def test_model_is_pinned_to_the_batch_run_model():
    """A promptbook refined against one model and shipped against another is
    a promptbook tuned on nothing."""
    assert rr.MODEL == "claude-sonnet-5"


# ---------------------------------------------- A5/A10: the settings file


def test_settings_template_passes_verification(tmp_path, settings_file):
    path = settings_file(rr.SETTINGS_TEMPLATE)
    settings = rr.verify_settings(path)
    assert settings["permissions"]["deny"], "the denial must be in the committed record"
    assert "Read" in settings["permissions"]["deny"]


def test_verify_settings_refuses_a_missing_file(tmp_path):
    with pytest.raises(rr.Refuse, match="does not exist"):
        rr.verify_settings(tmp_path / "nope.json")


def test_verify_settings_refuses_unparseable_json(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(rr.Refuse, match="not valid JSON"):
        rr.verify_settings(path)


def test_a10_settings_with_mcp_servers_is_refused(settings_file):
    path = settings_file({"mcpServers": {"zotero": {"command": "npx"}}})
    with pytest.raises(rr.Refuse, match="A10"):
        rr.verify_settings(path)


def test_a10_enable_all_project_mcp_servers_is_refused(settings_file):
    path = settings_file({"enableAllProjectMcpServers": True})
    with pytest.raises(rr.Refuse, match="A10"):
        rr.verify_settings(path)


def test_a5_settings_that_allow_a_tool_are_refused(settings_file):
    path = settings_file({"permissions": {"allow": ["Read"]}})
    with pytest.raises(rr.Refuse, match="A5"):
        rr.verify_settings(path)


def test_a3_settings_that_add_directories_are_refused(settings_file):
    path = settings_file({"permissions": {"additionalDirectories": [str(REPO_ROOT)]}})
    with pytest.raises(rr.Refuse, match="A3/A4"):
        rr.verify_settings(path)


@pytest.mark.parametrize("mode", ["acceptEdits", "bypassPermissions"])
def test_a5_permissive_default_mode_is_refused(mode, settings_file):
    path = settings_file({"permissions": {"defaultMode": mode}})
    with pytest.raises(rr.Refuse, match="A5"):
        rr.verify_settings(path)


def test_a5_hooks_are_refused(settings_file):
    """A hook runs code inside the room, which is hands by another name."""
    path = settings_file({"hooks": {"PreToolUse": [{"command": "cat ../data/*.csv"}]}})
    with pytest.raises(rr.Refuse, match="hook"):
        rr.verify_settings(path)


# ------------------------------------------------------ A7: CLAUDE_CONFIG_DIR


@pytest.mark.parametrize("value", [None, "", "   "])
def test_a7_unset_config_dir_is_refused_not_defaulted(value):
    """Unset is a refusal because the default *is* the real user config."""
    with pytest.raises(rr.Refuse, match="A7"):
        rr.verify_config_dir(value)


def test_a7_the_real_user_config_is_refused():
    with pytest.raises(rr.Refuse, match="A7"):
        rr.verify_config_dir(Path.home() / ".claude")


def test_a7_a_directory_under_the_real_user_config_is_refused(tmp_path):
    fake_real = tmp_path / "real"
    (fake_real / "sub").mkdir(parents=True)
    with pytest.raises(rr.Refuse, match="A7"):
        rr.verify_config_dir(fake_real / "sub", user_config=fake_real)


def test_a7_a_directory_containing_the_real_user_config_is_refused(tmp_path):
    fake_real = tmp_path / "real" / ".claude"
    fake_real.mkdir(parents=True)
    with pytest.raises(rr.Refuse, match="A7"):
        rr.verify_config_dir(tmp_path / "real", user_config=fake_real)


def test_a7_a_nonexistent_config_dir_is_refused(tmp_path):
    with pytest.raises(rr.Refuse, match="A7"):
        rr.verify_config_dir(tmp_path / "never_made", user_config=tmp_path / "real")


@pytest.mark.parametrize("entry", ["CLAUDE.md", "CLAUDE.local.md", "memory",
                                   "projects", "commands"])
def test_a7_a_config_dir_carrying_context_is_refused(entry, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    target = config / entry
    if entry.endswith(".md"):
        target.write_text("remember: the answers are in data/", encoding="utf-8")
    else:
        target.mkdir()
    with pytest.raises(rr.Refuse, match="A7"):
        rr.verify_config_dir(config, user_config=tmp_path / "real")


def test_a7_an_empty_config_dir_passes_and_is_resolved(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    assert rr.verify_config_dir(config, user_config=tmp_path / "real") == config.resolve()


def test_a7_child_env_drops_everything_not_allowlisted(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    base = {"PATH": "/usr/bin", "HOME": "/home/x",
            "ANTHROPIC_API_KEY": "FAKE-NOT-A-KEY",
            "ZOTERO_API_KEY": "FAKE-NOT-A-KEY",
            "CLAUDE_CODE_ENTRYPOINT": "cli"}
    env = rr.child_env(config, base=base)

    assert set(env) == {"PATH", "HOME", "CLAUDE_CONFIG_DIR"}
    assert not any(k.endswith("API_KEY") for k in env), (
        "the refinement loop runs on subscription quota; a key in the child's "
        "environment would silently bill the API and is one injection away "
        "from being read out")
    assert env["CLAUDE_CONFIG_DIR"] == str(config.resolve())


def test_a7_child_env_overrides_an_inherited_config_dir(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    env = rr.child_env(config, base={"CLAUDE_CONFIG_DIR": str(Path.home() / ".claude")})
    assert env["CLAUDE_CONFIG_DIR"] == str(config.resolve())


# ------------------------------------------------------------ A8: no CLAUDE.md


@pytest.mark.parametrize("entry", ["CLAUDE.md", "CLAUDE.local.md"])
def test_a8_claude_md_in_the_room_is_refused(entry, tmp_path):
    (tmp_path / entry).write_text("# project rules", encoding="utf-8")
    with pytest.raises(rr.Refuse, match="A8"):
        rr.verify_no_claude_md(tmp_path)


def test_a8_a_dot_claude_directory_in_the_room_is_refused(tmp_path):
    (tmp_path / ".claude").mkdir()
    with pytest.raises(rr.Refuse, match="A8"):
        rr.verify_no_claude_md(tmp_path)


def test_a8_claude_md_in_an_ancestor_is_refused(tmp_path):
    """The case the plan understates: Claude Code walks ancestors.

    A room dug two levels under a directory that has a CLAUDE.md inherits it --
    and this project's names the ground-truth file by path.
    """
    (tmp_path / "CLAUDE.md").write_text("data/ground_truth.csv holds the answers",
                                        encoding="utf-8")
    deep = tmp_path / "a" / "b" / "room"
    deep.mkdir(parents=True)
    with pytest.raises(rr.Refuse) as excinfo:
        rr.verify_no_claude_md(deep)
    assert "CLAUDE.md" in str(excinfo.value)


def test_a8_a_clean_room_passes(tmp_path):
    room = tmp_path / "room"
    room.mkdir()
    rr.verify_no_claude_md(room)


def test_a8_the_repo_would_be_refused_for_its_own_claude_md():
    """Sanity check that A8 is testing something real: this repo has one."""
    assert (REPO_ROOT / ".claude" / "CLAUDE.md").is_file()
    with pytest.raises(rr.Refuse):
        rr.verify_no_claude_md(REPO_ROOT)


# ------------------------------------------------- A11: one room, one paper


def test_a11_a_dirty_room_is_refused(tmp_path):
    (tmp_path / "response.json").write_text("{}", encoding="utf-8")
    with pytest.raises(rr.Refuse, match="A11"):
        rr.assert_room_empty(tmp_path)


def test_a11_the_refusal_names_the_leftovers(tmp_path):
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("", encoding="utf-8")
    with pytest.raises(rr.Refuse) as excinfo:
        rr.assert_room_empty(tmp_path)
    assert "a.txt" in str(excinfo.value) and "b.txt" in str(excinfo.value)


def test_a11_an_empty_room_passes(tmp_path):
    rr.assert_room_empty(tmp_path)


def test_a11_a_room_is_never_reused(clean_room):
    first = rr.new_paper_room(clean_room, "deadbeefdeadbeef", repo_root=REPO_ROOT)
    assert first.is_dir()
    with pytest.raises(rr.Refuse, match="A11"):
        rr.new_paper_room(clean_room, "deadbeefdeadbeef", repo_root=REPO_ROOT)


def test_a11_two_papers_get_two_rooms(clean_room):
    a = rr.new_paper_room(clean_room, "1111111111111111", repo_root=REPO_ROOT)
    b = rr.new_paper_room(clean_room, "2222222222222222", repo_root=REPO_ROOT)
    assert a != b and a.is_dir() and b.is_dir()


# ------------------------------------------ prepare_room: every wall at once


def test_prepare_room_builds_a_room_that_passes_every_wall(clean_room):
    rr.verify_room(clean_room, repo_root=REPO_ROOT)
    assert clean_room.papers_dir.is_dir()
    assert clean_room.config_dir.is_dir()
    assert json.loads(clean_room.settings_path.read_text(encoding="utf-8")) \
        == rr.SETTINGS_TEMPLATE


def test_prepare_room_refuses_a_room_inside_the_repo(tmp_path):
    """The wall holds even when the caller picks the location."""
    with pytest.raises(rr.Refuse, match="A3"):
        rr.prepare_room(REPO_ROOT / "scratch_room", repo_root=REPO_ROOT)
    assert not (REPO_ROOT / "scratch_room").exists() or \
        not any((REPO_ROOT / "scratch_room").iterdir()), \
        "a refused room must not be left behind holding paper text"


def test_room_env_is_the_locked_down_env(clean_room):
    env = clean_room.env(base={"PATH": "/usr/bin", "ANTHROPIC_API_KEY": "FAKE-NOT-A-KEY"})
    assert "ANTHROPIC_API_KEY" not in env
    assert env["CLAUDE_CONFIG_DIR"] == str(clean_room.config_dir.resolve())


# --------------------------------------------------------- A12: the canary


def canary_rows(n: int, *, truth_hits: int, decoy_hits: int) -> list[dict]:
    """`n` scoreable rows: truth='yes', decoy='no', decision set to order."""
    rows = []
    for i in range(n):
        if i < truth_hits:
            decision = "yes"
        elif i < truth_hits + decoy_hits:
            decision = "no"
        else:
            decision = "undecidable"
        rows.append({"decision": decision, "truth": "yes", "decoy": "no"})
    return rows


def test_a12_a_model_reading_the_decoy_is_flagged_as_leaked():
    verdict = rr.canary_verdict(canary_rows(20, truth_hits=1, decoy_hits=19))
    assert verdict["leaked"] is True
    assert verdict["suspicious"] is True
    assert verdict["decoy_agreement"] == pytest.approx(0.95)


def test_a12_a_model_reasoning_from_the_paper_is_clean():
    verdict = rr.canary_verdict(canary_rows(20, truth_hits=17, decoy_hits=3))
    assert verdict["leaked"] is False
    assert verdict["suspicious"] is False
    assert verdict["truth_agreement"] == pytest.approx(0.85)


def test_a12_a_small_decoy_lead_is_suspicious_but_not_fatal():
    """Under the margin: worth a look before trusting the round, not a discard."""
    verdict = rr.canary_verdict(canary_rows(20, truth_hits=9, decoy_hits=11))
    assert verdict["suspicious"] is True
    assert verdict["leaked"] is False


def test_a12_the_margin_boundary_is_inclusive():
    """Chosen so both rates are exact in binary: 0.25 + 0.25 == 0.50."""
    verdict = rr.canary_verdict(canary_rows(4, truth_hits=1, decoy_hits=2), margin=0.25)
    assert verdict["truth_agreement"] == 0.25
    assert verdict["decoy_agreement"] == 0.50
    assert verdict["leaked"] is True


def test_a12_rows_where_the_decoy_equals_the_truth_are_not_scored():
    """Only a flipped label distinguishes reading from reasoning."""
    rows = canary_rows(10, truth_hits=8, decoy_hits=2)
    rows += [{"decision": "yes", "truth": "yes", "decoy": "yes"} for _ in range(90)]
    verdict = rr.canary_verdict(rows)
    assert verdict["n"] == 10


def test_a12_a_canary_with_no_flipped_labels_is_refused():
    rows = [{"decision": "yes", "truth": "yes", "decoy": "yes"} for _ in range(20)]
    with pytest.raises(rr.Refuse, match="A12"):
        rr.canary_verdict(rows)
