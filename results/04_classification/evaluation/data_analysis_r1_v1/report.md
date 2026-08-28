# Classification evaluation

Generated: `2026-08-28T23:01:10+00:00`

`yes` is the positive class. Sensitivity = recall for `yes`; specificity = recall for `no`. Cohen's kappa is chance-corrected agreement and is shown as `—` when mathematically undefined.

| Task | Eligible | Coverage | Scored | Accuracy | Sensitivity | Specificity | Precision | F1 | Cohen's κ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| data_analysis | 120 | 33.3% | 40 | 82.5% | 20.0% | 91.4% | 25.0% | 0.222 | 0.125 |

Binary denominators are explicit: accuracy uses TP + TN + FP + FN; sensitivity uses TP + FN; specificity uses TN + FP. For exclusion, FP is a false exclusion and FN is a false keep. `undecidable`, `wrong_text`, and missing judgments are reported separately.

## 95% Wilson intervals

| Task | Accuracy interval | Sensitivity interval | Specificity interval |
|---|---|---|---|
| data_analysis | [68.0%, 91.2%] | [3.6%, 62.5%] | [77.6%, 97.0%] |

Kappa has no interval here: a binomial Wilson interval would be invalid for chance-corrected agreement. A paired bootstrap must be specified separately if an interval is needed for publication.

## Confusion matrices

| Task | TP | TN | FP | FN | Undecidable | Wrong text | Missing | Unlabelled judgments |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| data_analysis | 1 | 32 | 3 | 4 | 0 | 0 | 80 | 0 |

## Persisted provenance

| Task | Model(s) | Pass(es) |
|---|---|---|
| data_analysis | claude-sonnet-5 | primary |

| Task | Configuration | Effort(s) | Route(s) | Transport(s) | Run ID(s) | Source(s) |
|---|---|---|---|---|---|---|
| data_analysis | comparable | high | data_analysis | reading_room | run-data_analysis-r1-060a29aa3b615279e75d | C:\Users\charl\OneDrive\Desktop\CU Anschutz Research\Cluster-Paper Review\results\04_classification\raw\data_analysis_r1\run_environment.json |

Only `comparable` means one fully recorded configuration. Mixed or legacy rows remain useful descriptive evidence, but are refused for DC17/G11 promptbook-history/plateau comparisons.

## Confidence calibration and review thresholds

Confidence is confidence in the chosen decision. `confidence_calibration.csv` contains fixed bins; `confidence_thresholds.csv` treats `confidence < threshold` as a review candidate and reports retained binary performance. These are descriptive build-set sweeps, not a tuned production threshold.

## Files

- `summary.csv`: one row per task for Excel/R/plotting, including configuration and intervals.
- `cases.csv`: paper-level truth, prediction, confidence, error class, run, and response ID.
- `confidence_calibration.csv`: fixed-bin calibration data.
- `confidence_thresholds.csv`: review-load/retained-performance sweep from 0.50 to 0.95.
- `summary.json`: machine-readable aggregates, calibration, and threshold rows.
