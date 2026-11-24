"""Group P: the ground-truth answer shape wired into the Reading Room (plan step 4).

Offline. A promptbook version picks its answer shape from an explicit table:
v0/v1 keep the round-1 shape byte-for-byte, v2+ ask for and store the full
answer. Covers route resolution, prompts, the parse-and-check entry point,
storage beside the judgment rows, the other-label log, and the API schema.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

import api_contract
import db
import reading_room as rr
import schemas

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = Path(__file__).parent / "fixtures" / "full_analysis_example.json"
CHECKER = ROOT / "scripts" / "21_check_responses.py"
TOKEN = "TOKEN0001"


@pytest.fixture
def answer() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


@pytest.fixture
def v2_combined() -> rr.RouteBook:
    return rr.resolve_route_book(rr.COMBINED_ANALYSIS_ROUTE, root=ROOT, version="v2")


@pytest.fixture
def v2_gate() -> rr.RouteBook:
    return rr.resolve_route_book("exclusion", root=ROOT, version="v2")


def gate(**changes) -> str:
    payload = {"decision": "yes", "exclusion_reason": "E5",
               "reasoning": "Calls itself a secondary analysis.",
               "promptbook_evidence": "E5", "confidence": 0.9, "paper_id": TOKEN}
    payload.update(changes)
    return json.dumps(payload)


def load_checker():
    spec = importlib.util.spec_from_file_location("checker_p", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------- the version table


@pytest.mark.parametrize("version, contract", [
    ("v0", rr.CONTRACT_LEGACY), ("v1", rr.CONTRACT_LEGACY),
    ("v2", rr.CONTRACT_GROUND_TRUTH), ("v3", rr.CONTRACT_GROUND_TRUTH)])
def test_each_version_has_one_answer_shape(version, contract):
    assert rr.response_contract(version) == contract


# ---------------------------------------------------------------- resolving


def test_v1_combined_hashes_the_same_bytes_as_before():
    """Paid v1 evidence re-checks only if the hashed promptbook is unchanged."""
    book = rr.resolve_route_book(rr.COMBINED_ANALYSIS_ROUTE, root=ROOT, version="v1")
    v1 = ROOT / "promptbooks" / "v1"
    expected = rr.combined_analysis_promptbook(
        power_analysis=(v1 / "power_analysis.md").read_text(encoding="utf-8"),
        data_analysis=(v1 / "data_analysis.md").read_text(encoding="utf-8"))
    assert book.contract == rr.CONTRACT_LEGACY and book.promptbook == expected


def test_v2_combined_reads_one_book(v2_combined):
    assert v2_combined.paths == (ROOT / "promptbooks" / "v2" / rr.FULL_ANALYSIS_BOOK,)
    assert v2_combined.known_rules["power_analysis"] == {f"P{n}" for n in range(1, 19)}
    assert v2_combined.known_rules["data_analysis"] == {f"D{n}" for n in range(1, 16)}


@pytest.mark.parametrize("task", schemas.ANALYSIS_TASKS)
def test_v2_refuses_a_single_task_analysis_route(task):
    with pytest.raises(rr.Refuse, match="judged together"):
        rr.resolve_route_book(task, root=ROOT, version="v2")


@pytest.mark.parametrize("version", ["../v1", "", "v1/..", "v99"])
def test_a_bad_version_is_refused(version):
    with pytest.raises(rr.Refuse):
        rr.resolve_route_book("exclusion", root=ROOT, version=version)


def test_current_is_read_when_no_version_is_given(tmp_path):
    books = tmp_path / "promptbooks"
    (books / "v2").mkdir(parents=True)
    (books / "v2" / "exclusion.md").write_text("E1. x\n", encoding="utf-8")
    (books / "CURRENT").write_text("v2\n", encoding="utf-8")
    book = rr.resolve_route_book("exclusion", root=tmp_path)
    assert (book.version, book.contract) == ("v2", rr.CONTRACT_GROUND_TRUTH)


def test_a_missing_combined_book_refuses_rather_than_falls_back(tmp_path):
    books = tmp_path / "promptbooks" / "v2"
    books.mkdir(parents=True)
    (books / "power_analysis.md").write_text("P1. x\n", encoding="utf-8")
    (books / "data_analysis.md").write_text("D1. x\n", encoding="utf-8")
    with pytest.raises(rr.Refuse, match="combined_analysis.md"):
        rr.resolve_route_book(rr.COMBINED_ANALYSIS_ROUTE, root=tmp_path, version="v2")


# ------------------------------------------------------------------ prompts


def test_v1_prompts_are_byte_identical_to_the_legacy_builders():
    for route in ("exclusion", rr.COMBINED_ANALYSIS_ROUTE):
        book = rr.resolve_route_book(route, root=ROOT, version="v1")
        got = rr.build_route_prompt(book, token=TOKEN, text="paper")
        if route == "exclusion":
            want = rr.build_prompt(promptbook=book.promptbook, token=TOKEN,
                                   text="paper", task="exclusion")
        else:
            want = rr.build_combined_analysis_prompt(
                power_promptbook=book.texts["power_analysis"],
                data_promptbook=book.texts["data_analysis"], token=TOKEN, text="paper")
        assert got == want


def test_v2_combined_prompt_sends_one_book_and_asks_for_paper_id(v2_combined):
    prompt = rr.build_route_prompt(v2_combined, token=TOKEN, text="paper")
    assert "## Part A" in prompt and "## Answer format" in prompt
    assert "BEGIN POWER_ANALYSIS PROMPTBOOK" not in prompt
    assert f'"paper_id": "{TOKEN}"' in prompt
    assert prompt.rstrip().endswith("It is an abstention, not a category.")


def test_v2_gate_prompt_names_the_reason_range(v2_gate):
    prompt = rr.build_route_prompt(v2_gate, token=TOKEN, text="paper")
    assert "E1-E11, E13-E16" in prompt and '"exclusion_reason"' in prompt
    assert f'"paper_id": "{TOKEN}"' in prompt


# ---------------------------------------------------------- parse and check


def test_a_full_answer_passes_and_keeps_both_rows(answer, v2_combined):
    checked = rr.parse_and_check_reply(json.dumps(answer), book=v2_combined, token=TOKEN)
    assert isinstance(checked.answer, schemas.FullAnalysis)
    assert set(checked.decisions) == set(schemas.ANALYSIS_TASKS)
    assert checked.decisions["power_analysis"].paper_id == TOKEN


def test_a_full_answer_with_no_token_is_e10(answer, v2_combined):
    del answer["paper_id"]
    with pytest.raises(rr.SemanticFailure) as excinfo:
        rr.parse_and_check_reply(json.dumps(answer), book=v2_combined, token=TOKEN)
    assert excinfo.value.case == "E10"


def test_a_full_answer_with_another_token_discards_the_round(answer, v2_combined):
    answer["paper_id"] = "SOMEONEELSE"
    with pytest.raises(rr.RoundDiscarded):
        rr.parse_and_check_reply(json.dumps(answer), book=v2_combined, token=TOKEN)


@pytest.mark.parametrize("evidence, case", [("P5", "E4"), ("D99", "E3/E5"),
                                            ("see above", "E6")])
def test_data_evidence_is_checked_against_the_d_rules(answer, v2_combined, evidence, case):
    answer["data_analysis"]["promptbook_evidence"] = evidence
    with pytest.raises(rr.SemanticFailure) as excinfo:
        rr.parse_and_check_reply(json.dumps(answer), book=v2_combined, token=TOKEN)
    assert excinfo.value.case == case


def test_one_judgment_citing_the_others_conclusion_is_rejected(answer, v2_combined):
    answer["power_analysis"]["reasoning"] = "Based on the data analysis, clustering ignored."
    with pytest.raises(rr.SemanticFailure) as excinfo:
        rr.parse_and_check_reply(json.dumps(answer), book=v2_combined, token=TOKEN)
    assert excinfo.value.case == "DC54"


def test_an_old_shaped_reply_fails_to_parse_under_v2(v2_combined):
    old = {"paper_id": TOKEN,
           "power_analysis": {"decision": "yes", "reasoning": "r",
                              "promptbook_evidence": "P7", "confidence": 0.5},
           "data_analysis": {"decision": "yes", "reasoning": "r",
                             "promptbook_evidence": "D5", "confidence": 0.5}}
    with pytest.raises(schemas.ParseFailure):
        rr.parse_and_check_reply(json.dumps(old), book=v2_combined, token=TOKEN)


def test_a_gate_reply_carries_its_reason(v2_gate):
    checked = rr.parse_and_check_reply(gate(), book=v2_gate, token=TOKEN)
    assert checked.answer.exclusion_reason == "E5"
    assert checked.decisions["exclusion"].decision == "yes"


def test_a_gate_reply_without_its_reason_fails_to_parse(v2_gate):
    payload = json.loads(gate())
    del payload["exclusion_reason"]
    with pytest.raises(schemas.ParseFailure):
        rr.parse_and_check_reply(json.dumps(payload), book=v2_gate, token=TOKEN)


def test_wrong_text_still_cites_wrong_text(v2_gate):
    reply = gate(decision="wrong_text", exclusion_reason=None,
                 promptbook_evidence="WRONG_TEXT")
    checked = rr.parse_and_check_reply(reply, book=v2_gate, token=TOKEN)
    assert checked.decisions["exclusion"].decision == "wrong_text"


def test_v1_gate_still_rejects_the_new_key():
    book = rr.resolve_route_book("exclusion", root=ROOT, version="v1")
    with pytest.raises(schemas.ParseFailure):
        rr.parse_and_check_reply(gate(), book=book, token=TOKEN)


# ------------------------------------------------------------------ storage


def _registered(tmp_path):
    conn = db.connect(tmp_path / "review.db")
    environment = {"task": rr.COMBINED_ANALYSIS_ROUTE, "round": 1, "model": rr.MODEL,
                   "effort": rr.EFFORT, "system_prompt_sha256": "a",
                   "promptbook_version": "v2", "promptbook_sha256": "b"}
    run_id = db.register_run_environment(conn, environment,
                                         route=rr.COMBINED_ANALYSIS_ROUTE)
    response_id = db.response_id_for_attempt(run_id=run_id, paper_id="P1", attempt=1)
    db.register_response(conn, response_id=response_id, run_id=run_id, paper_id="P1",
                         attempt=1, provider_response_id=None, raw_path="raw.jsonl",
                         status="accepted", metadata={})
    return conn, run_id, response_id


def _rows(full, *, run_id, response_id):
    judgments = [{"paper_id": "P1", "task": task, "pass_name": db.PASS_PRIMARY,
                  "model_used": rr.MODEL, "decision": d.decision,
                  "reasoning": d.reasoning, "promptbook_evidence": d.promptbook_evidence,
                  "confidence": d.confidence, "promptbook_version": "v2",
                  "run_id": run_id, "response_id": response_id}
                 for task, d in full.task_decisions().items()]
    stored = {"response_id": response_id, "run_id": run_id, "paper_id": "P1",
              "route": rr.COMBINED_ANALYSIS_ROUTE, "schema_name": "FullAnalysis",
              "promptbook_version": "v2", "answer": full.model_dump(exclude={"paper_id"})}
    return judgments, stored


def test_the_full_answer_is_stored_with_its_judgments(tmp_path, answer):
    conn, run_id, response_id = _registered(tmp_path)
    full, _ = schemas.parse_full_analysis(json.dumps(answer))
    judgments, stored = _rows(full, run_id=run_id, response_id=response_id)
    db.insert_judgments_atomically(conn, judgments, [stored])
    row = conn.execute("SELECT * FROM structured_answers").fetchone()
    assert json.loads(row["answer_json"])["design"]["n_trt"] == 2
    assert db.structured_answer_exists(conn, response_id)
    assert conn.execute("SELECT COUNT(*) FROM judgments").fetchone()[0] == 2
    conn.close()


def test_a_bad_judgment_rolls_back_the_answer_too(tmp_path, answer):
    conn, run_id, response_id = _registered(tmp_path)
    full, _ = schemas.parse_full_analysis(json.dumps(answer))
    judgments, stored = _rows(full, run_id=run_id, response_id=response_id)
    judgments[1]["task"] = "not_a_task"
    with pytest.raises(ValueError):
        db.insert_judgments_atomically(conn, judgments, [stored])
    assert conn.execute("SELECT COUNT(*) FROM structured_answers").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM judgments").fetchone()[0] == 0
    conn.close()


def test_an_answer_needs_a_registered_response(tmp_path, answer):
    conn, run_id, _ = _registered(tmp_path)
    full, _ = schemas.parse_full_analysis(json.dumps(answer))
    _, stored = _rows(full, run_id=run_id, response_id="response-unknown")
    with pytest.raises(db.ProvenanceError):
        db.insert_structured_answer(conn, **stored)
    conn.close()


def test_a_second_answer_for_one_response_is_refused(tmp_path, answer):
    conn, run_id, response_id = _registered(tmp_path)
    full, _ = schemas.parse_full_analysis(json.dumps(answer))
    _, stored = _rows(full, run_id=run_id, response_id=response_id)
    db.insert_structured_answer(conn, **stored)
    with pytest.raises(Exception, match="UNIQUE"):
        db.insert_structured_answer(conn, **stored)
    conn.close()


# ------------------------------------------------------- checker helpers


def test_the_checker_reports_and_logs_other_labels(answer):
    checker = load_checker()
    changed = copy.deepcopy(answer)
    changed["data_analysis"]["done"]["method"] = "other: hurdle model"
    full, _ = schemas.parse_full_analysis(json.dumps(changed))
    record = {"paper_id": "P1", "attempt": 1, "raw_path": "raw.jsonl", "_answer": full}
    checker.add_answer_fields(record, full)
    assert record["other_labels"] == "data_analysis.done.method=hurdle model"
    rows = checker.other_label_rows([record], route=rr.COMBINED_ANALYSIS_ROUTE,
                                    round_no=1, version="v2", skip=set())
    assert [(r["field"], r["label"]) for r in rows] == [
        ("data_analysis.done.method", "hurdle model")]
    assert checker.other_label_rows([record], route="x", round_no=1, version="v2",
                                    skip={("P1", 1)}) == []


def test_the_checker_reports_the_gate_reason():
    checker = load_checker()
    answer_, _ = schemas.parse_exclusion_with_reason(gate())
    record = {}
    checker.add_answer_fields(record, answer_)
    assert record == {"exclusion_reason": "E5", "other_labels": ""}


def test_a_legacy_reply_has_no_answer_row():
    checker = load_checker()
    assert checker.answer_row({"paper_id": "P1"}, response_id="r", run_id="u",
                              route="exclusion", version="v1") is None


# --------------------------------------------------------------- API schema


def test_the_api_asks_for_the_same_shape_as_the_room():
    gt = rr.CONTRACT_GROUND_TRUTH
    assert (api_contract.output_schema_for(rr.COMBINED_ANALYSIS_ROUTE, contract=gt)
            == schemas.full_analysis_output_schema())
    assert (api_contract.output_schema_for("exclusion", contract=gt)
            == schemas.exclusion_with_reason_output_schema())
    config = api_contract.output_config_for(rr.COMBINED_ANALYSIS_ROUTE, contract=gt)
    assert config["format"]["schema"] == schemas.full_analysis_output_schema()


def test_the_api_keeps_the_legacy_shape_by_default():
    assert (api_contract.output_schema_for("exclusion")
            == schemas.tool_schema("exclusion")["input_schema"])


@pytest.mark.parametrize("task", schemas.ANALYSIS_TASKS)
def test_the_api_has_no_single_task_analysis_under_ground_truth(task):
    with pytest.raises(ValueError, match="no single-task"):
        api_contract.output_schema_for(task, contract=rr.CONTRACT_GROUND_TRUTH)
