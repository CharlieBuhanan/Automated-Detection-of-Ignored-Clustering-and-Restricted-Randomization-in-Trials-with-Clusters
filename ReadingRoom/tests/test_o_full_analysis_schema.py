"""Group O: the ground-truth-shaped answer contract (plan steps 1-3).

Offline. Covers the strict models in `schemas` (ExclusionWithReason,
FullAnalysis), the field dictionary, and the v2 combined promptbook. A partial,
extra, coerced, or self-contradicting answer must be rejected, never patched.
"""

from __future__ import annotations

import copy
import csv
import importlib.util
import json
import re
from pathlib import Path

import pytest

import schemas

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = Path(__file__).parent / "fixtures" / "full_analysis_example.json"
V2 = ROOT / "promptbooks" / "v2"


@pytest.fixture
def answer() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def reject(payload: dict, match: str | None = None) -> None:
    with pytest.raises(schemas.ParseFailure, match=match):
        schemas.parse_full_analysis(json.dumps(payload))


# ------------------------------------------------------------- accept


def test_example_parses_and_splits_into_two_legacy_rows(answer):
    full, fenced = schemas.parse_full_analysis(json.dumps(answer))
    assert not fenced
    rows = full.task_decisions()
    assert list(rows) == ["power_analysis", "data_analysis"]
    assert rows["power_analysis"].task == "power_analysis"
    assert rows["data_analysis"].paper_id == "TOKEN0001"
    assert full.design.n_levels() == 3           # 4 units, Q8: units - 1


def test_fenced_reply_is_accepted_and_reported(answer):
    _, fenced = schemas.parse_full_analysis("```json\n" + json.dumps(answer) + "\n```")
    assert fenced


def test_wrapper_token_fills_a_missing_paper_id(answer):
    del answer["paper_id"]
    full, _ = schemas.parse_full_analysis(json.dumps(answer), paper_id="TOK")
    assert full.paper_id == "TOK"


def test_other_label_is_accepted(answer):
    answer["design"]["levels"][2]["unit"] = "other: food pantry"
    answer["design"]["unit_rand"] = "other: food pantry"
    answer["design"]["correlated_units"] = ["physician", "other: food pantry"]
    answer["data_analysis"]["done"]["levels_modeled"] = ["physician", "other: food pantry"]
    answer["power_analysis"]["done"]["units_accounted"] = ["other: food pantry"]
    for task in ("power_analysis", "data_analysis"):
        answer[task]["should"]["units"] = ["physician", "other: food pantry"]
    full, _ = schemas.parse_full_analysis(json.dumps(answer))
    assert schemas.other_label(full.design.unit_rand) == "food pantry"
    assert schemas.other_labels(full) == [
        ("design.levels[2].unit", "food pantry"),
        ("design.unit_rand", "food pantry"),
        ("design.correlated_units[1]", "food pantry"),
        ("power_analysis.should.units[1]", "food pantry"),
        ("power_analysis.done.units_accounted[0]", "food pantry"),
        ("data_analysis.should.units[1]", "food pantry"),
        ("data_analysis.done.levels_modeled[1]", "food pantry"),
    ]


def test_other_labels_ignore_free_text(answer):
    answer["data_analysis"]["comment"]["note"] = "other: this is prose"
    answer["power_analysis"]["done"]["source_note"] = "other: also prose"
    full, _ = schemas.parse_full_analysis(json.dumps(answer))
    assert schemas.other_labels(full) == []


def test_no_power_calculation_is_all_null(answer):
    answer["power_analysis"]["done"] = {
        "reported": "no", "clustering": None, "units_accounted": [],
        "restricted_rand": None, "longitudinality": None, "method": None,
        "source_note": None, "timing": None}
    answer["power_analysis"]["promptbook_evidence"] = "P6"
    schemas.parse_full_analysis(json.dumps(answer))


# ------------------------------------------------------------- reject: shape


@pytest.mark.parametrize("path", [
    ("design",), ("power_analysis",), ("data_analysis", "comment"),
    ("design", "icc"), ("power_analysis", "done", "timing"),
    ("design", "levels", 0, "count", "per"),
])
def test_a_missing_key_is_rejected(answer, path):
    node = answer
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    reject(answer)


@pytest.mark.parametrize("path", [(), ("design",), ("power_analysis", "done"),
                                  ("data_analysis", "comment")])
def test_an_extra_key_is_rejected(answer, path):
    node = answer
    for key in path:
        node = node[key]
    node["surprise"] = 1
    reject(answer, "xtra")


def test_strings_are_not_coerced_to_numbers(answer):
    answer["design"]["n_trt"] = "2"
    reject(answer)


def test_a_misspelled_list_value_is_rejected_not_normalized(answer):
    answer["design"]["levels"][2]["unit"] = "Clinic"
    reject(answer, "other: <label>")


def test_an_overlong_other_label_is_rejected(answer):
    answer["data_analysis"]["done"]["method"] = "other: " + "x" * 61
    reject(answer, "cap is 60")


def test_reasoning_over_the_cap_is_rejected(answer):
    answer["data_analysis"]["reasoning"] = "x" * (schemas.REASONING_MAX_CHARS + 1)
    reject(answer)


def test_wrong_text_is_not_a_post_gate_decision(answer):
    answer["power_analysis"]["decision"] = "wrong_text"
    reject(answer)


# ------------------------------------------------------------- reject: design


@pytest.mark.parametrize("count, match", [
    ({"kind": "exact", "value": None, "low": None, "high": None, "per": None}, "needs value"),
    ({"kind": "range", "value": None, "low": 8, "high": 5, "per": None}, "below high"),
    ({"kind": "not_reported", "value": 3, "low": None, "high": None, "per": None}, "no numbers"),
])
def test_count_shapes(answer, count, match):
    answer["design"]["levels"][1]["count"] = count
    reject(answer, match)


def test_per_must_name_an_outer_level(answer):
    answer["design"]["levels"][1]["count"]["per"] = "patient"
    reject(answer, "not a level further out")


def test_unit_rand_must_be_a_level(answer):
    answer["design"]["unit_rand"] = "school"
    reject(answer, "not one of the levels")


def test_ind_samp_unit_cannot_sit_below_unit_rand(answer):
    answer["design"]["ind_samp_unit"] = "physician"
    reject(answer, "further out")


def test_a_grouping_is_never_a_correlated_unit(answer):
    answer["design"]["correlated_units"].append("matched_pair")
    reject(answer, "restriction grouping")


def test_a_pair_level_needs_restricted_status(answer):
    answer["design"]["restricted_randomization"] = {
        "status": "none", "schemes": [], "variables": None}
    reject(answer, "matched_pair/stratum")


def test_schemes_only_when_restricted(answer):
    answer["design"]["restricted_randomization"]["schemes"] = []
    reject(answer, "schemes")


def test_several_iccs_each_need_a_level(answer):
    answer["design"]["icc"]["values"][1]["applies_to"] = None
    reject(answer, "applies_to")


# ------------------------------------------------------- reject: consistency


def test_all_levels_must_cover_every_correlated_unit(answer):
    done = answer["data_analysis"]["done"]
    done["levels_modeled"] = ["clinic"]
    reject(answer, "all_levels")


def test_power_yes_with_some_levels_is_rejected(answer):
    answer["power_analysis"]["decision"] = "yes"
    reject(answer, "requires clustering 'all_levels'")


def test_data_yes_with_restriction_ignored_is_rejected(answer):
    answer["data_analysis"]["done"]["restricted_rand"] = "ignored"
    reject(answer, "restriction accounted")


def test_data_yes_with_cluster_fixed_effects_is_rejected(answer):
    answer["data_analysis"]["done"]["method"] = "cluster_fixed_effects"
    reject(answer, "D6/D7")


def test_longitudinality_must_match_n_long(answer):
    answer["design"]["n_long"] = 1
    reject(answer, "n_long is 1")


def test_unrestricted_design_needs_not_applicable(answer):
    design = answer["design"]
    design["levels"].pop()                       # drop the matched_pair level
    design["ind_samp_unit"] = "clinic"
    design["restricted_randomization"] = {"status": "none", "schemes": [], "variables": None}
    reject(answer, "must be 'not_applicable'")


def test_a_comment_tag_must_agree_with_done(answer):
    answer["data_analysis"]["comment"]["tags"] = ["restriction_ignored"]
    reject(answer, "restriction_ignored")


def test_there_is_no_few_clusters_tag(answer):
    """Its threshold is still open with Deb, so the contract makes no such call."""
    answer["data_analysis"]["comment"]["tags"] = ["few_clusters_no_correction"]
    reject(answer, "data_comment tag")


def test_should_is_asked_of_both_judgments(answer):
    del answer["power_analysis"]["should"]
    reject(answer, "should")


def test_should_may_disagree_with_done_and_the_design(answer):
    """A second opinion to compare with the derived value, not a constraint."""
    answer["data_analysis"]["should"] = {"units": ["clinic"], "restricted_rand": False,
                                         "longitudinality": False}
    schemas.parse_full_analysis(json.dumps(answer))


@pytest.mark.parametrize("units, message", [(["ward"], "not levels above the person"),
                                            (["patient"], "not levels above the person"),
                                            (["matched_pair"], "restriction grouping")])
def test_should_units_are_real_cluster_levels(answer, units, message):
    answer["power_analysis"]["should"]["units"] = units
    reject(answer, message)


def test_should_flags_are_strict_booleans(answer):
    answer["data_analysis"]["should"]["longitudinality"] = "true"
    reject(answer, "bool")


def test_no_analysis_cannot_be_correct(answer):
    answer["data_analysis"]["done"] = {
        "method": "not_reported", "planned_only": None, "levels_modeled": [],
        "clustering": None, "restricted_rand": None, "longitudinality": None,
        "small_sample_correction": None}
    reject(answer, "D4")


def test_power_and_data_are_not_checked_against_each_other(answer):
    """Independence: opposite verdicts on the same design are legal."""
    assert answer["power_analysis"]["decision"] != answer["data_analysis"]["decision"]
    schemas.parse_full_analysis(json.dumps(answer))


# ------------------------------------------------------------- exclusion


def gate(**changes) -> str:
    payload = {"decision": "yes", "exclusion_reason": "E5", "reasoning": "says secondary",
               "promptbook_evidence": "E5", "confidence": 0.9} | changes
    return json.dumps(payload)


def test_exclusion_reason_round_trip():
    answer, _ = schemas.parse_exclusion_with_reason(gate(), paper_id="TOK")
    assert answer.reason_name() == "secondary_analysis"
    assert answer.as_decision().task == "exclusion"


@pytest.mark.parametrize("changes", [
    {"exclusion_reason": None},                              # yes needs a reason
    {"exclusion_reason": "E12"},                             # retired rule
    {"exclusion_reason": "E7"},                              # not the cited rule
    {"decision": "no"},                                      # keep carries no reason
    {"decision": "wrong_text", "promptbook_evidence": "WRONG_TEXT"},
])
def test_bad_exclusion_reasons_are_rejected(changes):
    with pytest.raises(schemas.ParseFailure):
        schemas.parse_exclusion_with_reason(gate(**changes))


def test_exclusion_reason_key_is_required():
    payload = json.loads(gate(decision="no", exclusion_reason=None))
    del payload["exclusion_reason"]
    with pytest.raises(schemas.ParseFailure):
        schemas.parse_exclusion_with_reason(json.dumps(payload))


# ------------------------------------------------------- provider schema


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


@pytest.mark.parametrize("build", [schemas.full_analysis_output_schema,
                                   schemas.exclusion_with_reason_output_schema])
def test_output_schema_is_closed_and_self_contained(build):
    schema = build()
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text
    assert "paper_id" not in schema["properties"]
    for node in _walk(schema):
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False
            assert node["required"] == list(node["properties"])
        assert not isinstance(node.get("description"), str)   # no internal docstrings


# ------------------------------------------------------- field dictionary


def _builder():
    path = ROOT / "scripts" / "24_build_field_dictionary.py"
    spec = importlib.util.spec_from_file_location("field_dictionary_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_field_dictionary_is_current_and_in_ground_truth_order():
    builder = _builder()
    assert builder.OUT.read_text(encoding="utf-8") == builder.build()
    with builder.GROUND_TRUTH.open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    with builder.OUT.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["column"] for row in rows] == header
    counts = {}
    for row in rows:
        counts[row["filled_by"]] = counts.get(row["filled_by"], 0) + 1
    assert counts == {"code": 13, "model": 20, "derived": 8, "blank": 2}


# ------------------------------------------------------- promptbook


@pytest.mark.parametrize("prefix, last", [("P", 18), ("D", 15)])
def test_combined_book_defines_every_rule_once(prefix, last):
    """The standalone v2 books were folded in (v2 doc.md); this is the only copy."""
    text = (V2 / "combined_analysis.md").read_text(encoding="utf-8")
    defined = re.findall(rf"^\s*\d+\.\s+\*\*({prefix}\d+)\.", text, flags=re.MULTILINE)
    assert defined == [f"{prefix}{n}" for n in range(1, last + 1)]


def test_v2_has_no_standalone_analysis_books():
    assert not (V2 / "power_analysis.md").exists()
    assert not (V2 / "data_analysis.md").exists()


def test_combined_book_lists_every_vocabulary_value():
    text = (V2 / "combined_analysis.md").read_text(encoding="utf-8")
    for name in ("UNITS", "RESTRICTION_SCHEMES", "DATA_METHODS", "POWER_METHODS",
                 "DATA_COMMENT_TAGS"):
        for value in getattr(schemas, name):
            assert f"`{value}`" in text, f"{name} value {value!r} missing from the promptbook"
