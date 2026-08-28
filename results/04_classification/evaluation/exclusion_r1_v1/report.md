# Classification evaluation

Generated: `2026-08-28T23:38:52+00:00`

`yes` is the positive class. Sensitivity = recall for `yes`; specificity = recall for `no`. Cohen's kappa is chance-corrected agreement and is shown as `—` when mathematically undefined.

| Task | Eligible | Coverage | Scored | Accuracy | Sensitivity | Specificity | Precision | F1 | Cohen's κ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| exclusion | 335 | 14.6% | 48 | 89.6% | 100.0% | 70.6% | 86.1% | 0.925 | 0.756 |

Binary denominators are explicit: accuracy uses TP + TN + FP + FN; sensitivity uses TP + FN; specificity uses TN + FP. For exclusion, FP is a false exclusion and FN is a false keep. `undecidable`, `wrong_text`, and missing judgments are reported separately.

## 95% Wilson intervals

| Task | Accuracy interval | Sensitivity interval | Specificity interval |
|---|---|---|---|
| exclusion | [77.8%, 95.5%] | [89.0%, 100.0%] | [46.9%, 86.7%] |

Kappa has no interval here: a binomial Wilson interval would be invalid for chance-corrected agreement. A paired bootstrap must be specified separately if an interval is needed for publication.

## Confusion matrices

| Task | TP | TN | FP | FN | Undecidable | Wrong text | Missing | Unlabelled judgments |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| exclusion | 31 | 12 | 5 | 0 | 0 | 1 | 286 | 0 |

## Persisted provenance

| Task | Model(s) | Pass(es) |
|---|---|---|
| exclusion | claude-sonnet-5 | primary |

| Task | Configuration | Effort(s) | Route(s) | Transport(s) | Run ID(s) | Source(s) |
|---|---|---|---|---|---|---|
| exclusion | unprovenanced_legacy | none | none | none | none | legacy/unprovenanced |

Only `comparable` means one fully recorded configuration. Mixed or legacy rows remain useful descriptive evidence, but are refused for DC17/G11 promptbook-history/plateau comparisons.

## Confidence calibration and review thresholds

Confidence is confidence in the chosen decision. `confidence_calibration.csv` contains fixed bins; `confidence_thresholds.csv` treats `confidence < threshold` as a review candidate and reports retained binary performance. These are descriptive build-set sweeps, not a tuned production threshold.

## Files

- `summary.csv`: one row per task for Excel/R/plotting, including configuration and intervals.
- `cases.csv`: paper-level truth, prediction, confidence, error class, run, and response ID.
- `confidence_calibration.csv`: fixed-bin calibration data.
- `confidence_thresholds.csv`: review-load/retained-performance sweep from 0.50 to 0.95.
- `summary.json`: machine-readable aggregates, calibration, and threshold rows.
