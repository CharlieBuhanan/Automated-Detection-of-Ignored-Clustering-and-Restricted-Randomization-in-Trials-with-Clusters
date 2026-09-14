# Classification evaluation

Generated: `2026-08-29T03:57:22+00:00`

`yes` is the positive class. Sensitivity = recall for `yes`; specificity = recall for `no`. Cohen's kappa is chance-corrected agreement and is shown as `—` when mathematically undefined.

| Task | Eligible | Coverage | Scored | Accuracy | Sensitivity | Specificity | Precision | F1 | Cohen's κ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| exclusion | 335 | 14.6% | 48 | 89.6% | 100.0% | 70.6% | 86.1% | 0.925 | 0.756 |
| power_analysis | 120 | 40.8% | 49 | 79.6% | 37.5% | 87.8% | 37.5% | 0.375 | 0.253 |
| data_analysis | 120 | 40.0% | 48 | 79.2% | 28.6% | 87.8% | 28.6% | 0.286 | 0.164 |

Binary denominators are explicit: accuracy uses TP + TN + FP + FN; sensitivity uses TP + FN; specificity uses TN + FP. For exclusion, FP is a false exclusion and FN is a false keep. `undecidable`, `wrong_text`, and missing judgments are reported separately.

## 95% Wilson intervals

| Task | Accuracy interval | Sensitivity interval | Specificity interval |
|---|---|---|---|
| exclusion | [77.8%, 95.5%] | [89.0%, 100.0%] | [46.9%, 86.7%] |
| power_analysis | [66.4%, 88.5%] | [13.7%, 69.4%] | [74.5%, 94.7%] |
| data_analysis | [65.7%, 88.3%] | [8.2%, 64.1%] | [74.5%, 94.7%] |

Kappa has no interval here: a binomial Wilson interval would be invalid for chance-corrected agreement. A paired bootstrap must be specified separately if an interval is needed for publication.

## Confusion matrices

| Task | TP | TN | FP | FN | Undecidable | Wrong text | Missing | Unlabelled judgments |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| exclusion | 31 | 12 | 5 | 0 | 0 | 1 | 286 | 0 |
| power_analysis | 3 | 36 | 5 | 5 | 0 | 0 | 71 | 0 |
| data_analysis | 2 | 36 | 5 | 5 | 0 | 0 | 72 | 0 |

## Persisted provenance

| Task | Model(s) | Pass(es) |
|---|---|---|
| exclusion | claude-sonnet-5 | primary |
| power_analysis | claude-sonnet-5 | primary |
| data_analysis | claude-sonnet-5 | primary |

| Task | Configuration | Effort(s) | Route(s) | Transport(s) | Run ID(s) | Source(s) |
|---|---|---|---|---|---|---|
| exclusion | unprovenanced_legacy | none | none | none | none | legacy/unprovenanced |
| power_analysis | comparable | medium | power_analysis | reading_room | run-power_analysis-r1-34dd7a28df27c27898a9 | C:\Users\charl\OneDrive\Desktop\CU Anschutz Research\Cluster-Paper Review\results\04_classification\raw\power_analysis_v1_r1\run_environment.json |
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
- `report.html`: the same statistics as a page, tiered by what each one decides.
