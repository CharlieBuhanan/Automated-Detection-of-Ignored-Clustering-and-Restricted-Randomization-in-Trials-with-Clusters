"""Combined post-gate response contract (DC54)."""

from __future__ import annotations

import json

import pytest

import schemas
from schemas import ParseFailure, parse_combined_analysis


POWER = {
    "decision": "yes",
    "reasoning": "The sample-size calculation and assumptions are reported.",
    "promptbook_evidence": "P1",
    "confidence": 0.81,
}
DATA = {
    "decision": "no",
    "reasoning": "The analysis ignores the cluster-randomized design.",
    "promptbook_evidence": "D2",
    "confidence": 0.63,
}


def raw(**overrides) -> str:
    payload = {"paper_id": "blind-token", "power_analysis": POWER,
               "data_analysis": DATA}
    payload.update(overrides)
    return json.dumps(payload)


def test_combined_response_binds_both_tasks_and_the_shared_token():
    combined, fenced = parse_combined_analysis(raw())
    assert fenced is False
    assert combined.paper_id == "blind-token"
    assert list(combined.task_decisions()) == list(schemas.ANALYSIS_TASKS)
    assert combined.power_analysis.task == "power_analysis"
    assert combined.data_analysis.task == "data_analysis"
    assert combined.power_analysis.paper_id == combined.data_analysis.paper_id == "blind-token"


def test_combined_response_accepts_a_json_fence():
    combined, fenced = parse_combined_analysis(f"```json\n{raw()}\n```")
    assert fenced is True
    assert combined.data_analysis.decision == "no"


def test_combined_response_requires_both_halves_and_keeps_raw_text():
    reply = raw(data_analysis=None)
    with pytest.raises(ParseFailure) as excinfo:
        parse_combined_analysis(reply)
    assert excinfo.value.raw == reply
    assert "data_analysis" in str(excinfo.value)


@pytest.mark.parametrize("task", schemas.ANALYSIS_TASKS)
def test_combined_response_rejects_exclusion_only_wrong_text(task):
    payload = json.loads(raw())
    payload[task]["decision"] = "wrong_text"
    with pytest.raises(ParseFailure, match="DC41"):
        parse_combined_analysis(json.dumps(payload))


def test_combined_response_rejects_an_extra_top_level_field():
    with pytest.raises(ParseFailure, match="Extra inputs"):
        parse_combined_analysis(raw(summary="not requested"))


@pytest.mark.parametrize("field", ["task", "paper_id"])
def test_combined_response_rejects_nested_wrapper_metadata(field):
    payload = json.loads(raw())
    payload["power_analysis"][field] = "not-owned-by-model"
    with pytest.raises(ParseFailure, match="wrapper-owned"):
        parse_combined_analysis(json.dumps(payload))


def test_combined_parser_uses_a_wrapper_token_only_when_the_model_omits_it():
    payload = json.loads(raw())
    del payload["paper_id"]
    combined, _ = parse_combined_analysis(json.dumps(payload), paper_id="wrapper-token")
    assert combined.paper_id == "wrapper-token"
    assert {decision.paper_id for decision in combined.task_decisions().values()} == {"wrapper-token"}


def test_combined_batch_schema_requires_two_clean_task_objects():
    schema = schemas.combined_analysis_tool_schema()
    input_schema = schema["input_schema"]
    assert schema["name"] == "record_combined_analysis_decisions"
    assert input_schema["required"] == list(schemas.ANALYSIS_TASKS)
    assert input_schema["additionalProperties"] is False
    assert set(input_schema["properties"]) == set(schemas.ANALYSIS_TASKS)
    for task, nested in input_schema["properties"].items():
        assert nested["additionalProperties"] is False
        assert set(nested["properties"]) == {
            "decision", "reasoning", "promptbook_evidence", "confidence"}
        assert nested["properties"]["decision"]["enum"] == ["yes", "no", "undecidable"]
        assert nested["properties"]["reasoning"]["maxLength"] == schemas.REASONING_MAX_CHARS
