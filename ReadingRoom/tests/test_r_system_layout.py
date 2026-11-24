"""Group R: the system layout (v3 onward). Offline; the fake CLI spawns nothing.

v0-v2 sent the promptbook twice in the user message (DC26 sandwich) and the v2
smoke test read 0 tokens from the cache. From v3 the book and the answer rules
go in the system prompt once, through `--system-prompt-file`, so papers 2..n
can read them from the cache. These tests pin the table, the bytes, the walls
around the file, and the provenance record.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import reading_room as rr

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT
TOKEN_A = "0123456789abcdef"
TOKEN_B = "fedcba9876543210"
PERSONA_TOKENS = 12_198


# ------------------------------------------------------------- the table


@pytest.mark.parametrize("version", ["v0", "v1", "v2"])
def test_r1_run_versions_keep_the_sandwich(version):
    """Paid evidence keeps the shape it ran under, byte for byte."""
    assert rr.prompt_layout(version) == rr.LAYOUT_SANDWICH


@pytest.mark.parametrize("version", ["v3", "v4"])
def test_r1_later_versions_use_the_system_layout(version):
    assert rr.prompt_layout(version) == rr.LAYOUT_SYSTEM


def test_r1_v2_has_no_system_prompt_and_its_paper_prompt_is_unchanged():
    book = rr.resolve_route_book("exclusion", root=ROOT, version="v2")
    assert rr.build_route_system_prompt(book) is None
    prompt = rr.build_route_prompt(book, token=TOKEN_A, text="PAPER BODY")
    assert prompt.count(book.promptbook.strip()) == 2, "v2 still sends the sandwich"


# --------------------------------------------------------- v3 books


def test_r2_v3_exclusion_is_byte_identical_to_v2():
    v2 = (ROOT / "promptbooks" / "v2" / "exclusion.md").read_bytes()
    v3 = (ROOT / "promptbooks" / "v3" / "exclusion.md").read_bytes()
    assert v2 == v3


def test_r2_v3_combined_ties_stratum_to_levels():
    text = (ROOT / "promptbooks" / "v3" / "combined_analysis.md").read_text(encoding="utf-8")
    assert "that same unit must also be\n  the last entry in `levels`" in text
    assert "`ind_samp_unit: stratum`" in text


# --------------------------------------------------- the prompt bytes


@pytest.mark.parametrize("route", ["exclusion", "combined_analysis"])
def test_r3_system_prompt_holds_the_book_once_and_nothing_per_paper(route):
    book = rr.resolve_route_book(route, root=ROOT, version="v3")
    system = rr.build_route_system_prompt(book)
    assert system.count(book.promptbook.strip()) == 1
    assert "{" + "token" + "}" not in system
    # Identical for every paper, or it cannot be cached.
    assert rr.build_route_system_prompt(book) == system
    assert "HOW TO REPLY" in system


@pytest.mark.parametrize("route", ["exclusion", "combined_analysis"])
def test_r3_user_message_is_the_paper_only(route):
    book = rr.resolve_route_book(route, root=ROOT, version="v3")
    message = rr.build_route_prompt(book, token=TOKEN_A, text="PAPER BODY")
    assert f"BEGIN PAPER {TOKEN_A}" in message and f"END PAPER {TOKEN_A}" in message
    assert "PAPER BODY" in message
    assert f'"paper_id" is exactly {TOKEN_A}' in message
    assert book.promptbook.strip()[:200] not in message, "no second copy of the book"
    assert message.rstrip().endswith(f"exactly {TOKEN_A}."), \
        "the last thing in the context is the task, not the paper (DC26)"


def test_r3_exclusion_system_rules_match_the_sandwich_rules():
    """Same checked rules as v2's instructions, minus the per-paper token."""
    book = rr.resolve_route_book("exclusion", root=ROOT, version="v3")
    system = rr.build_route_system_prompt(book)
    assert rr._exclusion_reason_range() in system
    assert rr.EVIDENCE_WRONG_TEXT in system
    assert '"exclusion_reason"' in system


# ------------------------------------------------------------- argv


def test_r4_argv_carries_the_file_last_and_no_inline_prompt(tmp_path):
    path = tmp_path / "system_prompt.txt"
    argv = rr.build_argv(settings_path=tmp_path / "s.json", system_prompt_file=path)
    assert argv[-2:] == ["--system-prompt-file", str(path)]
    assert "--system-prompt" not in argv


def test_r4_verify_accepts_the_matching_file(tmp_path):
    path = tmp_path / "system_prompt.txt"
    path.write_text("line one\nline two\n", encoding="utf-8", newline="")
    argv = rr.build_argv(settings_path=tmp_path / "s.json", system_prompt_file=path)
    rr.verify_argv(argv, system_prompt_file_text="line one\nline two\n")


def test_r4_verify_refuses_an_edited_file(tmp_path):
    path = tmp_path / "system_prompt.txt"
    path.write_text("tampered", encoding="utf-8")
    argv = rr.build_argv(settings_path=tmp_path / "s.json", system_prompt_file=path)
    with pytest.raises(rr.Refuse, match="does not match"):
        rr.verify_argv(argv, system_prompt_file_text="original")


def test_r4_verify_refuses_a_file_with_no_expected_text(tmp_path):
    path = tmp_path / "system_prompt.txt"
    path.write_text("x", encoding="utf-8")
    argv = rr.build_argv(settings_path=tmp_path / "s.json", system_prompt_file=path)
    with pytest.raises(rr.Refuse, match="no expected text"):
        rr.verify_argv(argv)


def test_r4_verify_refuses_both_prompt_flags(tmp_path):
    path = tmp_path / "system_prompt.txt"
    path.write_text("x", encoding="utf-8")
    argv = rr.build_argv(settings_path=tmp_path / "s.json", system_prompt_file=path)
    argv += ["--system-prompt", rr.load_system_prompt()]
    with pytest.raises(rr.Refuse, match="together"):
        rr.verify_argv(argv, system_prompt_file_text="x")


def test_r4_verify_refuses_expected_text_with_no_file_flag(tmp_path):
    argv = rr.build_argv(settings_path=tmp_path / "s.json")
    with pytest.raises(rr.Refuse, match="exactly one"):
        rr.verify_argv(argv, system_prompt_file_text="x")


def test_r4_append_file_flag_is_still_forbidden(tmp_path):
    path = tmp_path / "system_prompt.txt"
    path.write_text("x", encoding="utf-8")
    argv = rr.build_argv(settings_path=tmp_path / "s.json", system_prompt_file=path)
    argv[-2] = "--append-system-prompt-file"
    with pytest.raises(rr.Refuse, match="append-system-prompt-file"):
        rr.verify_argv(argv, system_prompt_file_text="x")


# ------------------------------------------------------- the room file


def test_r5_file_bytes_are_the_hashed_bytes(clean_room):
    text = "a\nb\n"
    spf = rr.write_system_prompt_file(clean_room, text)
    assert spf.path.read_bytes() == b"a\nb\n", "no CRLF translation on Windows"
    assert spf.path.parent == clean_room.root
    with pytest.raises(rr.Refuse, match="already exists"):
        rr.write_system_prompt_file(clean_room, text)


# ------------------------------------------------- A17 for the file


@pytest.mark.parametrize("route", ["exclusion", "combined_analysis"])
def test_r6_band_rejects_the_persona_and_the_pinned_one_liner(route):
    book = rr.resolve_route_book(route, root=ROOT, version="v3")
    low, high = rr.system_file_token_band(rr.build_route_system_prompt(book))
    assert high < PERSONA_TOKENS, "the CLI persona alone must fall outside the band"
    assert low > 183, "the pinned one-liner (file ignored) must fall outside the band"


def test_r6_preflight_passes_with_the_file_loaded(clean_room, fake_claude):
    text = "rules " * 2000                       # 12,000 chars -> band 2,000-6,500
    spf = rr.write_system_prompt_file(clean_room, text)
    fake_claude.set(usage={"input_tokens": 4, "cache_creation_input_tokens": 3000,
                           "cache_read_input_tokens": 0})
    probe = rr.preflight(clean_room, claude=str(fake_claude.path),
                         repo_root=REPO_ROOT, system_prompt_file=spf)
    assert probe.input_tokens == 3004
    argv = fake_claude.invocations()[-1]["argv"]
    assert rr._flag_value(argv, "--system-prompt-file") == str(spf.path)
    assert "--system-prompt" not in argv


def test_r6_preflight_refuses_when_the_file_was_not_loaded(clean_room, fake_claude):
    spf = rr.write_system_prompt_file(clean_room, "rules " * 2000)
    # Default fake usage is the sealed one-liner, 183 tokens: below the band.
    with pytest.raises(rr.Refuse, match="not loaded|A17"):
        rr.preflight(clean_room, claude=str(fake_claude.path),
                     repo_root=REPO_ROOT, system_prompt_file=spf)


def test_r6_preflight_refuses_the_persona_riding_along(clean_room, fake_claude):
    spf = rr.write_system_prompt_file(clean_room, "rules " * 2000)
    fake_claude.set(usage={"input_tokens": 4, "cache_creation_input_tokens": 15_000,
                           "cache_read_input_tokens": 0})
    with pytest.raises(rr.Refuse, match="A17"):
        rr.preflight(clean_room, claude=str(fake_claude.path),
                     repo_root=REPO_ROOT, system_prompt_file=spf)


def test_r6_run_paper_sends_the_file_and_the_paper_on_stdin(clean_room, fake_claude):
    book = rr.resolve_route_book("exclusion", root=ROOT, version="v3")
    spf = rr.write_system_prompt_file(clean_room, rr.build_route_system_prompt(book))
    prompt = rr.build_route_prompt(book, token=TOKEN_B, text="PAPER BODY")
    attempt = rr.run_paper(prompt, room=clean_room, token=TOKEN_B, paper_id="P1",
                           claude=str(fake_claude.path), repo_root=REPO_ROOT,
                           system_prompt_file=spf)
    assert attempt.ok
    argv = fake_claude.invocations()[-1]["argv"]
    assert rr._flag_value(argv, "--system-prompt-file") == str(spf.path)


def test_r6_run_paper_refuses_a_file_edited_mid_round(clean_room, fake_claude):
    spf = rr.write_system_prompt_file(clean_room, "original")
    spf.path.write_text("edited", encoding="utf-8")
    with pytest.raises(rr.Refuse, match="does not match"):
        rr.run_paper("x", room=clean_room, token=TOKEN_B, paper_id="P1",
                     claude=str(fake_claude.path), repo_root=REPO_ROOT,
                     system_prompt_file=spf)
    assert fake_claude.invocations() == [], "nothing spawned"


# ------------------------------------------------------ provenance


def test_r7_run_environment_records_the_layout_and_the_sent_hash(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    record = tmp_path / "raw" / "system_prompt.txt"
    env = rr.build_run_environment(
        task="exclusion", round_no=1, argv=["claude"], promptbook_version="v3",
        promptbook_text="book", settings_path=settings, tools_offered=[],
        claude_code_version="x", started_at="t", repo_root=tmp_path,
        system_prompt_text="SYSTEM", system_prompt_record=record)
    assert env["prompt_layout"] == rr.LAYOUT_SYSTEM
    assert env["system_prompt_sha256"] == rr.sha256_text("SYSTEM")
    assert env["system_prompt_path"] == str(Path("raw") / "system_prompt.txt")


def test_r7_sandwich_run_environment_is_unchanged(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    env = rr.build_run_environment(
        task="exclusion", round_no=1, argv=["claude"], promptbook_version="v2",
        promptbook_text="book", settings_path=settings, tools_offered=[],
        claude_code_version="x", started_at="t", repo_root=REPO_ROOT)
    assert env["prompt_layout"] == rr.LAYOUT_SANDWICH
    assert env["system_prompt_sha256"] == rr.sha256_text(rr.load_system_prompt())
