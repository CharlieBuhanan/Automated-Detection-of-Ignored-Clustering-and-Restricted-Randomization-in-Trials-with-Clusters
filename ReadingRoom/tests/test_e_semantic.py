"""Group E -- semantic validation (E1-E12). The quiet failures.

Everything here is a structurally valid `Decision`. It parsed, it validated, and
it is still wrong -- which is the dangerous kind, because it scores. A reply
citing rule `E99` looks exactly like a reply citing `E9` until something checks
the promptbook.

Three of these are round-level FATALs rather than per-paper retries (E8, E9,
E11), for the same reason A1 is: they are evidence about the harness, not about
the paper that happened to surface them.

Offline. Case numbers refer to `TEST_PLAN.md`.
"""

from __future__ import annotations

import json

import pytest

import reading_room as rr
import schemas

KNOWN = {"E1", "E2", "E3", "E5", "E12", "E18"}
TOKEN = "abcdef0123456789"


def decision(**overrides) -> schemas.Decision:
    base = {"decision": "no", "reasoning": "Parallel CRT; no exclusion applies.",
            "promptbook_evidence": "E1", "confidence": 0.7, "paper_id": TOKEN}
    return schemas.Decision(**{**base, **overrides})


# ------------------------------------------------------------ E1/E2: wrong_text


@pytest.mark.parametrize("task", ["power_analysis", "data_analysis"])
def test_e1_wrong_text_off_exclusion_is_rejected(task):
    """DC41. Power and data see gate survivors, which already passed that check."""
    with pytest.raises(rr.SemanticFailure) as excinfo:
        rr.check_decision(decision(decision="wrong_text", promptbook_evidence="P1"),
                          task=task, token=TOKEN, known_rules={"P1"})
    assert excinfo.value.case == "E1"
    assert "DC41" in str(excinfo.value)


def test_e2_wrong_text_on_exclusion_is_accepted():
    """Routed to human review, not scored -- and not a retry."""
    call = decision(decision="wrong_text", promptbook_evidence="WRONG_TEXT")
    rr.check_decision(call, task="exclusion", token=TOKEN, known_rules=KNOWN)
    assert call.is_abstention()


def test_e2_wrong_text_cites_the_promptbooks_own_sentinel_not_a_rule():
    """v1 exclusion's response table: "the criterion number that decided it,
    e.g. E5; WRONG_TEXT if that decision". No numbered rule decides wrong_text,
    so demanding one would reject the evidence the promptbook asks for.

    Found by the first live run, where the model followed the promptbook and
    this checker failed it.
    """
    rr.check_decision(decision(decision="wrong_text", promptbook_evidence="WRONG_TEXT"),
                      task="exclusion", token=TOKEN, known_rules=KNOWN)
    rr.check_decision(decision(decision="wrong_text", promptbook_evidence="wrong_text"),
                      task="exclusion", token=TOKEN, known_rules=KNOWN)


def test_e2_wrong_text_still_has_to_say_something():
    """The exception is one specific word, not a licence to write prose."""
    with pytest.raises(rr.SemanticFailure) as excinfo:
        rr.check_decision(decision(decision="wrong_text",
                                   promptbook_evidence="it is a letter"),
                          task="exclusion", token=TOKEN, known_rules=KNOWN)
    assert excinfo.value.case == "E6"


def test_the_prompt_tells_the_model_the_wrong_text_convention():
    """Or the model is guessing at a convention the checker enforces."""
    prompt = rr.build_prompt(promptbook="x", token=TOKEN, text="t", task="exclusion")
    assert "WRONG_TEXT" in prompt


# ------------------------------------------------- E3-E6: the cited rule exists


def test_e3_a_rule_that_does_not_exist_is_rejected():
    with pytest.raises(rr.SemanticFailure) as excinfo:
        rr.check_decision(decision(promptbook_evidence="E99"), task="exclusion",
                          token=TOKEN, known_rules=KNOWN)
    assert "E99" in str(excinfo.value)
    assert excinfo.value.case == "E3/E5"


def test_e3_the_failure_lists_the_rules_that_do_exist():
    with pytest.raises(rr.SemanticFailure) as excinfo:
        rr.check_decision(decision(promptbook_evidence="E99"), task="exclusion",
                          token=TOKEN, known_rules=KNOWN)
    assert "E12" in str(excinfo.value), "naming the real set is what makes it fixable"


def test_e4_the_wrong_tasks_prefix_is_rejected():
    with pytest.raises(rr.SemanticFailure) as excinfo:
        rr.check_decision(decision(promptbook_evidence="P3"), task="exclusion",
                          token=TOKEN, known_rules=KNOWN)
    assert excinfo.value.case == "E4"
    assert "P3" in str(excinfo.value)


def test_e4_is_checked_before_existence():
    """`P3` on an exclusion paper is a task error, not a typo -- and saying so
    points at the real problem, which is that the model cited another book."""
    with pytest.raises(rr.SemanticFailure) as excinfo:
        rr.check_decision(decision(promptbook_evidence="P3"), task="exclusion",
                          token=TOKEN, known_rules=KNOWN | {"P3"})
    assert excinfo.value.case == "E4"


def test_e5_a_rule_from_a_previous_version_is_rejected(promptbook_text):
    """Checked against the version actually in force, not against any version."""
    v0_rules = rr.promptbook_rule_ids(promptbook_text + "\n4. **E4. Old rule.**\n",
                                      "exclusion")
    v1_rules = rr.promptbook_rule_ids(promptbook_text, "exclusion")
    assert "E4" in v0_rules and "E4" not in v1_rules

    rr.check_decision(decision(promptbook_evidence="E4"), task="exclusion",
                      token=TOKEN, known_rules=v0_rules)          # fine under v0
    with pytest.raises(rr.SemanticFailure):                        # not under v1
        rr.check_decision(decision(promptbook_evidence="E4"), task="exclusion",
                          token=TOKEN, known_rules=v1_rules)


def test_e6_prose_with_no_rule_id_is_rejected():
    with pytest.raises(rr.SemanticFailure) as excinfo:
        rr.check_decision(
            decision(promptbook_evidence="The trial is clearly randomized by clinic."),
            task="exclusion", token=TOKEN, known_rules=KNOWN)
    assert excinfo.value.case == "E6"
    assert "DC13" in str(excinfo.value)


def test_e6_prose_around_a_real_rule_id_is_fine():
    """The requirement is that a rule is named, not that nothing else is said."""
    rr.check_decision(decision(promptbook_evidence="E3 applies: stepped wedge."),
                      task="exclusion", token=TOKEN, known_rules=KNOWN)


def test_several_valid_rules_are_all_checked():
    rr.check_decision(decision(promptbook_evidence="E1, E3 and E12"),
                      task="exclusion", token=TOKEN, known_rules=KNOWN)
    with pytest.raises(rr.SemanticFailure):
        rr.check_decision(decision(promptbook_evidence="E1, E3 and E77"),
                          task="exclusion", token=TOKEN, known_rules=KNOWN)


# ------------------------------------------------- promptbook_rule_ids itself


def test_rule_ids_are_read_from_the_promptbook_in_force(promptbook_text):
    assert rr.promptbook_rule_ids(promptbook_text, "exclusion") == {"E1", "E2", "E3"}


def test_rule_ids_are_filtered_to_this_tasks_prefix():
    mixed = "E1 and P1 and D1 all appear here"
    assert rr.promptbook_rule_ids(mixed, "exclusion") == {"E1"}
    assert rr.promptbook_rule_ids(mixed, "power_analysis") == {"P1"}
    assert rr.promptbook_rule_ids(mixed, "data_analysis") == {"D1"}


def test_the_real_v1_promptbooks_define_rules(promptbooks):
    """A promptbook whose ids this cannot read would reject every reply."""
    version, _, text = rr.resolve_promptbook("exclusion")
    rules = rr.promptbook_rule_ids(text, "exclusion")
    assert {"E1", "E3", "E18"} <= rules, f"{version} exclusion rules: {sorted(rules)}"


# ------------------------------------------------------------- E7: confidence


@pytest.mark.parametrize("value", [1.5, -0.1])
def test_e7_confidence_outside_the_bound_never_becomes_a_decision(value):
    """Enforced by pydantic, so it cannot reach `check_decision` at all."""
    with pytest.raises(Exception):
        decision(confidence=value)


# --------------------------------------------------------- E8: constant scores


def test_e8_identical_confidence_across_a_round_fails_it():
    assert rr.constant_confidence([0.8] * 50) is True


def test_e8_any_variation_passes():
    assert rr.constant_confidence([0.8] * 49 + [0.7]) is False


def test_e8_abstains_on_a_smoke_test():
    """Three identical values in a 3-paper run is a coincidence, not a finding."""
    assert rr.constant_confidence([0.8, 0.8, 0.8]) is False


def test_e8_the_minimum_is_the_boundary():
    assert rr.constant_confidence([0.5] * 9) is False
    assert rr.constant_confidence([0.5] * 10) is True


def test_e8_ignores_missing_values():
    assert rr.constant_confidence([0.5] * 10 + [None] * 5) is True


# ------------------------------------------------------- E9/E10: the token echo


def test_e9_a_different_token_discards_the_round():
    """Either the harness crossed two responses or the model saw an identifier
    it was never given. Neither is a one-paper problem."""
    with pytest.raises(rr.RoundDiscarded) as excinfo:
        rr.check_token_echo(decision(paper_id="0000000000000000"), TOKEN)
    assert "E9" in str(excinfo.value)
    assert TOKEN in str(excinfo.value)


def test_e9_the_right_token_passes():
    rr.check_token_echo(decision(paper_id=TOKEN), TOKEN)


def test_e9_whitespace_around_the_token_is_tolerated():
    """`str_strip_whitespace` handles it, but pin it: failing a whole round on a
    trailing space would be an expensive way to be pedantic."""
    rr.check_token_echo(decision(paper_id=f"  {TOKEN}  "), TOKEN)


def test_e10_a_missing_token_is_a_retry_not_a_fatal():
    call = schemas.Decision(decision="no", reasoning="r",
                            promptbook_evidence="E1", confidence=0.5)
    rr.check_token_echo(call, TOKEN)          # not fatal: nothing was crossed
    with pytest.raises(rr.SemanticFailure) as excinfo:
        rr.check_decision(call, task="exclusion", token=TOKEN, known_rules=KNOWN)
    assert excinfo.value.case == "E10"


# ------------------------------------------------------ E11: a real paper_id


def test_e11_a_real_paper_id_in_the_reply_discards_the_round():
    real = {"XHFTHUCG", "3JVAWNIE", "WPF7MUCV"}
    reply = json.dumps({"decision": "no", "reasoning": "Similar to 3JVAWNIE.",
                        "promptbook_evidence": "E1", "confidence": 0.6})
    with pytest.raises(rr.RoundDiscarded) as excinfo:
        rr.check_no_real_paper_ids(reply, TOKEN, real)
    assert "3JVAWNIE" in str(excinfo.value)
    assert "E11" in str(excinfo.value)


def test_e11_the_blinded_token_itself_is_not_a_leak():
    """The model is explicitly asked to echo it."""
    rr.check_no_real_paper_ids(f'{{"paper_id": "{TOKEN}"}}', TOKEN, {TOKEN, "ABC12345"})


def test_e11_a_clean_reply_passes():
    reply = json.dumps({"decision": "no", "reasoning": "Parallel CRT.",
                        "promptbook_evidence": "E1", "confidence": 0.6})
    rr.check_no_real_paper_ids(reply, TOKEN, {"XHFTHUCG", "3JVAWNIE"})


def test_e11_matches_on_word_boundaries_only():
    """A key embedded in a longer word is a coincidence, not a citation."""
    rr.check_no_real_paper_ids("the sequence ABC12345XYZ appears", TOKEN, {"ABC12345"})


# ---------------------------------------------------- E12: naming another paper


@pytest.mark.parametrize("text", [
    "This mirrors Cattamanchi et al. 2021.",
    "Similar to Bernabe (2020).",
    "As in Smith & Lee 2019, clustering was ignored.",
    "Following Jones and Brown 2018.",
])
def test_e12_a_named_citation_is_flagged(text):
    assert rr.flag_other_papers(text), f"should flag: {text}"


@pytest.mark.parametrize("text", [
    "Parallel cluster randomized trial with 40 clinics.",
    "The 2019 cohort was analysed with a GLMM.",
    "E3 applies: stepped wedge.",
])
def test_e12_ordinary_reasoning_is_not_flagged(text):
    assert rr.flag_other_papers(text) == []


def test_e12_is_a_flag_not_a_rejection():
    """A promptbook rule can legitimately name a source, so this cannot fail a
    paper -- it goes on the human review list."""
    call = decision(reasoning="Design matches Cattamanchi et al. 2021.")
    rr.check_decision(call, task="exclusion", token=TOKEN, known_rules=KNOWN)
    assert rr.flag_other_papers(call.reasoning)


# --------------------------------------------- pulling the reply out of a stream


def test_assistant_text_concatenates_text_blocks_in_order():
    from conftest import assistant_text, stream
    text = stream(
        {"type": "system", "subtype": "init"},
        assistant_text('{"decision":'),
        assistant_text(' "no"}'),
        {"type": "result", "subtype": "success", "result": "ignored"},
    )
    assert rr.assistant_text(text) == '{"decision": "no"}'


def test_assistant_text_falls_back_to_the_result_field():
    from conftest import stream
    text = stream({"type": "result", "subtype": "success", "result": '{"decision": "no"}'})
    assert rr.assistant_text(text) == '{"decision": "no"}'


def test_assistant_text_survives_a_garbled_stream():
    assert rr.assistant_text("not json\n\n{bad}\n") == ""


def test_assistant_text_ignores_non_text_blocks():
    from conftest import stream
    text = stream({"type": "assistant", "message": {"content": [
        {"type": "thinking", "thinking": "hmm"},
        {"type": "text", "text": "answer"}]}})
    assert rr.assistant_text(text) == "answer"
