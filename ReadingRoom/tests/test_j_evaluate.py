"""Read-only classification metrics, including Cohen's kappa (evaluation)."""

from __future__ import annotations

import csv

import pytest

import db
import evaluate


def insert_label(conn, paper_id, *, split=db.SPLIT_BUILD, excluded=False,
                 power="yes", stats="yes"):
    conn.execute(
        """INSERT INTO validation_labels
           (paper_id, source_file, citation_raw, exclusion_reason, power, stats,
            review_category, split, matched_by, match_score, loaded_at)
           VALUES (?, 'test', ?, ?, ?, ?, NULL, ?, 'test', 1.0, 'now')""",
        (paper_id, paper_id, "not RCT" if excluded else None, power, stats, split))
    conn.commit()


def insert_judgment(conn, paper_id, task, decision, *, index=None,
                    version="v1", confidence=0.8, model="claude-sonnet-5"):
    return db.insert_judgment(
        conn, paper_id=paper_id, task=task, pass_name=db.PASS_PRIMARY,
        model_used=model, decision=decision, reasoning="test reasoning",
        promptbook_evidence="E1", confidence=confidence,
        promptbook_version=version, judgment_index=index)


def test_binary_metrics_include_sensitivity_specificity_and_kappa(tmp_path):
    conn = db.connect(tmp_path / "review.db")
    try:
        for paper_id, excluded in (("TP", True), ("FN", True), ("FP", False),
                                   ("TN", False), ("U", False), ("W", True)):
            insert_label(conn, paper_id, excluded=excluded)
        for paper_id, decision in (("TP", "yes"), ("FN", "no"), ("FP", "yes"),
                                   ("TN", "no"), ("U", "undecidable"),
                                   ("W", "wrong_text")):
            insert_judgment(conn, paper_id, "exclusion", decision)

        result = evaluate.evaluate_task(conn, "exclusion", promptbook_version="v1")
    finally:
        conn.close()

    row = result.summary_row()
    assert row["eligible"] == 6
    assert row["scored"] == 4
    assert row["true_positive"] == row["true_negative"] == 1
    assert row["false_positive"] == row["false_negative"] == 1
    assert row["undecidable"] == row["wrong_text"] == 1
    assert row["accuracy"] == pytest.approx(0.5)
    assert row["sensitivity"] == pytest.approx(0.5)
    assert row["specificity"] == pytest.approx(0.5)
    assert row["precision"] == pytest.approx(0.5)
    assert row["f1"] == pytest.approx(0.5)
    assert row["cohen_kappa"] == pytest.approx(0.0)


def test_missing_judgments_are_coverage_not_silent_denominator_shrinkage(tmp_path):
    conn = db.connect(tmp_path / "review.db")
    try:
        insert_label(conn, "P1", excluded=True)
        insert_label(conn, "P2", excluded=False)
        insert_judgment(conn, "P1", "exclusion", "yes")
        result = evaluate.evaluate_task(conn, "exclusion", promptbook_version="v1")
    finally:
        conn.close()

    row = result.summary_row()
    assert row["eligible"] == 2
    assert row["judged_eligible"] == 1
    assert row["coverage"] == pytest.approx(0.5)
    assert row["scored"] == 1
    assert row["scoreable_coverage"] == pytest.approx(0.5)
    assert any(case["paper_id"] == "P2" and case["status"] == "missing"
               for case in result.cases)


def test_analysis_evaluation_only_counts_human_gate_survivors(tmp_path):
    conn = db.connect(tmp_path / "review.db")
    try:
        insert_label(conn, "SURVIVOR", excluded=False, power="yes")
        insert_label(conn, "EXCLUDED", excluded=True, power=None)
        insert_judgment(conn, "SURVIVOR", "power_analysis", "yes")
        insert_judgment(conn, "EXCLUDED", "power_analysis", "no")
        result = evaluate.evaluate_task(conn, "power_analysis", promptbook_version="v1")
    finally:
        conn.close()

    row = result.summary_row()
    assert row["eligible"] == 1
    assert row["scored"] == 1
    assert row["unlabeled_judgments"] == 1
    assert any(case["paper_id"] == "EXCLUDED" and case["status"] == "unlabeled"
               for case in result.cases)


def test_latest_judgment_for_the_requested_version_is_scored(tmp_path):
    conn = db.connect(tmp_path / "review.db")
    try:
        insert_label(conn, "P1", excluded=True)
        insert_judgment(conn, "P1", "exclusion", "no", index=1, version="v1")
        insert_judgment(conn, "P1", "exclusion", "yes", index=2, version="v1")
        insert_judgment(conn, "P1", "exclusion", "no", index=3, version="v2")
        result_v1 = evaluate.evaluate_task(conn, "exclusion", promptbook_version="v1")
        result_any = evaluate.evaluate_task(conn, "exclusion")
    finally:
        conn.close()

    assert result_v1.summary_row()["accuracy"] == 1.0
    assert result_any.summary_row()["accuracy"] == 0.0


def test_kappa_is_null_when_expected_agreement_is_one(tmp_path):
    conn = db.connect(tmp_path / "review.db")
    try:
        insert_label(conn, "P1", excluded=True)
        insert_judgment(conn, "P1", "exclusion", "yes")
        result = evaluate.evaluate_task(conn, "exclusion", promptbook_version="v1")
    finally:
        conn.close()

    assert result.summary_row()["cohen_kappa"] is None


def test_writer_creates_csv_json_and_markdown_dashboard(tmp_path):
    conn = db.connect(tmp_path / "review.db")
    try:
        insert_label(conn, "P1", excluded=True)
        insert_judgment(conn, "P1", "exclusion", "yes")
        results = evaluate.evaluate_tasks(conn, ("exclusion",), promptbook_version="v1")
    finally:
        conn.close()

    paths = evaluate.write_evaluation(tmp_path / "report", results,
                                      generated_at="2026-08-28T00:00:00+00:00")
    assert all(path.is_file() for path in paths.values())
    rows = list(csv.DictReader(paths["summary_csv"].open(encoding="utf-8")))
    assert rows[0]["cohen_kappa"] == ""
    assert "Cohen's κ" in paths["report"].read_text(encoding="utf-8")
