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
import html
import json
import math
import re
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


# ------------------------------------------------------------- HTML dashboard

# Every number this module calculates is on the page, but they are not equally
# load-bearing and a reader cannot tell that from a metric name alone. Each one
# carries a tier so the page can say plainly what a decision may rest on.
TIER_LABEL = {
    "primary": ("Primary",
                "the round's result — a promptbook change is judged on these, and "
                "the DC17 plateau rule reads accuracy"),
    "guardrail": ("Guardrail",
                  "these can invalidate the primary numbers; read them before "
                  "believing an accuracy"),
    "support": ("Supporting",
                "describes the shape of the errors and the model's confidence; "
                "never a stopping criterion on its own"),
}

TIER_ORDER = ["primary", "guardrail", "support"]

# `yes` is one word in the schema and two different claims across tasks, so every
# gloss below is written per task rather than in the schema's vocabulary.
TASK_WORDS = {
    "exclusion": {
        "yes": "exclude", "no": "keep",
        "positive": "papers the human excluded",
        "negative": "papers the human kept",
        "sensitivity": "Share of human-excluded papers the model also excluded. A miss "
                       "here is a false keep: recoverable, a human still sees the paper.",
        "specificity": "Share of human-kept papers the model also kept. **This is the "
                       "critical direction for the gate** — a miss here is a false "
                       "exclusion, and the paper never reaches power or data analysis.",
        "false_positive": "False exclusions — **unrecoverable**. The model dropped a "
                          "paper the human kept, so no later task ever sees it.",
        "false_negative": "False keeps. The model kept a paper the human excluded: "
                          "wasteful, but recoverable downstream.",
        "precision": "Of the papers the model excluded, the share the human also excluded.",
        "npv": "Of the papers the model kept, the share the human also kept.",
    },
    "analysis": {
        "yes": "correct", "no": "flawed",
        "positive": "analyses the human judged correct",
        "negative": "analyses the human judged flawed",
        "sensitivity": "Share of human-correct analyses the model also called correct. "
                       "A miss here means the model is too strict.",
        "specificity": "Share of human-flawed analyses the model also called flawed. A "
                       "miss here means the model is too lenient — it waved a flawed "
                       "analysis through.",
        "false_positive": "Model too lenient: it called a flawed analysis correct.",
        "false_negative": "Model too strict: it called a correct analysis flawed.",
        "precision": "Of the analyses the model called correct, the share the human also did.",
        "npv": "Of the analyses the model called flawed, the share the human also did.",
    },
}


def task_words(task: str) -> dict[str, str]:
    """Reader-facing vocabulary for one task; analyses share a wording."""
    return TASK_WORDS.get(task, TASK_WORDS["analysis"])


def _pct(value: Any) -> str:
    return _format_metric(value, percent=True)


def _num(value: Any) -> str:
    return _format_metric(value)


def _interval(row: dict[str, Any], stem: str) -> str:
    low, high = row.get(f"{stem}_ci95_low"), row.get(f"{stem}_ci95_high")
    if low is None or high is None:
        return "no interval at n = 0"
    return f"95% CI {_pct(low)} – {_pct(high)}"


def _inline(text: str) -> str:
    """Escape, then honour the `**bold**` and `` `code` `` used in the glosses."""
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)


def _metric_rows(row: dict[str, Any]) -> list[dict[str, str]]:
    """Every statistic calculated for one task, tiered and explained."""
    words = task_words(row["task"])
    tp, tn = row["true_positive"], row["true_negative"]
    fp, fn = row["false_positive"], row["false_negative"]
    undecidable_rate = _ratio(row["undecidable"], row["judged_eligible"])
    fingerprints = row["configuration_fingerprints"]
    return [
        # ---------------------------------------------------------- primary
        {"tier": "primary", "name": "Accuracy", "value": _pct(row["accuracy"]),
         "detail": f"(TP + TN) / scored = {tp + tn} / {row['scored']} · "
                   + _interval(row, "accuracy"),
         "why": "The DC17 plateau rule reads this one: two consecutive rounds each "
                "improving by under 1pp ends the promptbook loop. Compare rounds "
                "through the interval, not the point estimate — at 50 papers a 1pp "
                "move is well inside the noise."},
        {"tier": "primary", "name": "Sensitivity", "value": _pct(row["sensitivity"]),
         "detail": f"TP / (TP + FN) = {tp} / {tp + fn} · " + _interval(row, "sensitivity"),
         "why": words["sensitivity"]},
        {"tier": "primary", "name": "Specificity", "value": _pct(row["specificity"]),
         "detail": f"TN / (TN + FP) = {tn} / {tn + fp} · " + _interval(row, "specificity"),
         "why": words["specificity"]},
        {"tier": "primary", "name": "Cohen's kappa", "value": _num(row["cohen_kappa"]),
         "detail": "interval " + row["cohen_kappa_ci95_method"].replace("_", " ")
                   + " — a binomial interval would be invalid here",
         "why": "Agreement corrected for what the two marginal distributions would "
                "produce by chance. On a lopsided split this is the honest headline: "
                "accuracy can look high purely because one class dominates. Shown as "
                "— when expected agreement is 1 and kappa is undefined."},
        # -------------------------------------------------------- guardrail
        {"tier": "guardrail", "name": "Eligible papers", "value": str(row["eligible"]),
         "detail": f"{row['split']} split · {row['persisted_judgments']} persisted judgments",
         "why": "Papers in this split carrying a human answer for this task. Power and "
                "data analysis score only gate survivors, so their eligible count is "
                "smaller than exclusion's by design, not by loss."},
        {"tier": "guardrail", "name": "Coverage", "value": _pct(row["coverage"]),
         "detail": f"{row['judged_eligible']} of {row['eligible']} judged · "
                   f"{row['missing']} missing",
         "why": "Share of eligible papers with a persisted judgment. Below 100% the "
                "accuracy above describes a subset, not the split — and a partial "
                "round is not the full-build-split regression run DC17 asks for."},
        {"tier": "guardrail", "name": "Scored", "value": str(row["scored"]),
         "detail": f"TP + TN + FP + FN · {_pct(row['scoreable_coverage'])} of eligible",
         "why": "The binary denominator. Abstentions, wrong-text reports and missing "
                "rows sit outside it, which is what stops them being silently counted "
                "as mistakes."},
        {"tier": "guardrail", "name": "Undecidable", "value": str(row["undecidable"]),
         "detail": f"{_pct(undecidable_rate)} of judged papers",
         "why": "Abstentions, not a category. **Watch this against accuracy**: rising "
                "while accuracy holds flat means the promptbook is teaching the model "
                "to abstain rather than to judge."},
        {"tier": "guardrail", "name": "Wrong text", "value": str(row["wrong_text"]),
         "detail": "reported by the model, not detected here",
         "why": "The model said the text it was handed was not the paper. Any count "
                "above zero is a corpus or extraction problem to chase before these "
                "metrics mean anything."},
        {"tier": "guardrail", "name": "Missing judgments", "value": str(row["missing"]),
         "detail": f"of {row['eligible']} eligible",
         "why": "Eligible papers with no persisted judgment. Pairing is label-first so "
                "these cut coverage instead of quietly shrinking the denominator."},
        {"tier": "guardrail", "name": "Unlabelled judgments",
         "value": str(row["unlabeled_judgments"]),
         "detail": "persisted, but not scoreable against this split",
         "why": "Judgments that could not pair to an eligible label — a split mismatch, "
                "or an analysis judgment on a human-excluded paper. Evidence worth "
                "investigating, not rows to drop invisibly."},
        {"tier": "guardrail", "name": "Configuration",
         "value": row["configuration_status"].replace("_", " "),
         "detail": f"{len(fingerprints.split(';')) if fingerprints else 0} fingerprint(s)",
         "why": "Only `comparable` means one fully recorded configuration. Mixed or "
                "legacy rows stay useful as description, but are refused for a "
                "`promptbook_accuracy_history.csv` row or a plateau claim."},
        # ---------------------------------------------------------- support
        {"tier": "support", "name": "Precision", "value": _pct(row["precision"]),
         "detail": f"TP / (TP + FP) = {tp} / {tp + fp}",
         "why": words["precision"]},
        {"tier": "support", "name": "Negative predictive value",
         "value": _pct(row["negative_predictive_value"]),
         "detail": f"TN / (TN + FN) = {tn} / {tn + fn}",
         "why": words["npv"]},
        {"tier": "support", "name": "F1", "value": _num(row["f1"]),
         "detail": "harmonic mean of precision and sensitivity",
         "why": "Ignores TN entirely, so it says nothing about the negative class. "
                "Fine for comparing runs, misleading as a single headline here."},
        {"tier": "support", "name": "Balanced accuracy",
         "value": _pct(row["balanced_accuracy"]),
         "detail": "(sensitivity + specificity) / 2",
         "why": "Accuracy with both classes weighted equally. A large gap between this "
                "and plain accuracy means the majority class is carrying the headline."},
        {"tier": "support", "name": "Confidence", "value": _num(row["confidence_mean"]),
         "detail": f"mean of n = {row['confidence_n']} · range "
                   f"{_num(row['confidence_min'])}–{_num(row['confidence_max'])} · "
                   f"{row['distinct_confidences']} distinct values",
         "why": "Confidence in the chosen decision, not a probability of the positive "
                "class. Few distinct values means the model is picking from a habit of "
                "round numbers, which caps what any threshold can do."},
        {"tier": "support", "name": "Calibration gap", "value": _num(row["calibration_gap"]),
         "detail": f"mean confidence − empirical accuracy "
                   f"({_pct(row['calibration_empirical_accuracy'])}) · "
                   f"n = {row['calibration_n']}",
         "why": "Positive means overconfident: the model claims more certainty than its "
                "answers earn. This is what makes a confidence threshold either useful "
                "or a false comfort."},
        {"tier": "support", "name": "Expected calibration error",
         "value": _num(row["expected_calibration_error"]),
         "detail": "bin-weighted mean of |gap|",
         "why": "The calibration gap without cancellation, so an overconfident bin and "
                "an underconfident bin cannot average each other away."},
        {"tier": "support", "name": "Brier score (decision)",
         "value": _num(row["decision_confidence_brier"]),
         "detail": "mean squared error of confidence against correctness · lower is better",
         "why": "Scores confidence and correctness together: it rewards being right, and "
                "being right about how sure you were."},
    ]


def _tile(label: str, value: str, foot: str, tone: str) -> str:
    return (f'<div class="tile {tone}"><span class="tile-k">{html.escape(label)}</span>'
            f'<span class="tile-v">{html.escape(value)}</span>'
            f'<span class="tile-f">{html.escape(foot)}</span></div>')


def _table(headers: list[str], body: list[list[str]], *, numeric_from: int = 1) -> str:
    """Cells at or after ``numeric_from`` are right-aligned and tabular."""
    def klass(index: int) -> str:
        return ' class="r"' if index >= numeric_from else ""
    head = "".join(f"<th{klass(index)}>{html.escape(text)}</th>"
                   for index, text in enumerate(headers))
    rows = "".join(
        "<tr>" + "".join(f"<td{klass(index)}>{cell}</td>"
                         for index, cell in enumerate(line)) + "</tr>"
        for line in body)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"


def _confusion(row: dict[str, Any]) -> str:
    words = task_words(row["task"])
    yes, no = words["yes"], words["no"]
    cells = [
        ("true_positive", "TP", row["true_positive"], f"human {yes} · model {yes}"),
        ("false_negative", "FN", row["false_negative"], f"human {yes} · model {no}"),
        ("false_positive", "FP", row["false_positive"], f"human {no} · model {yes}"),
        ("true_negative", "TN", row["true_negative"], f"human {no} · model {no}"),
    ]
    grid = "".join(
        f'<div class="cell {key}"><span class="cell-k">{code}</span>'
        f'<span class="cell-v">{count}</span>'
        f'<span class="cell-f">{html.escape(gloss)}</span></div>'
        for key, code, count, gloss in cells)
    return (f'<div class="grid">{grid}</div>'
            f'<p class="note">{_inline(words["false_positive"])}<br>'
            f'{_inline(words["false_negative"])}</p>')


def _metric_table(row: dict[str, Any]) -> str:
    body = []
    for metric in sorted(_metric_rows(row),
                         key=lambda item: TIER_ORDER.index(item["tier"])):
        tier = metric["tier"]
        body.append([
            f'<span class="tag {tier}">{TIER_LABEL[tier][0]}</span>',
            f'<b>{html.escape(metric["name"])}</b>',
            f'<span class="big">{html.escape(metric["value"])}</span>',
            f'<span class="muted">{_inline(metric["detail"])}</span>',
            _inline(metric["why"]),
        ])
    return _table(["Tier", "Statistic", "Value", "How it is built", "Why it matters"],
                  body, numeric_from=99)


def _calibration_table(result: TaskEvaluation) -> str:
    if not result.calibration_bins:
        return '<p class="note">No scored judgment carried a confidence value.</p>'
    body = [[f'{bin_row["bin_lower"]:.2f} – {bin_row["bin_upper"]:.2f}',
             str(bin_row["n"]), _num(bin_row["mean_confidence"]),
             _pct(bin_row["empirical_accuracy"]), _num(bin_row["calibration_gap"])]
            for bin_row in result.calibration_bins]
    return _table(["Confidence bin", "n", "Mean confidence", "Empirical accuracy", "Gap"],
                  body)


def _threshold_table(result: TaskEvaluation) -> str:
    rows = [row for row in result.threshold_rows if row["confidence_n"]]
    if not rows:
        return '<p class="note">No scored judgment carried a confidence value.</p>'
    body = [[f'{row["threshold"]:.2f}', str(row["low_confidence_n"]),
             _pct(row["low_confidence_rate"]), str(row["retained_n"]),
             _pct(row["retained_accuracy"]), _pct(row["retained_sensitivity"]),
             _pct(row["retained_specificity"])] for row in rows]
    return _table(["Threshold", "Sent to review", "Review load", "Retained n",
                   "Retained accuracy", "Retained sensitivity", "Retained specificity"],
                  body)


def _provenance_table(row: dict[str, Any]) -> str:
    fields = [("Model(s)", row["models"]), ("Pass(es)", row["pass_names"]),
              ("Configuration", row["configuration_status"].replace("_", " ")),
              ("Effort(s)", row["efforts"]), ("Route(s)", row["routes"]),
              ("Transport(s)", row["transports"]), ("Run ID(s)", row["run_ids"]),
              ("Fingerprint(s)", row["configuration_fingerprints"]),
              ("Source(s)", row["configuration_sources"])]
    body = [[f"<b>{html.escape(name)}</b>",
             f"<code>{html.escape(str(value))}</code>" if value
             else '<span class="muted">none</span>']
            for name, value in fields]
    return _table(["Field", "Recorded"], body, numeric_from=99)


def _task_section(result: TaskEvaluation) -> str:
    row = result.summary_row()
    words = task_words(result.task)
    scored = row["scored"]
    tone = ("unlabelled" if not scored
            else "true_positive" if (row["accuracy"] or 0) >= 0.9
            else "false_positive")
    tiles = "".join([
        _tile("Accuracy", _pct(row["accuracy"]), _interval(row, "accuracy"), tone),
        _tile("Sensitivity", _pct(row["sensitivity"]),
              f'recall on {words["positive"]}', "true_positive"),
        _tile("Specificity", _pct(row["specificity"]),
              f'recall on {words["negative"]}', "true_negative"),
        _tile("Cohen's kappa", _num(row["cohen_kappa"]),
              "chance-corrected agreement", "unlabelled"),
    ])
    subtitle = " · ".join(part for part in (
        f'{row["eligible"]} eligible',
        f'{_pct(row["coverage"])} coverage',
        f"{scored} scored",
        f'{row["undecidable"]} undecidable' if row["undecidable"] else "",
        f'{row["missing"]} missing' if row["missing"] else "",
        row["configuration_status"].replace("_", " ")) if part)
    empty = ('<p class="warn">No scoreable judgment for this task, so every rate below '
             'is undefined rather than zero.</p>' if not scored else "")
    return f"""<article class="card task {tone}" data-task="{html.escape(result.task)}">
<header><span class="tag {tone}">{html.escape(result.task.replace("_", " "))}</span>
<h2>{html.escape(result.task)} &middot; {html.escape(result.split)} split
&middot; {html.escape(row["promptbook_version"])}</h2>
<p class="who">{html.escape(subtitle)}</p></header>
{empty}
<div class="tiles">{tiles}</div>
<h3>Confusion matrix</h3>
{_confusion(row)}
<h3>Every calculated statistic</h3>
{_metric_table(row)}
<h3>Confidence calibration</h3>
<p class="note">Confidence is confidence in the chosen decision, not a probability of
&ldquo;{html.escape(words["yes"])}&rdquo;. A positive gap means overconfident.</p>
{_calibration_table(result)}
<h3>Review-threshold sweep</h3>
<p class="note">A policy of &ldquo;send every judgment below the threshold to a human&rdquo;.
A descriptive build-split sweep, not a tuned production threshold.</p>
{_threshold_table(result)}
<h3>Provenance</h3>
{_provenance_table(row)}
</article>"""


def render_html(results: Iterable[TaskEvaluation], *,
                generated_at: str | None = None) -> str:
    """A self-contained page carrying every statistic, ranked by what it decides."""
    results = list(results)
    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    summaries = [result.summary_row() for result in results]
    split = summaries[0]["split"] if summaries else ""
    version = summaries[0]["promptbook_version"] if summaries else ""

    chips = [f'<button class="chip active" data-task="all">'
             f"Every task <b>{len(results)}</b></button>"]
    for result, row in zip(results, summaries):
        chips.append(
            f'<button class="chip" data-task="{html.escape(result.task)}">'
            f'{html.escape(result.task.replace("_", " "))} '
            f'<b>{_pct(row["accuracy"])}</b></button>')

    legend = "".join(
        f'<div class="legend-row"><span class="tag {tier}">{TIER_LABEL[tier][0]}</span>'
        f"<span>{_inline(TIER_LABEL[tier][1])}</span></div>" for tier in TIER_ORDER)

    unclean = [f'{row["task"]}: {row["configuration_status"].replace("_", " ")}'
               for row in summaries if row["configuration_status"] != "comparable"]
    warning = (f'<p class="warn">Not a clean DC17 history row — '
               f'{html.escape(" · ".join(unclean))}</p>' if unclean else "")

    subtitle = " · ".join(part for part in (
        f"{split} split", version, f"{len(results)} task(s)",
        f"generated {generated_at}") if part)

    return HTML_TEMPLATE.format(
        title="Classification evaluation", subtitle=html.escape(subtitle),
        warning=warning, chips="".join(chips), legend=legend,
        sections="\n".join(_task_section(result) for result in results))


HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  --bg:#fbfbfa; --card:#fff; --ink:#1a1a19; --muted:#6b6b66; --line:#e4e4e0;
  --fn:#b3261e; --fp:#a8590c; --tp:#1a7f4b; --tn:#5a5a55; --odd:#6b4ba8;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#17171a; --card:#1f1f23; --ink:#ececeb; --muted:#9a9a95; --line:#33333a;
    --fn:#ff8a80; --fp:#ffb870; --tp:#6fd39b; --tn:#9a9a95; --odd:#c0a3f0; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 -apple-system,
  BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif; }}
.wrap {{ max-width:1040px; margin:0 auto; padding:32px 20px 96px; }}
h1 {{ font-size:22px; margin:0 0 4px; letter-spacing:-.01em; }}
.sub {{ color:var(--muted); font-size:13px; margin:0; }}
.warn {{ color:var(--fp); font-size:13px; margin:8px 0 0; }}
.bar {{ position:sticky; top:0; z-index:5; background:var(--bg); padding:16px 0 12px;
  border-bottom:1px solid var(--line); margin:16px 0 20px; display:flex;
  flex-wrap:wrap; gap:8px; }}
.chip {{ font:inherit; font-size:13px; padding:5px 11px; border-radius:99px; cursor:pointer;
  border:1px solid var(--line); background:var(--card); color:var(--muted); }}
.chip b {{ color:var(--ink); }}
.chip.active {{ border-color:currentColor; color:var(--ink); }}
.tag.primary {{ color:var(--tp); }}
.tag.guardrail {{ color:var(--fp); }}
.tag.support {{ color:var(--tn); }}
.tag.true_positive {{ color:var(--tp); }}
.tag.true_negative {{ color:var(--tn); }}
.tag.false_positive {{ color:var(--fp); }}
.tag.false_negative {{ color:var(--fn); }}
.tag.unlabelled {{ color:var(--odd); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:16px 18px; margin-bottom:14px; border-left:3px solid currentColor;
  color:var(--tn); }}
.card.true_positive {{ color:var(--tp); }}
.card.false_positive {{ color:var(--fp); }}
.card.unlabelled {{ color:var(--odd); }}
.card > * {{ color:var(--ink); }}
.tag {{ display:inline-block; font-size:11px; font-weight:700; letter-spacing:.05em;
  text-transform:uppercase; border:1px solid currentColor; border-radius:99px;
  padding:1px 8px; margin-bottom:8px; white-space:nowrap; }}
header h2 {{ font-size:15px; font-weight:600; margin:0; line-height:1.4; }}
h3 {{ font-size:11px; font-weight:700; letter-spacing:.07em; text-transform:uppercase;
  color:var(--muted); margin:24px 0 6px; }}
.who {{ margin:2px 0 0; font-size:12px; color:var(--muted); }}
.legend {{ margin:-6px 0 20px; font-size:13px; color:var(--muted); }}
.legend summary {{ cursor:pointer; color:var(--muted); }}
.legend-row {{ display:flex; gap:10px; align-items:baseline; margin:10px 0 0;
  padding-left:2px; color:var(--tn); }}
.legend-row > span:last-child {{ color:var(--muted); flex:1; }}
.legend-row .tag {{ margin:0; flex:0 0 auto; min-width:110px; text-align:center; }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px;
  margin:12px 0 0; }}
.tile {{ border:1px solid var(--line); border-radius:8px; padding:10px 12px;
  display:flex; flex-direction:column; gap:2px; color:var(--tn); }}
.tile.true_positive {{ color:var(--tp); }}
.tile.false_positive {{ color:var(--fp); }}
.tile.unlabelled {{ color:var(--odd); }}
.tile-k {{ font-size:11px; font-weight:700; letter-spacing:.05em; text-transform:uppercase; }}
.tile-v {{ font:600 26px/1.15 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  color:var(--ink); letter-spacing:-.02em; font-variant-numeric:tabular-nums; }}
.tile-f {{ font-size:11.5px; color:var(--muted); }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:8px; }}
.cell {{ border:1px solid var(--line); border-radius:8px; padding:9px 11px;
  display:flex; flex-direction:column; gap:1px; color:var(--tn); }}
.cell.true_positive {{ color:var(--tp); }}
.cell.false_positive {{ color:var(--fp); }}
.cell.false_negative {{ color:var(--fn); }}
.cell-k {{ font:700 11px ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.06em; }}
.cell-v {{ font:600 20px/1.2 system-ui,sans-serif; color:var(--ink);
  font-variant-numeric:tabular-nums; }}
.cell-f {{ font-size:11.5px; color:var(--muted); }}
table {{ width:100%; border-collapse:collapse; font-size:13px; margin:4px 0 0; }}
th, td {{ text-align:left; padding:7px 9px; border-bottom:1px solid var(--line);
  vertical-align:top; }}
th {{ font-size:11px; letter-spacing:.05em; text-transform:uppercase; color:var(--muted);
  font-weight:700; white-space:nowrap; }}
td.r, th.r {{ text-align:right; font-variant-numeric:tabular-nums; }}
tbody tr:last-child td {{ border-bottom:none; }}
td .tag {{ margin:0; }}
.big {{ font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap; }}
.muted {{ color:var(--muted); font-size:12px; }}
.note {{ color:var(--muted); font-size:12.5px; margin:8px 0 0; }}
code {{ font:12px ui-monospace,SFMono-Regular,Menlo,monospace; word-break:break-all; }}
.card[hidden] {{ display:none; }}
.scroll {{ overflow-x:auto; }}
</style></head><body><div class="wrap">
<h1>{title}</h1><p class="sub">{subtitle}</p>{warning}
<div class="bar">{chips}</div>
<details class="legend"><summary>Which statistics are important, and why</summary>{legend}</details>
{sections}
</div><script>
var chips = document.querySelectorAll('.chip');
var cards = document.querySelectorAll('.card.task');
chips.forEach(function (chip) {{
  chip.addEventListener('click', function () {{
    var want = chip.dataset.task;
    chips.forEach(function (other) {{ other.classList.toggle('active', other === chip); }});
    cards.forEach(function (card) {{
      card.hidden = want !== 'all' && card.dataset.task !== want;
    }});
  }});
}});
</script></body></html>
"""


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
        "- `report.html`: the same statistics as a page, tiered by what each one decides.",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report_html = output_dir / "report.html"
    report_html.write_text(render_html(results, generated_at=generated_at),
                           encoding="utf-8")

    return {"summary_csv": summary_csv, "cases_csv": cases_csv,
            "calibration_csv": calibration_csv, "thresholds_csv": thresholds_csv,
            "summary_json": summary_json, "report": report,
            "report_html": report_html}


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
