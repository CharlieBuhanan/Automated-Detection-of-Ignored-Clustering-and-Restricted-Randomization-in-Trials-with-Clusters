# Promptbook v2 — version log

Machine-readable reporting metrics live in
`results/04_classification/promptbook_accuracy_history.csv`. Run environments
and raw responses retain the corresponding provenance.

## Version

| | |
|---|---|
| Version | `v2` |
| Created | 2026-08-28 |
| Parent | `v1` |
| Git commit | captured in each run environment |
| Model used to build it | none |
| Route | Reading Room (`scripts/20_reading_room.py`) |
| Status | **draft** — do not run until the expert adjudications are recorded |

## Delta from v1

The v2 decision criteria are unchanged from v1. The wording has been compacted
only; v2's functional delta is the **input configuration**, which evaluates the
same rubric against references-stripped text. Any future criterion edit requires
its own table row and a human-verified rationale before this draft is run-frozen.

| Change | Reason | Comparison rule |
|---|---|---|
| References-stripped input (`data/extracted_text_stripped/`) | Reference titles can cause false positives for criteria that do not describe the paper under review | Report v2 stripped-text results separately from v1 whole-text results (DC57) |
| Wording compaction | Removes repeated explanations without changing a criterion or rule ID | No decision-rule change |

### Ground-truth output contract (added 2026-11-24, still un-run)

v2 had no paid/raw request, so these were made in place (CLAUDE.md: no `v3` for an
un-run draft). Plan: `research design/GROUND_TRUTH_OUTPUT_PLAN.md`; columns:
`data/field_dictionary.csv`; parser: `schemas.ExclusionWithReason` /
`schemas.FullAnalysis`.

| Change | Reason | Comparison rule |
|---|---|---|
| `exclusion.md` also returns `exclusion_reason` (an E-number that must be cited) | Plan decision 4; 43-column export | Same E1-E18 criteria; no decision-rule change |
| New `combined_analysis.md`: Part A study design, then Part B power (P1-P18), then Part C data (D1-D15), each with a structured `done` record | Plan step 3; one call fills the 20 model columns | P and D criteria copied verbatim from `power_analysis.md` / `data_analysis.md`, except the row below |
| D4 adds: a planned analysis this manuscript describes is judged like a performed one | Deb Q7 (2026-11-09): a planned-only analysis can be `data_correct` yes | Criterion clarification, human-ruled |
| No few-clusters tag; D13 unchanged | User, 2026-11-24: work without the unconfirmed 40-cluster threshold (Deb.md 3a-3c). `small_sample_correction` still records the fact | If Deb confirms, add a rule to D13 in place before the first run |
| Each judgment also returns `should` (units, restricted_rand, longitudinality) | User, 2026-11-24: ask the model too, so its answer can be compared with the value code derives from Part A | Not a decision rule; never checked against `done` or the verdict |
| `n_long` replaced by `longitudinal: {baseline_measured, n_followup}`; code derives `n_long` | User, 2026-11-24. Human coding of baseline + one follow-up is split (most papers 2, some 1), so the model records the facts and the export picks the convention; the strict `not_applicable` check applies only to one follow-up with no baseline, or two or more follow-ups | Export counts baseline (majority human coding; GLIMMPSE's repeated-measures count); follow-up-only count reported beside it |
| Longitudinality defined once in Part A, including baseline as a covariate or change score = `accounted` | Same; the NHLBI table marks baseline-adjusted models as accounting for longitudinality (e.g. `4IBT3NAD`) | Does not affect `power_correct` / `data_correct` (P17, D14, DC49) |
| `exclusion.md` adds **E19. Other clear ineligibility**, reason `other: <label>` | User, 2026-11-24: reasons are open lists like every other list (decision 18). Worded "use rarely, if unsure keep" because a false exclusion is unrecoverable | New criterion; each use is logged to `other_labels.csv` |

v2's standalone `power_analysis.md` and `data_analysis.md` were deleted on
2026-11-24 (user decision; recoverable from git at `397a09f`), so the P and D
rules live only in `combined_analysis.md`. Their text was copied verbatim from
those files except D4. On v2 the runner refuses `--task power_analysis` and
`--task data_analysis`; the combined route is the only post-gate route.

The E3, E5, E17, P2/P17, and D3/D14 decisions are inherited from v1. Their
rationale and the earlier un-run version consolidation are recorded in
[`v1 doc.md`](../v1/v1%20doc.md) and the decision log; they are not repeated
here.

## Run and reporting state

No DC17 accuracy delta is reportable for v2. The current v1 whole-text results
remain the baseline and must not be pooled with v2. A configuration change is a
separate provenance stratum; a prompt-byte change also requires a version bump.

| Round | Date | Split | Task | n | Accuracy | Δ vs previous | `undecidable` | `wrong_text` | Parse retries |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| — | — | — | — | — | — | — | — | — | — |

## Expected misses

| Task | Papers | Rationale |
|---|---|---|
| data_analysis | `MQF2Y5AM` (Altinger) | Longitudinality alone does not make an analysis incorrect (DC49). |

The five stepped-wedge papers and Cattamanchi are in expert review and are not
scored. See `results/review/18_expert_review_dropped.csv`.

## Plateau check

| Task | Last two Δ | Plateaued? | Sonnet check run? | Sonnet accuracy |
|---|---|---|---|---|
| exclusion | — | no | no | — |
| power_analysis | — | no | no | — |
| data_analysis | — | no | no | — |
