"""Group D -- response parsing, the `src/schemas.py` boundary (D1-D14).

Every case must produce either a valid `Decision` or a logged `ParseFailure`
with the raw text attached. Nothing may be discarded silently: a reply that
vanishes is a paper missing from the denominator, and the accuracy number does
not know it happened.

Pure and offline -- no CLI, no fixtures beyond strings.

Case numbers refer to `TEST_PLAN.md`.
"""

from __future__ import annotations

import json

import pytest

import schemas
from schemas import Decision, ParseFailure, parse_decision


GOOD = {
    "decision": "no",
    "reasoning": "Parallel cluster randomized trial; none of E1-E18 applies.",
    "promptbook_evidence": "E1, E3",
    "confidence": 0.77,
}


def raw(**overrides) -> str:
    payload = {**GOOD, **overrides}
    for key, value in list(payload.items()):
        if value is None:
            del payload[key]
    return json.dumps(payload)


# ------------------------------------------------------------- D1-D3: fences


def test_d1_clean_bare_json():
    decision, was_fenced = parse_decision(raw(), task="exclusion")
    assert decision.decision == "no"
    assert was_fenced is False


def test_d2_json_fence_is_stripped_and_counted():
    decision, was_fenced = parse_decision(f"```json\n{raw()}\n```", task="exclusion")
    assert decision.decision == "no"
    assert was_fenced is True, "the rate is reportable, so it must be returned"


def test_d3_bare_fence_is_stripped():
    decision, was_fenced = parse_decision(f"```\n{raw()}\n```", task="exclusion")
    assert decision.decision == "no"
    assert was_fenced is True


def test_d2_fence_with_surrounding_whitespace():
    decision, was_fenced = parse_decision(f"\n\n  ```json\n{raw()}\n```  \n\n",
                                          task="exclusion")
    assert was_fenced is True and decision.decision == "no"


# ------------------------------------------------------- D4-D7: unparseable


def test_d4_prose_before_the_json_is_a_parse_failure():
    """Not silently salvaged. A model that narrates is a prompt problem."""
    with pytest.raises(ParseFailure) as excinfo:
        parse_decision(f"Here is my answer:\n{raw()}", task="exclusion")
    assert excinfo.value.raw.startswith("Here is my answer")


def test_d5_empty_response():
    with pytest.raises(ParseFailure, match="empty reply"):
        parse_decision("", task="exclusion")


def test_d5_whitespace_only_response():
    with pytest.raises(ParseFailure, match="empty reply"):
        parse_decision("   \n\t  ", task="exclusion")


def test_d6_truncated_json_keeps_the_raw():
    truncated = raw()[:40]
    with pytest.raises(ParseFailure) as excinfo:
        parse_decision(truncated, task="exclusion")
    assert excinfo.value.raw == truncated, "the raw text is the evidence"
    assert "not valid JSON" in str(excinfo.value)


def test_d7_a_json_array_names_the_type():
    with pytest.raises(ParseFailure) as excinfo:
        parse_decision(f"[{raw()}]", task="exclusion")
    assert "list" in str(excinfo.value)


@pytest.mark.parametrize("payload", ['"a string"', "42", "true", "null"])
def test_d7_other_non_object_json_is_named(payload):
    with pytest.raises(ParseFailure, match="expected a JSON object"):
        parse_decision(payload, task="exclusion")


# ------------------------------------------------------------- D8: extra keys


def test_d8_an_extra_field_is_rejected():
    """`extra="forbid"`: an invented field is a prompt problem worth seeing."""
    with pytest.raises(ParseFailure) as excinfo:
        parse_decision(raw(certainty="high"), task="exclusion")
    assert "certainty" in str(excinfo.value)


# --------------------------------------------------------- D9-D10: decisions


@pytest.mark.parametrize("value", ["Yes", " yes ", "YES", "yEs"])
def test_d9_decision_is_normalized(value):
    decision, _ = parse_decision(raw(decision=value), task="exclusion")
    assert decision.decision == "yes"


def test_d10_an_unknown_decision_lists_the_allowed_set():
    with pytest.raises(ParseFailure) as excinfo:
        parse_decision(raw(decision="maybe"), task="exclusion")
    message = str(excinfo.value)
    assert "maybe" in message
    for allowed in schemas.DECISIONS:
        assert allowed in message


def test_d10_an_empty_decision_is_rejected():
    with pytest.raises(ParseFailure):
        parse_decision(raw(decision=""), task="exclusion")


# ------------------------------------------------------- D11-D12: the cap


def test_d11_reasoning_at_exactly_the_cap_is_accepted():
    """Inclusive boundary -- 200 is allowed, not 199."""
    text = "x" * schemas.REASONING_MAX_CHARS
    decision, _ = parse_decision(raw(reasoning=text), task="exclusion")
    assert len(decision.reasoning) == schemas.REASONING_MAX_CHARS


def test_d12_one_char_over_the_cap_states_length_and_cap():
    text = "x" * (schemas.REASONING_MAX_CHARS + 1)
    with pytest.raises(ParseFailure) as excinfo:
        parse_decision(raw(reasoning=text), task="exclusion")
    message = str(excinfo.value)
    assert str(schemas.REASONING_MAX_CHARS + 1) in message
    assert str(schemas.REASONING_MAX_CHARS) in message


def test_d12_the_cap_is_measured_after_whitespace_stripping():
    """`str_strip_whitespace` runs first, so padding does not fail a good reply."""
    text = "  " + "x" * schemas.REASONING_MAX_CHARS + "  "
    decision, _ = parse_decision(raw(reasoning=text), task="exclusion")
    assert len(decision.reasoning) == schemas.REASONING_MAX_CHARS


# --------------------------------------------------- D13-D14: required fields


@pytest.mark.parametrize("value", ["", "   ", None])
def test_d13_reasoning_is_required(value):
    with pytest.raises(ParseFailure):
        parse_decision(raw(reasoning=value), task="exclusion")


@pytest.mark.parametrize("value", ["", "   ", None])
def test_d14_promptbook_evidence_is_required(value):
    with pytest.raises(ParseFailure):
        parse_decision(raw(promptbook_evidence=value), task="exclusion")


def test_d13_the_required_field_message_names_dc13():
    with pytest.raises(ParseFailure, match="DC13"):
        parse_decision(raw(reasoning=""), task="exclusion")


# --------------------------------------------- confidence and the wrong_text rule


@pytest.mark.parametrize("value", [1.5, -0.1, 2, -1])
def test_confidence_outside_the_unit_interval_is_rejected(value):
    with pytest.raises(ParseFailure):
        parse_decision(raw(confidence=value), task="exclusion")


@pytest.mark.parametrize("value", [0.0, 1.0, 0.5])
def test_confidence_boundaries_are_inclusive(value):
    decision, _ = parse_decision(raw(confidence=value), task="exclusion")
    assert decision.confidence == value


def test_missing_confidence_is_rejected():
    with pytest.raises(ParseFailure):
        parse_decision(raw(confidence=None), task="exclusion")


def test_wrong_text_is_accepted_on_exclusion():
    decision, _ = parse_decision(raw(decision="wrong_text"), task="exclusion")
    assert decision.is_abstention()


@pytest.mark.parametrize("task", ["power_analysis", "data_analysis"])
def test_wrong_text_is_rejected_off_exclusion(task):
    with pytest.raises(ParseFailure, match="DC41"):
        parse_decision(raw(decision="wrong_text"), task=task)


# ----------------------------------------------------- the token echo channel


def test_paper_id_is_left_none_when_the_model_omits_it():
    """How E10 is detected: the checker passes paper_id=None so a missing echo
    stays missing rather than being helpfully filled in by the wrapper."""
    decision, _ = parse_decision(raw(), task="exclusion", paper_id=None)
    assert decision.paper_id is None


def test_a_model_supplied_paper_id_survives_parsing():
    decision, _ = parse_decision(raw(paper_id="deadbeefdeadbeef"),
                                 task="exclusion", paper_id=None)
    assert decision.paper_id == "deadbeefdeadbeef"


def test_the_wrapper_default_fills_paper_id_only_when_absent():
    decision, _ = parse_decision(raw(), task="exclusion", paper_id="REAL01")
    assert decision.paper_id == "REAL01"


# ------------------------------------------------------------------ helpers


@pytest.mark.parametrize("evidence,expected", [
    ("E1", ["E1"]),
    ("E1, E3", ["E1", "E3"]),
    ("rules E12 and P4", ["E12", "P4"]),
    ("no rule here", []),
    ("E1E2", []),                     # not word-bounded; not a citation
])
def test_cited_rules_extraction(evidence, expected):
    decision = Decision(**{**GOOD, "promptbook_evidence": evidence})
    assert decision.cited_rules() == expected


@pytest.mark.parametrize("decision,expected", [
    ("yes", False), ("no", False), ("undecidable", True), ("wrong_text", True)])
def test_is_abstention(decision, expected):
    assert Decision(**{**GOOD, "decision": decision}).is_abstention() is expected


# -------------------------------------------- the Batch route shares the model


@pytest.mark.parametrize("task", schemas.TASKS)
def test_tool_schema_matches_the_cli_route(task):
    """DC35: one model, both routes, so they cannot drift on what they accept."""
    schema = schemas.tool_schema(task)
    properties = schema["input_schema"]["properties"]
    assert set(properties) == {"decision", "reasoning", "promptbook_evidence",
                               "confidence"}
    assert properties["reasoning"]["maxLength"] == schemas.REASONING_MAX_CHARS
    assert schema["input_schema"]["additionalProperties"] is False
    expected = ["yes", "no", "undecidable"] + (
        ["wrong_text"] if task == "exclusion" else [])
    assert properties["decision"]["enum"] == expected


def test_tool_schema_refuses_an_unknown_task():
    with pytest.raises(ValueError, match="unknown task"):
        schemas.tool_schema("inclusion")
