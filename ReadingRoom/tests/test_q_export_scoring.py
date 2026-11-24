"""Group Q: the 43-column export and per-column scoring (full col output plan step 5).

Offline. Built on small in-memory human sides plus the shared full-answer
fixture; one test reads the real data files (read-only) to pin the frozen
counts and the column order.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import db
import gt_export as g
import schemas

EXAMPLE = Path(__file__).parent / "fixtures" / "full_analysis_example.json"
HEADER = g.read_csv(g.GROUND_TRUTH)[0]


@pytest.fixture
def full_payload() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def full(payload: dict) -> schemas.FullAnalysis:
    return schemas.FullAnalysis.model_validate(payload)


def gate(decision="yes", reason="E5", evidence=None) -> schemas.ExclusionWithReason:
    return schemas.ExclusionWithReason.model_validate({
        "decision": decision, "exclusion_reason": reason if decision == "yes" else None,
        "reasoning": "r", "promptbook_evidence": evidence or (reason or "E1"),
        "confidence": 0.8})


def human_row(paper_id: str, **cells) -> dict:
    row = {column: "" for column in HEADER}
    row.update(paper_id=paper_id, source_institute="NHLBI", source_file="f.tex",
               source_row="1", citation_raw=f"{paper_id} et al.", labeled="1")
    row.update(cells)
    return row


def human_side(*rows: dict, dropped: tuple[dict, ...] = ()) -> g.HumanSide:
    by_paper: dict[str, list[dict]] = {}
    for row in rows:
        by_paper.setdefault(row["paper_id"], []).append(row)
    return g.HumanSide(HEADER, list(dict.fromkeys(r["paper_id"] for r in rows)),
                       list(dropped), by_paper)


def answers(gates=None, fulls=None) -> g.ModelAnswers:
    result = g.ModelAnswers(gate=dict(gates or {}), full=dict(fulls or {}))
    for pid in result.gate:
        result.source[(pid, g.EXCLUSION_ROUTE)] = f"resp-gate-{pid}"
    for pid in result.full:
        result.source[(pid, g.COMBINED_ROUTE)] = f"resp-full-{pid}"
    return result


# ------------------------------------------------------------------ export


def test_export_has_the_ground_truth_columns_in_order(full_payload):
    export = g.export_rows(human_side(human_row("P1")),
                           answers({"P1": gate("no")}, {"P1": full(full_payload)}))
    assert list(export.rows[0]) == HEADER
    assert len(HEADER) == 43


def test_design_cells_render_like_the_human_file(full_payload):
    row = g.export_rows(human_side(human_row("P1")),
                        answers({"P1": gate("no")}, {"P1": full(full_payload)})).rows[0]
    assert row["comment_levels"] == "patient within physician within clinic within matched_pair"
    assert row["n_levels"] == "3"
    # Outermost first, the person level last.
    assert [row[c] for c in g.COUNT_COLUMNS] == ["8", "16", "64", "~20/physician"]
    assert row["restricted_rand_raw"] == "yes, pair_matched by clinic size and region"
    assert row["restricted_rand"] == "yes"
    assert row["icc"] == "clinic 0.05; physician 0.01-0.03"
    assert row["n_long"] == "3"                    # baseline + 2 follow-ups
    assert row["stepped_wedge"] == "no"
    assert row["data_should"] == ("Account for clustering at physician, clinic, "
                                  "restricted rand., longitudinality")
    assert row["power_done"].startswith("Formula accounting for clustering at clinic only")
    assert row["data_done"].startswith("Mixed model accounting for clustering at physician")
    assert (row["power_correct"], row["data_correct"]) == ("no", "yes")
    assert (row["excluded"], row["labeled"]) == ("0", "1")


def test_unanswered_paper_keeps_its_row_with_model_columns_blank():
    source = human_row("P1", excluded="0", power_correct="yes", n_trt="2",
                       source_doi="10.1/x")
    row = g.export_rows(human_side(source), answers()).rows[0]
    assert row["labeled"] == "0" and row["source_doi"] == "10.1/x"
    assert row["paper_id"] == "P1"
    model_columns = set(HEADER) - set(g.PROVENANCE) - {"labeled"}
    assert all(row[c] == "" for c in model_columns)


def test_exclusion_reason_is_the_readable_name_and_raw_keeps_the_number():
    row = g.export_rows(human_side(human_row("P1")), answers({"P1": gate()})).rows[0]
    assert (row["excluded"], row["exclusion_reason"], row["exclusion_reason_raw"]) == \
        ("1", "secondary_analysis", "E5")
    assert row["power_correct"] == "" and row["n_trt"] == ""   # never asked


def test_other_exclusion_reason_exports_its_label():
    answer = gate(reason="other: animal study", evidence="E19")
    row = g.export_rows(human_side(human_row("P1")), answers({"P1": answer})).rows[0]
    assert row["exclusion_reason"] == "other: animal study"


def test_undecidable_gate_exports_a_blank_excluded():
    row = g.export_rows(human_side(human_row("P1")),
                        answers({"P1": gate("undecidable")})).rows[0]
    assert row["excluded"] == "" and row["labeled"] == "1"


def test_disagreeing_human_rows_are_skipped_not_exported():
    side = human_side(human_row("P1", excluded="0", source_institute="NCI"),
                      human_row("P1", excluded="1"), human_row("P2"))
    export = g.export_rows(side, answers())
    assert [r["paper_id"] for r in export.rows] == ["P2"]
    assert export.skipped == [{"paper_id": "P1", "reason": "human rows disagree on excluded"}]


def test_agreeing_duplicate_rows_export_once_from_the_detailed_row():
    side = human_side(human_row("P1", excluded="0", source_institute="NCI"),
                      human_row("P1", excluded="0", comment_levels="patient within clinic",
                                source_row="9"))
    export = g.export_rows(side, answers())
    assert len(export.rows) == 1 and export.rows[0]["source_row"] == "9"


def test_answered_papers_outside_the_active_set_are_reported(full_payload):
    export = g.export_rows(human_side(human_row("P1")), answers({"ZZ": gate()}))
    assert export.orphans == ["ZZ"]


def test_comparison_carries_both_n_long_conventions(full_payload):
    export = g.export_rows(human_side(human_row("P1")),
                           answers({"P1": gate("no")}, {"P1": full(full_payload)}))
    row = export.comparison[0]
    assert (row["n_long"], row["n_long_followup_only"]) == ("3", "2")
    assert row["data_should_agrees"] == 1          # fixture's own should = derived
    assert export.answer_index[0]["gate_decision"] == "no"


def test_unknown_schedule_exports_nr_and_no_longitudinality(full_payload):
    full_payload["design"]["longitudinal"] = {"baseline_measured": "not_reported",
                                              "n_followup": 2}
    row = g.export_rows(human_side(human_row("P1")),
                        answers(fulls={"P1": full(full_payload)})).rows[0]
    assert row["n_long"] == "NR"
    assert "longitudinality" not in row["data_should"]


def test_real_files_match_the_frozen_counts_and_header():
    human = g.load_human()
    assert len(human.active) == g.EXPECTED_ACTIVE_HLS
    assert len(human.dropped) == g.EXPECTED_DROPPED_HLS
    export = g.export_rows(human, answers())
    assert len(export.rows) + len(export.skipped) == g.EXPECTED_ACTIVE_HLS
    assert all(list(r) == human.header for r in export.rows)


def test_a_changed_manifest_count_stops_the_export():
    with pytest.raises(g.ExportError, match="active HLS"):
        g.load_human(expected_active=g.EXPECTED_ACTIVE_HLS + 1)


def test_load_answers_takes_the_latest_answer_per_route(tmp_path, full_payload):
    conn = db.connect(tmp_path / "t.db")
    conn.execute("PRAGMA foreign_keys = OFF")
    first = gate("no").model_dump(exclude={"paper_id"})
    second = gate().model_dump(exclude={"paper_id"})
    body = full(full_payload).model_dump(exclude={"paper_id"})
    rows = [("r1", "P1", "exclusion", first, "2026-01-01"),
            ("r2", "P1", "exclusion", second, "2026-01-02"),
            ("r3", "P1", "combined_analysis", body, "2026-01-01"),
            ("r4", "P2", "exclusion", second, "2026-01-01")]
    for rid, pid, route, payload, stamp in rows:
        conn.execute("INSERT INTO structured_answers VALUES (?,?,?,?,?,?,?,?,?)",
                     (rid, "run", pid, route, "X", "v2" if rid != "r4" else "v3",
                      json.dumps(payload), "h", stamp))
    loaded = g.load_answers(conn, promptbook_version="v2")
    assert loaded.gate["P1"].decision == "yes"
    assert loaded.source[("P1", "exclusion")] == "r2"
    assert "P1" in loaded.full and "P2" not in loaded.gate


# ----------------------------------------------------------------- scoring


def scored(human: dict, model_row: dict, column: str, synonyms=None,
           gate_decision="no", has_full=True):
    return g.score_cell(column, human, model_row, synonyms or {},
                        gate_decision=gate_decision, has_full=has_full)


def model_row(**cells) -> dict:
    row = {column: "" for column in HEADER}
    row.update(labeled="1", power_correct_raw="no")
    row.update(cells)
    return row


def test_blank_human_cell_is_not_scored():
    assert scored(human_row("P1"), model_row(n_trt="2"), "n_trt") is None


def test_never_asked_is_not_scored():
    human = human_row("P1", n_trt="2")
    assert scored(human, model_row(n_trt="2"), "n_trt", has_full=False) is None
    assert scored(human_row("P1", excluded="0"), model_row(excluded="0"), "excluded",
                  gate_decision="") is None


def test_gate_abstention_is_counted_apart_from_misses():
    cell = scored(human_row("P1", excluded="1"), model_row(excluded=""), "excluded",
                  gate_decision="undecidable")
    assert cell["outcome"] == g.ABSTAIN


@pytest.mark.parametrize("human_reason, model_reason, outcome", [
    ("secondary_analysis", "secondary_in_title", g.MATCH),     # E4 counts as E5
    ("secondary_analysis", "secondary_analysis", g.MATCH),
    ("pilot_study", "secondary_analysis", g.MISMATCH),
    ("protocol_paper", "secondary_analysis", g.NOT_SCORED),    # retired E12
    ("secondary_analysis", "other: animal study", g.MISMATCH),
])
def test_exclusion_reason_rules(human_reason, model_reason, outcome):
    human = human_row("P1", excluded="1", exclusion_reason=human_reason)
    cell = scored(human, model_row(excluded="1", exclusion_reason=model_reason),
                  "exclusion_reason", gate_decision="yes")
    assert cell["outcome"] == outcome


def test_n_levels_scores_against_units_minus_one_not_the_human_number():
    human = human_row("P1", n_levels="2", comment_levels="patient within clinic")
    cell = scored(human, model_row(n_levels="1"), "n_levels")
    assert cell["outcome"] == g.MATCH and cell["human"] == "1"


def test_unit_terms_need_a_checked_synonym():
    human = human_row("P1", unit_rand="PCP")
    model = model_row(unit_rand="physician")
    assert scored(human, model, "unit_rand")["outcome"] == g.NOT_SCORED
    assert scored(human, model, "unit_rand", {"pcp": "physician"})["outcome"] == g.MATCH


def test_an_other_label_matches_the_same_human_wording():
    human = human_row("P1", comment_levels="participant within church")
    model = model_row(comment_levels="participant within church")
    assert scored(human, model, "comment_levels")["outcome"] == g.MATCH


@pytest.mark.parametrize("human, model, outcome", [
    ("12", "12", g.MATCH), ("12", "~12", g.MISMATCH), ("NR", "NR", g.MATCH),
    ("NR", "12", g.MISMATCH), ("20 per school", "20/school", g.MATCH),
    ("5--8", "5-8", g.MATCH), ("325 + 288", "613", g.NOT_SCORED),
])
def test_cluster_counts_match_exactly(human, model, outcome):
    cell = scored(human_row("P1", n_outer=human), model_row(n_outer=model), "n_outer")
    assert cell["outcome"] == outcome


@pytest.mark.parametrize("human, model, outcome", [
    ("0.05", "0.05", g.MATCH), ("0.01-0.05", "0.01-0.05", g.MATCH),
    ("0.1 (pt within clin), 0.05 (clin within ICU)", "clinic 0.05; patient 0.1", g.MATCH),
    ("not mentioned", "NR", g.MATCH), ("0.05", "0.5", g.MISMATCH),
    ("<0.05", "0.04", g.NOT_SCORED),
])
def test_icc_is_a_numeric_set_match(human, model, outcome):
    cell = scored(human_row("P1", icc=human), model_row(icc=model), "icc")
    assert cell["outcome"] == outcome


@pytest.mark.parametrize("human, model, outcome", [
    ("Account for clustering alone", "Account for clustering at clinic, restricted rand.",
     g.MATCH),                                                  # a correct extra
    ("Account for restricted rand. and clustering", "Account for clustering at clinic",
     g.MISMATCH),
    ("Account for clustering and longitudinality",
     "Account for clustering at clinic, longitudinality", g.MATCH),
    ("Same", "Account for clustering at clinic", g.NOT_SCORED),
])
def test_should_needs_every_human_factor(human, model, outcome):
    cell = scored(human_row("P1", data_should=human), model_row(data_should=model),
                  "data_should")
    assert cell["outcome"] == outcome


def test_score_summarises_and_reports_the_follow_up_only_convention():
    human = human_side(human_row("P1", excluded="0", n_long="2", n_trt="2"))
    export = [model_row(paper_id="P1", excluded="0", n_long="2", n_trt="3")]
    index = [{"paper_id": "P1", "gate_decision": "no", "full_response_id": "r"}]
    comparison = [{"paper_id": "P1", "n_long_followup_only": "1"}]
    summary, cells = g.score(export, human, index, comparison, synonyms={})
    by_column = {r["column"]: r for r in summary}
    assert by_column["n_long"]["agreement"] == "1.000"
    assert by_column["n_long (follow-up only)"]["mismatch"] == 1
    assert by_column["n_trt"]["mismatch"] == 1
    assert by_column["excluded"]["match"] == 1
    assert "person-coded" in by_column["power_done"]["note"]


def test_scoring_can_be_limited_to_a_split():
    human = human_side(human_row("P1", n_trt="2"), human_row("P2", n_trt="2"))
    export = [model_row(paper_id="P1", n_trt="2"), model_row(paper_id="P2", n_trt="2")]
    index = [{"paper_id": p, "gate_decision": "no", "full_response_id": "r"}
             for p in ("P1", "P2")]
    _, cells = g.score(export, human, index, papers={"P1"}, synonyms={})
    assert {c["paper_id"] for c in cells} == {"P1"}


def test_only_checked_synonyms_load(tmp_path):
    path = tmp_path / "syn.csv"
    path.write_text("human_term,unit,checked\nPCP,physician,yes\nteam,clinic,no\n",
                    encoding="utf-8")
    assert g.load_synonyms(path) == {"pcp": "physician"}
