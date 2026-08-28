# Classification evaluation

Generated: `2026-08-28T18:02:05+00:00`

`yes` is the positive class. Sensitivity = recall for `yes`; specificity = recall for `no`. Cohen's kappa is chance-corrected agreement and is shown as `—` when mathematically undefined.

| Task | Eligible | Coverage | Scored | Accuracy | Sensitivity | Specificity | Precision | F1 | Cohen's κ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| exclusion | 335 | 14.6% | 48 | 89.6% | 100.0% | 70.6% | 86.1% | 0.925 | 0.756 |
| power_analysis | 120 | 0.0% | 0 | — | — | — | — | — | — |
| data_analysis | 120 | 0.0% | 0 | — | — | — | — | — | — |

## Confusion matrices

| Task | TP | TN | FP | FN | Undecidable | Wrong text | Missing | Unlabelled judgments |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| exclusion | 31 | 12 | 5 | 0 | 0 | 1 | 286 | 0 |
| power_analysis | 0 | 0 | 0 | 0 | 0 | 0 | 120 | 0 |
| data_analysis | 0 | 0 | 0 | 0 | 0 | 0 | 120 | 0 |

## Persisted provenance

| Task | Model(s) | Pass(es) |
|---|---|---|
| exclusion | claude-sonnet-5 | primary |
| power_analysis | — | — |
| data_analysis | — | — |

The current `judgments` table does not store effort or runner route. Do not infer high/medium comparability from this report alone; verify historical effort from each run's `run_environment.json` until request-level provenance migration is implemented.

## Files

- `summary.csv`: one row per task for Excel/R/plotting.
- `cases.csv`: paper-level truth, prediction, confidence, and error class.
- `summary.json`: machine-readable aggregate metrics.
