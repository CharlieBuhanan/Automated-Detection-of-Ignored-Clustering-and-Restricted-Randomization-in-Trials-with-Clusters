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
import math
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
    "f1", "balanced_accuracy", "cohen_kappa",
    "accuracy_ci95_low", "accuracy_ci95_high",
    "sensitivity_ci95_low", "sensitivity_ci95_high",
    "specificity_ci95_low", "specificity_ci95_high",
    "cohen_kappa_ci95_method", "undecidable", "wrong_text",
    "unlabeled_judgments", "confidence_n", "confidence_min", "confidence_max",
    "confidence_mean", "distinct_confidences", "calibration_n",
    "calibration_empirical_accuracy", "calibration_gap", "decision_confidence_brier",
    "expected_calibration_error", "models", "pass_names",
    "configuration_status", "configuration_fingerprints", "run_ids",
    "configuration_sources", "efforts", "routes", "transports",
]

CASE_COLUMNS = [
    "task", "split", "paper_id", "promptbook_version", "judgment_index",
    "pass_name", "model_used", "truth", "decision", "confidence", "status",
    "outcome", "reasoning", "promptbook_evidence", "run_id", "response_id",
    "configuration_fingerprint", "configuration_source", "effort", "route",
    "transport",
]

CALIBRATION_COLUMNS = [
    "task", "split", "promptbook_version", "configuration_status",
    "bin_lower", "bin_upper", "n", "mean_confidence", "empirical_accuracy",
    "calibration_gap",
]

THRESHOLD_COLUMNS = [
    "task", "split", "promptbook_version", "configuration_status", "threshold",
    "confidence_n", "low_confidence_n", "low_confidence_rate",
    "retained_n", "retained_accuracy", "retained_sensitivity",
    "retained_specificity",
]

HISTORY_COLUMNS = [
    "generated_at", "task", "split", "promptbook_version", "eligible",
    "scored", "accuracy", "sensitivity", "specificity", "cohen_kappa",
    "configuration_status", "configuration_fingerprint", "run_ids",
    "configuration_sources", "comparable_to_previous", "comparison_note",
]

CONFIDENCE_THRESHOLDS = tuple(round(value / 100, 2) for value in range(50, 100, 5))
CALIBRATION_BIN_WIDTH = 0.10


class ConfigurationRefusal(RuntimeError):
    """A report is not a clean configuration for a DC17 history comparison."""


def _ratio(numerator: int, denominator: int) -> float | None:
    """Return a rate or ``None`` when its denominator does not exist."""
    return numerator / denominator if denominator else None


def _rounded(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _wilson_interval(successes: int, total: int, *, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    """Two-sided 95% Wilson binomial interval, or ``(None, None)`` at n=0.

    Wilson is stable for the small, imbalanced calibration batches here; the
    normal/Wald interval can report impossible negative rates or false 100%
    certainty with the same data.
    """
    if not total:
        return None, None
    p = successes / total
    z_squared = z * z
    denominator = 1 + z_squared / total
    centre = (p + z_squared / (2 * total)) / denominator
    half_width = (z / denominator) * math.sqrt(
        p * (1 - p) / total + z_squared / (4 * total * total))
    return max(0.0, centre - half_width), min(1.0, centre + half_width)


def _configuration_summary(judgments: list[Any]) -> dict[str, Any]:
    """Describe whether the selected latest judgments are one known experiment.

    Evaluation itself stays useful for historical/legacy rows, but an unknown
    or mixed configuration cannot become a DC17 plateau/history observation.
    This is intentionally based on every selected persisted judgment, not only
    correct ones or only the scoreable subset.
    """
    if not judgments:
        return {
            "configuration_status": "no_judgments",
            "configuration_fingerprints": "",
            "run_ids": "",
            "configuration_sources": "",
            "efforts": "",
            "routes": "",
            "transports": "",
        }

    run_ids = sorted({str(row["run_id"]) for row in judgments if row["run_id"]})
    fingerprints = sorted({str(row["provenance_config_fingerprint"])
                           for row in judgments if row["provenance_config_fingerprint"]})
    sources = sorted({str(row["provenance_source_path"])
                      for row in judgments if row["provenance_source_path"]})
    efforts = sorted({str(row["provenance_effort"])
                      for row in judgments if row["provenance_effort"]})
    routes = sorted({str(row["provenance_route"])
                     for row in judgments if row["provenance_route"]})
    transports = sorted({str(row["provenance_transport"])
                         for row in judgments if row["provenance_transport"]})
    unprovenanced = any(
        not row["run_id"] or not row["provenance_config_fingerprint"]
        for row in judgments)
    if unprovenanced:
        status = "mixed_with_unprovenanced" if fingerprints else "unprovenanced_legacy"
    elif len(fingerprints) != 1:
        status = "mixed_configuration"
    else:
        status = "comparable"
    if not sources and unprovenanced:
        sources = ["legacy/unprovenanced"]
    return {
        "configuration_status": status,
        "configuration_fingerprints": ";".join(fingerprints),
        "run_ids": ";".join(run_ids),
        "configuration_sources": ";".join(sources),
        "efforts": ";".join(efforts),
        "routes": ";".join(routes),
        "transports": ";".join(transports),
    }


def _calibration_summary(confidence_correct: list[tuple[float, int]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Decision-confidence calibration, with fixed bins suitable for CSV/plots.

    Model confidence is confidence in the chosen decision, not a calibrated
    probability of the positive class.  Thus the Brier score below is for
    *decision correctness* and threshold rows model a review policy of
    ``confidence < threshold``.
    """
    if not confidence_correct:
        return ({
            "calibration_n": 0,
            "calibration_empirical_accuracy": None,
            "calibration_gap": None,
            "decision_confidence_brier": None,
            "expected_calibration_error": None,
        }, [])
    n = len(confidence_correct)
    mean_confidence = mean(value for value, _ in confidence_correct)
    empirical_accuracy = mean(correct for _, correct in confidence_correct)
    brier = mean((confidence - correct) ** 2 for confidence, correct in confidence_correct)
    bins: list[dict[str, Any]] = []
    weighted_gap = 0.0
    # Make 1.0 fall in the final bin rather than create an eleventh bin.
    for bin_index in range(int(1 / CALIBRATION_BIN_WIDTH)):
        lower = round(bin_index * CALIBRATION_BIN_WIDTH, 2)
        upper = round((bin_index + 1) * CALIBRATION_BIN_WIDTH, 2)
        values = [(confidence, correct) for confidence, correct in confidence_correct
                  if lower <= confidence < upper or
                  (bin_index == int(1 / CALIBRATION_BIN_WIDTH) - 1 and confidence == 1.0)]
        if not values:
            continue
        bin_mean_confidence = mean(confidence for confidence, _ in values)
        bin_accuracy = mean(correct for _, correct in values)
        gap = bin_mean_confidence - bin_accuracy
        weighted_gap += len(values) / n * abs(gap)
        bins.append({
            "bin_lower": lower,
            "bin_upper": upper,
            "n": len(values),
            "mean_confidence": _rounded(bin_mean_confidence),
            "empirical_accuracy": _rounded(bin_accuracy),
            "calibration_gap": _rounded(gap),
        })
    return ({
        "calibration_n": n,
        "calibration_empirical_accuracy": _rounded(empirical_accuracy),
        "calibration_gap": _rounded(mean_confidence - empirical_accuracy),
        "decision_confidence_brier": _rounded(brier),
        "expected_calibration_error": _rounded(weighted_gap),
    }, bins)


def _threshold_summary(confidence_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Show review load and retained binary performance at fixed thresholds."""
    rows: list[dict[str, Any]] = []
    n = len(confidence_cases)
    for threshold in CONFIDENCE_THRESHOLDS:
        low = [case for case in confidence_cases if case["confidence"] < threshold]
        retained = [case for case in confidence_cases if case["confidence"] >= threshold]
        tp = sum(case["outcome"] == "true_positive" for case in retained)
        tn = sum(case["outcome"] == "true_negative" for case in retained)
        fp = sum(case["outcome"] == "false_positive" for case in retained)
        fn = sum(case["outcome"] == "false_negative" for case in retained)
        retained_n = len(retained)
        rows.append({
            "threshold": threshold,
            "confidence_n": n,
            "low_confidence_n": len(low),
            "low_confidence_rate": _rounded(_ratio(len(low), n)),
            "retained_n": retained_n,
            "retained_accuracy": _rounded(_ratio(tp + tn, retained_n)),
            "retained_sensitivity": _rounded(_ratio(tp, tp + fn)),
            "retained_specificity": _rounded(_ratio(tn, tn + fp)),
        })
    return rows


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
    calibration_bins: list[dict[str, Any]]
    threshold_rows: list[dict[str, Any]]

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
    confidence_correct: list[tuple[float, int]] = []
    confidence_cases: list[dict[str, Any]] = []
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
                "run_id": "", "response_id": "", "configuration_fingerprint": "",
                "configuration_source": "", "effort": "", "route": "",
                "transport": "",
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
            if confidence is not None:
                confidence_value = float(confidence)
                confidence_correct.append((confidence_value, int(
                    outcome in ("true_positive", "true_negative"))))
                confidence_cases.append({"confidence": confidence_value, "outcome": outcome})
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
            "run_id": judgment["run_id"] or "",
            "response_id": judgment["response_id"] or "",
            "configuration_fingerprint": judgment["provenance_config_fingerprint"] or "",
            "configuration_source": judgment["provenance_source_path"] or "",
            "effort": judgment["provenance_effort"] or "",
            "route": judgment["provenance_route"] or "",
            "transport": judgment["provenance_transport"] or "",
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
            "run_id": judgment["run_id"] or "",
            "response_id": judgment["response_id"] or "",
            "configuration_fingerprint": judgment["provenance_config_fingerprint"] or "",
            "configuration_source": judgment["provenance_source_path"] or "",
            "effort": judgment["provenance_effort"] or "",
            "route": judgment["provenance_route"] or "",
            "transport": judgment["provenance_transport"] or "",
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

    accuracy_low, accuracy_high = _wilson_interval(tp + tn, scored)
    sensitivity_low, sensitivity_high = _wilson_interval(tp, tp + fn)
    specificity_low, specificity_high = _wilson_interval(tn, tn + fp)
    calibration, calibration_bins = _calibration_summary(confidence_correct)
    threshold_rows = _threshold_summary(confidence_cases)
    configuration = _configuration_summary(judgments)

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
        "accuracy_ci95_low": _rounded(accuracy_low),
        "accuracy_ci95_high": _rounded(accuracy_high),
        "sensitivity_ci95_low": _rounded(sensitivity_low),
        "sensitivity_ci95_high": _rounded(sensitivity_high),
        "specificity_ci95_low": _rounded(specificity_low),
        "specificity_ci95_high": _rounded(specificity_high),
        # Kappa needs a paired bootstrap or another resampling design to get a
        # defensible interval.  It is intentionally not given a pseudo-binomial
        # Wilson interval just because accuracy has one.
        "cohen_kappa_ci95_method": "not_estimated",
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
        **calibration,
        **configuration,
    }
    return TaskEvaluation(task=task, split=split,
                          promptbook_version=promptbook_version,
                          metrics=metrics, cases=cases,
                          calibration_bins=calibration_bins,
                          threshold_rows=threshold_rows)


def evaluate_tasks(conn, tasks: Iterable[str] = db.TASKS, *,
                   split: str = db.SPLIT_BUILD,
                   promptbook_version: str | None = None) -> list[TaskEvaluation]:
    """Evaluate several tasks in their supplied, stable order."""
    return [evaluate_task(conn, task, split=split,
                          promptbook_version=promptbook_version)
            for task in tasks]


def _calibration_rows(results: Iterable[TaskEvaluation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        summary = result.summary_row()
        for bin_row in result.calibration_bins:
            rows.append({
                "task": result.task,
                "split": result.split,
                "promptbook_version": summary["promptbook_version"],
                "configuration_status": summary["configuration_status"],
                **bin_row,
            })
    return rows


def _threshold_rows(results: Iterable[TaskEvaluation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        summary = result.summary_row()
        for threshold_row in result.threshold_rows:
            rows.append({
                "task": result.task,
                "split": result.split,
                "promptbook_version": summary["promptbook_version"],
                "configuration_status": summary["configuration_status"],
                **threshold_row,
            })
    return rows


def _write_csv(path: Path, *, columns: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_evaluation(output_dir: Path, results: Iterable[TaskEvaluation], *,
                     generated_at: str | None = None) -> dict[str, Path]:
    """Write CSV, JSON, and Markdown reporting artifacts; never write SQLite."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = list(results)
    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    summaries = [result.summary_row() for result in results]
    cases = [case for result in results for case in result.cases]
    calibration_rows = _calibration_rows(results)
    threshold_rows = _threshold_rows(results)

    summary_csv = output_dir / "summary.csv"
    _write_csv(summary_csv, columns=SUMMARY_COLUMNS, rows=summaries)

    cases_csv = output_dir / "cases.csv"
    _write_csv(cases_csv, columns=CASE_COLUMNS, rows=cases)

    calibration_csv = output_dir / "confidence_calibration.csv"
    _write_csv(calibration_csv, columns=CALIBRATION_COLUMNS, rows=calibration_rows)

    thresholds_csv = output_dir / "confidence_thresholds.csv"
    _write_csv(thresholds_csv, columns=THRESHOLD_COLUMNS, rows=threshold_rows)

    summary_json = output_dir / "summary.json"
    summary_json.write_text(json.dumps({
        "generated_at": generated_at,
        "results": summaries,
        "calibration_bins": calibration_rows,
        "confidence_thresholds": threshold_rows,
        "notes": {
            "confidence": "Confidence is confidence in the chosen decision.",
            "threshold": "low_confidence means confidence < threshold; retained rows have confidence >= threshold.",
            "intervals": "Accuracy, sensitivity, and specificity use two-sided 95% Wilson intervals. Kappa interval is not estimated.",
        },
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
        "Binary denominators are explicit: accuracy uses TP + TN + FP + FN; "
        "sensitivity uses TP + FN; specificity uses TN + FP. For exclusion, "
        "FP is a false exclusion and FN is a false keep. `undecidable`, "
        "`wrong_text`, and missing judgments are reported separately.",
        "",
        "## 95% Wilson intervals",
        "",
        "| Task | Accuracy interval | Sensitivity interval | Specificity interval |",
        "|---|---|---|---|",
    ]
    for row in summaries:
        lines.append(
            "| {task} | [{accuracy_low}, {accuracy_high}] | [{sensitivity_low}, {sensitivity_high}] | [{specificity_low}, {specificity_high}] |".format(
                task=row["task"],
                accuracy_low=_format_metric(row["accuracy_ci95_low"], percent=True),
                accuracy_high=_format_metric(row["accuracy_ci95_high"], percent=True),
                sensitivity_low=_format_metric(row["sensitivity_ci95_low"], percent=True),
                sensitivity_high=_format_metric(row["sensitivity_ci95_high"], percent=True),
                specificity_low=_format_metric(row["specificity_ci95_low"], percent=True),
                specificity_high=_format_metric(row["specificity_ci95_high"], percent=True),
            ))
    lines += [
        "",
        "Kappa has no interval here: a binomial Wilson interval would be invalid "
        "for chance-corrected agreement. A paired bootstrap must be specified "
        "separately if an interval is needed for publication.",
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
        "| Task | Configuration | Effort(s) | Route(s) | Transport(s) | Run ID(s) | Source(s) |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in summaries:
        lines.append(
            "| {task} | {status} | {efforts} | {routes} | {transports} | {run_ids} | {sources} |".format(
                task=row["task"], status=row["configuration_status"],
                efforts=row["efforts"] or "none", routes=row["routes"] or "none",
                transports=row["transports"] or "none", run_ids=row["run_ids"] or "none",
                sources=row["configuration_sources"] or "none"))
    lines += [
        "",
        "Only `comparable` means one fully recorded configuration. Mixed or legacy "
        "rows remain useful descriptive evidence, but are refused for DC17/G11 "
        "promptbook-history/plateau comparisons.",
        "",
        "## Confidence calibration and review thresholds",
        "",
        "Confidence is confidence in the chosen decision. `confidence_calibration.csv` "
        "contains fixed bins; `confidence_thresholds.csv` treats `confidence < threshold` "
        "as a review candidate and reports retained binary performance. These are "
        "descriptive build-set sweeps, not a tuned production threshold.",
        "",
        "## Files",
        "",
        "- `summary.csv`: one row per task for Excel/R/plotting, including configuration and intervals.",
        "- `cases.csv`: paper-level truth, prediction, confidence, error class, run, and response ID.",
        "- `confidence_calibration.csv`: fixed-bin calibration data.",
        "- `confidence_thresholds.csv`: review-load/retained-performance sweep from 0.50 to 0.95.",
        "- `summary.json`: machine-readable aggregates, calibration, and threshold rows.",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {"summary_csv": summary_csv, "cases_csv": cases_csv,
            "calibration_csv": calibration_csv, "thresholds_csv": thresholds_csv,
            "summary_json": summary_json, "report": report}


def require_history_eligible(results: Iterable[TaskEvaluation]) -> None:
    """Refuse a DC17 history publication for mixed or unknown configuration."""
    invalid = []
    for result in results:
        summary = result.summary_row()
        if summary["configuration_status"] != "comparable":
            invalid.append(
                f"{result.task}: {summary['configuration_status']} "
                f"(runs={summary['run_ids'] or 'none'})")
    if invalid:
        raise ConfigurationRefusal(
            "Refusing to append promptbook accuracy history: a DC17/G11 row must "
            "come from one fully provenanced configuration. " + "; ".join(invalid))


def append_accuracy_history(history_path: Path, results: Iterable[TaskEvaluation], *,
                            generated_at: str | None = None) -> Path:
    """Explicitly append clean configuration rows to promptbook history.

    All results are validated before the file opens for write.  A changed
    configuration is retained as a new observation but marked as an
    incomparable boundary, so a plateau calculation cannot bridge it.
    """
    results = list(results)
    require_history_eligible(results)
    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    history_path = Path(history_path)
    existing: list[dict[str, str]] = []
    if history_path.is_file():
        with history_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != HISTORY_COLUMNS:
                raise ConfigurationRefusal(
                    f"{history_path} has an incompatible history header; migrate it "
                    "deliberately instead of silently changing a published record")
            existing = list(reader)

    rows: list[dict[str, Any]] = []
    for result in results:
        summary = result.summary_row()
        config_fingerprint = summary["configuration_fingerprints"]
        duplicate = any(
            row["task"] == result.task and row["split"] == result.split and
            row["promptbook_version"] == summary["promptbook_version"] and
            row["run_ids"] == summary["run_ids"]
            for row in existing)
        if duplicate:
            raise ConfigurationRefusal(
                f"{result.task}/{result.split} with these run IDs is already in "
                f"{history_path}; refusing a duplicate history observation")
        previous = next((row for row in reversed(existing)
                         if row["task"] == result.task and row["split"] == result.split),
                        None)
        comparable_to_previous = bool(previous and
                                      previous["configuration_status"] == "comparable" and
                                      previous["configuration_fingerprint"] == config_fingerprint)
        if previous is None:
            note = "first fully-provenanced observation for this task/split"
        elif comparable_to_previous:
            note = "same configuration as previous row; eligible for DC17 comparison"
        else:
            note = "configuration changed; DC17 comparison to previous row is forbidden"
        rows.append({
            "generated_at": generated_at,
            "task": result.task,
            "split": result.split,
            "promptbook_version": summary["promptbook_version"],
            "eligible": summary["eligible"],
            "scored": summary["scored"],
            "accuracy": summary["accuracy"],
            "sensitivity": summary["sensitivity"],
            "specificity": summary["specificity"],
            "cohen_kappa": summary["cohen_kappa"],
            "configuration_status": summary["configuration_status"],
            "configuration_fingerprint": config_fingerprint,
            "run_ids": summary["run_ids"],
            "configuration_sources": summary["configuration_sources"],
            "comparable_to_previous": "yes" if comparable_to_previous else "no",
            "comparison_note": note,
        })

    history_path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(history_path, columns=HISTORY_COLUMNS, rows=[*existing, *rows])
    return history_path
