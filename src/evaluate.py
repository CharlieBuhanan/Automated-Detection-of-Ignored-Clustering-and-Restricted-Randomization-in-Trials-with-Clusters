"""Read-only evaluation of persisted classification judgments.

This module scores the latest judgment for each paper/task against the human
label. It deliberately does not import an API client, submit work, update the
database, or modify a retry ledger. Evaluation must be safe to repeat: the
results are an analysis of immutable labels and append-only judgments, never a
new experimental condition.

``yes`` is the positive class for every task. For exclusion that means
``exclude``; for power and data it means ``correct``. ``undecidable`` and
``wrong_text`` remain visible but are excluded from the binary-score denominator
instead of being silently converted into mistakes.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

import db


SUMMARY_COLUMNS = [
    "task", "split", "promptbook_version", "eligible", "persisted_judgments",
    "judged_eligible", "missing", "coverage", "scored", "scoreable_coverage",
    "true_positive", "true_negative", "false_positive", "false_negative",
    "accuracy", "sensitivity", "specificity", "precision", "negative_predictive_value",
    "f1", "balanced_accuracy", "cohen_kappa", "undecidable", "wrong_text",
    "unlabeled_judgments", "confidence_n", "confidence_min", "confidence_max",
    "confidence_mean", "distinct_confidences", "models", "pass_names",
]

CASE_COLUMNS = [
    "task", "split", "paper_id", "promptbook_version", "judgment_index",
    "pass_name", "model_used", "truth", "decision", "confidence", "status",
    "outcome", "reasoning", "promptbook_evidence",
]


def _ratio(numerator: int, denominator: int) -> float | None:
    """Return a rate or ``None`` when its denominator does not exist."""
    return numerator / denominator if denominator else None


def _rounded(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _format_metric(value: Any, *, percent: bool = False) -> str:
    if value is None:
        return "—"
    if percent:
        return f"{float(value):.1%}"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


@dataclass(frozen=True)
class TaskEvaluation:
    """One task's complete evaluation and its paper-level audit trail."""

    task: str
    split: str
    promptbook_version: str | None
    metrics: dict[str, Any]
    cases: list[dict[str, Any]]

    def summary_row(self) -> dict[str, Any]:
        """Flat, CSV-ready summary with stable column names."""
        version = self.promptbook_version or "latest_any_version"
        return {"task": self.task, "split": self.split,
                "promptbook_version": version, **self.metrics}


def _classification_outcome(*, truth: str, decision: str) -> str:
    if truth == "yes" and decision == "yes":
        return "true_positive"
    if truth == "no" and decision == "no":
        return "true_negative"
    if truth == "no" and decision == "yes":
        return "false_positive"
    if truth == "yes" and decision == "no":
        return "false_negative"
    raise ValueError(f"expected binary truth/prediction, got {truth!r}/{decision!r}")


def evaluate_task(conn, task: str, *, split: str = db.SPLIT_BUILD,
                  promptbook_version: str | None = None) -> TaskEvaluation:
    """Evaluate the latest persisted judgments for one task and split.

    The pairing is label-first so a missing model judgment becomes an explicit
    case and reduces coverage, rather than quietly shrinking the denominator.
    Persisted judgments that cannot be paired to an eligible label are also
    reported: a split mismatch or an analysis judgment on a human-excluded
    paper is evidence worth investigating, not a row to drop invisibly.
    """
    if task not in db.TASKS:
        raise ValueError(f"unknown task {task!r}; expected one of {db.TASKS}")
    if split not in (db.SPLIT_BUILD, db.SPLIT_HOLDOUT):
        raise ValueError(
            f"unknown split {split!r}; expected {db.SPLIT_BUILD!r} or "
            f"{db.SPLIT_HOLDOUT!r}")

    labels = {
        row["paper_id"]: row
        for row in conn.execute("SELECT * FROM validation_labels WHERE split = ?", (split,))
    }
    eligible = {
        paper_id: db.expected_decision(label, task)
        for paper_id, label in labels.items()
    }
    eligible = {paper_id: truth for paper_id, truth in eligible.items() if truth in ("yes", "no")}

    judgments = list(db.latest_judgments(conn, task, promptbook_version))
    by_paper = {row["paper_id"]: row for row in judgments}
    cases: list[dict[str, Any]] = []

    counts = {
        "true_positive": 0,
        "true_negative": 0,
        "false_positive": 0,
        "false_negative": 0,
        "undecidable": 0,
        "wrong_text": 0,
        "missing": 0,
        "unlabeled_judgments": 0,
    }
    confidences: list[float] = []
    models: set[str] = set()
    pass_names: set[str] = set()

    for paper_id in sorted(eligible):
        truth = eligible[paper_id]
        judgment = by_paper.pop(paper_id, None)
        if judgment is None:
            counts["missing"] += 1
            cases.append({
                "task": task, "split": split, "paper_id": paper_id,
                "promptbook_version": promptbook_version or "latest_any_version",
                "judgment_index": "", "pass_name": "", "model_used": "",
                "truth": truth, "decision": "", "confidence": "",
                "status": "missing", "outcome": "missing", "reasoning": "",
                "promptbook_evidence": "",
            })
            continue

        decision = judgment["decision"]
        confidence = judgment["confidence"]
        models.add(judgment["model_used"])
        pass_names.add(judgment["pass_name"])
        if confidence is not None:
            confidences.append(float(confidence))

        if decision == "undecidable":
            counts["undecidable"] += 1
            status, outcome = "abstained", "undecidable"
        elif decision == "wrong_text":
            counts["wrong_text"] += 1
            status, outcome = "not_scored", "wrong_text"
        elif decision in ("yes", "no"):
            outcome = _classification_outcome(truth=truth, decision=decision)
            counts[outcome] += 1
            status = "scored"
        else:
            # The database is permissive enough to contain historical bad data.
            # Do not classify an unknown decision as a miss or make up a metric.
            counts["unlabeled_judgments"] += 1
            status, outcome = "invalid", "unknown_decision"

        cases.append({
            "task": task, "split": split, "paper_id": paper_id,
            "promptbook_version": judgment["promptbook_version"],
            "judgment_index": judgment["judgment_index"],
            "pass_name": judgment["pass_name"], "model_used": judgment["model_used"],
            "truth": truth, "decision": decision, "confidence": confidence,
            "status": status, "outcome": outcome,
            "reasoning": judgment["reasoning"],
            "promptbook_evidence": judgment["promptbook_evidence"],
        })

    # Latest judgments outside the requested eligible set are not scoreable.
    # Keep them in cases.csv to expose, for example, a holdout or non-survivor
    # analysis judgment that would otherwise make coverage look deceptively good.
    for paper_id, judgment in sorted(by_paper.items()):
        counts["unlabeled_judgments"] += 1
        models.add(judgment["model_used"])
        pass_names.add(judgment["pass_name"])
        cases.append({
            "task": task, "split": split, "paper_id": paper_id,
            "promptbook_version": judgment["promptbook_version"],
            "judgment_index": judgment["judgment_index"],
            "pass_name": judgment["pass_name"], "model_used": judgment["model_used"],
            "truth": "", "decision": judgment["decision"],
            "confidence": judgment["confidence"], "status": "unlabeled",
            "outcome": "unlabeled_judgment", "reasoning": judgment["reasoning"],
            "promptbook_evidence": judgment["promptbook_evidence"],
        })

    tp, tn = counts["true_positive"], counts["true_negative"]
    fp, fn = counts["false_positive"], counts["false_negative"]
    scored = tp + tn + fp + fn
    judged_eligible = len(eligible) - counts["missing"]
    accuracy = _ratio(tp + tn, scored)
    sensitivity = _ratio(tp, tp + fn)
    specificity = _ratio(tn, tn + fp)
    precision = _ratio(tp, tp + fp)
    negative_predictive_value = _ratio(tn, tn + fn)
    f1 = _ratio(2 * tp, 2 * tp + fp + fn)
    balanced_accuracy = (
        (sensitivity + specificity) / 2
        if sensitivity is not None and specificity is not None else None
    )

    # Cohen's kappa corrects observed agreement for the agreement implied by
    # the two binary marginal distributions. Undefined is better than a made-up
    # 0 when both sides have a single class and expected agreement is 1.
    if scored:
        observed = accuracy
        predicted_yes = _ratio(tp + fp, scored)
        predicted_no = _ratio(tn + fn, scored)
        truth_yes = _ratio(tp + fn, scored)
        truth_no = _ratio(tn + fp, scored)
        expected = predicted_yes * truth_yes + predicted_no * truth_no
        cohen_kappa = None if expected == 1 else (observed - expected) / (1 - expected)
    else:
        cohen_kappa = None

    metrics = {
        "eligible": len(eligible),
        "persisted_judgments": len(judgments),
        "judged_eligible": judged_eligible,
        "missing": counts["missing"],
        "coverage": _rounded(_ratio(judged_eligible, len(eligible))),
        "scored": scored,
        "scoreable_coverage": _rounded(_ratio(scored, len(eligible))),
        "true_positive": tp,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
        "accuracy": _rounded(accuracy),
        "sensitivity": _rounded(sensitivity),
        "specificity": _rounded(specificity),
        "precision": _rounded(precision),
        "negative_predictive_value": _rounded(negative_predictive_value),
        "f1": _rounded(f1),
        "balanced_accuracy": _rounded(balanced_accuracy),
        "cohen_kappa": _rounded(cohen_kappa),
        "undecidable": counts["undecidable"],
        "wrong_text": counts["wrong_text"],
        "unlabeled_judgments": counts["unlabeled_judgments"],
        "confidence_n": len(confidences),
        "confidence_min": _rounded(min(confidences)) if confidences else None,
        "confidence_max": _rounded(max(confidences)) if confidences else None,
        "confidence_mean": _rounded(mean(confidences)) if confidences else None,
        "distinct_confidences": len(set(confidences)),
        "models": ";".join(sorted(models)),
        "pass_names": ";".join(sorted(pass_names)),
    }
    return TaskEvaluation(task=task, split=split,
                          promptbook_version=promptbook_version,
                          metrics=metrics, cases=cases)


def evaluate_tasks(conn, tasks: Iterable[str] = db.TASKS, *,
                   split: str = db.SPLIT_BUILD,
                   promptbook_version: str | None = None) -> list[TaskEvaluation]:
    """Evaluate several tasks in their supplied, stable order."""
    return [evaluate_task(conn, task, split=split,
                          promptbook_version=promptbook_version)
            for task in tasks]


def write_evaluation(output_dir: Path, results: Iterable[TaskEvaluation], *,
                     generated_at: str | None = None) -> dict[str, Path]:
    """Write CSV, JSON, and Markdown reporting artifacts; never write SQLite."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = list(results)
    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    summaries = [result.summary_row() for result in results]
    cases = [case for result in results for case in result.cases]

    summary_csv = output_dir / "summary.csv"
    with summary_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summaries)

    cases_csv = output_dir / "cases.csv"
    with cases_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CASE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(cases)

    summary_json = output_dir / "summary.json"
    summary_json.write_text(json.dumps({
        "generated_at": generated_at,
        "results": summaries,
    }, indent=2) + "\n", encoding="utf-8")

    report = output_dir / "report.md"
    lines = [
        "# Classification evaluation",
        "",
        f"Generated: `{generated_at}`",
        "",
        "`yes` is the positive class. Sensitivity = recall for `yes`; "
        "specificity = recall for `no`. Cohen's kappa is chance-corrected "
        "agreement and is shown as `—` when mathematically undefined.",
        "",
        "| Task | Eligible | Coverage | Scored | Accuracy | Sensitivity | Specificity | Precision | F1 | Cohen's κ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            "| {task} | {eligible} | {coverage} | {scored} | {accuracy} | "
            "{sensitivity} | {specificity} | {precision} | {f1} | {kappa} |".format(
                task=row["task"], eligible=row["eligible"],
                coverage=_format_metric(row["coverage"], percent=True),
                scored=row["scored"], accuracy=_format_metric(row["accuracy"], percent=True),
                sensitivity=_format_metric(row["sensitivity"], percent=True),
                specificity=_format_metric(row["specificity"], percent=True),
                precision=_format_metric(row["precision"], percent=True),
                f1=_format_metric(row["f1"]),
                kappa=_format_metric(row["cohen_kappa"]),
            ))
    lines += [
        "",
        "## Confusion matrices",
        "",
        "| Task | TP | TN | FP | FN | Undecidable | Wrong text | Missing | Unlabelled judgments |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            "| {task} | {true_positive} | {true_negative} | {false_positive} | "
            "{false_negative} | {undecidable} | {wrong_text} | {missing} | "
            "{unlabeled_judgments} |".format(**row))
    lines += [
        "",
        "## Persisted provenance",
        "",
        "| Task | Model(s) | Pass(es) |",
        "|---|---|---|",
    ]
    for row in summaries:
        lines.append(
            f"| {row['task']} | {row['models'] or '—'} | {row['pass_names'] or '—'} |")
    lines += [
        "",
        "The current `judgments` table does not store effort or runner route. "
        "Do not infer high/medium comparability from this report alone; verify "
        "historical effort from each run's `run_environment.json` until request-level "
        "provenance migration is implemented.",
        "",
        "## Files",
        "",
        "- `summary.csv`: one row per task for Excel/R/plotting.",
        "- `cases.csv`: paper-level truth, prediction, confidence, and error class.",
        "- `summary.json`: machine-readable aggregate metrics.",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {"summary_csv": summary_csv, "cases_csv": cases_csv,
            "summary_json": summary_json, "report": report}
