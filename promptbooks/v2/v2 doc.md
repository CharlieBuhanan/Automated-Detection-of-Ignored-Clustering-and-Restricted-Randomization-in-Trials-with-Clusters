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
| `few_clusters_no_correction` tag recorded, but D13 unchanged (not decisive) | Deb Q2 said it makes data incorrect; confirmation pending (Deb.md 3b), and `Y7PRFE3Z` is labelled correct | Flip D13 in place if Deb confirms before the first run |

`power_analysis.md` and `data_analysis.md` are unchanged and are not used by the
combined route once step 4 switches it to `combined_analysis.md`.

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
