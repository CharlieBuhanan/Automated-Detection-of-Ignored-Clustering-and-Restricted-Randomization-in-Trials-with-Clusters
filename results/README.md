# results/

Outputs, foldered by the pipeline stage that produced them. Every file here is **generated** —
rebuild it by re-running its script, never hand-edit it. The one exception is `review/`, where a
human's decisions are the content.

| folder | stage | rebuilt by |
|---|---|---|
| `01_corpus_build/` | Fetch → verify → extract → ledger | `01`, `02`, `05` |
| `02_ground_truth/` | Human labels merged and loaded | `07`, `04` |
| `03_figures/` | Diagrams for the manuscript | hand-drawn, exported |
| `04_classification/` | Promptbook loop and the batch runs | *(empty until the loop starts)* |
| `review/` | The human queue — spans every stage | various |

## 01_corpus_build/

| file | what it is |
|---|---|
| `identity_report.csv` | Every identity signal per paper (title/author/DOI scores, `title_pos`). The diagnosis file behind the manifest's `verdict`. |
| `extraction_report.csv` | Per-paper extraction outcome: method, character count, page count. |
| `exclusions.csv` | **The ledger.** One row per departed paper: stage, reason, evidence, `decided_by` (rule/human/model). Reconciles 2063 fetched → 1773 active. |
| `needs_manual_check.csv` | Papers flagged for a human by a rule rather than by review. |
| `unvalidated_set_summary.tex` | The Unlabelled Set's fetch summary: 2115 placements → 1494 unique. |
| `corpus_breakdown.tex` | Full corpus reconciliation table, both sets. |
| `corpus_disposition.tex` / `_prisma.tex` | Disposition of every paper; PRISMA-shaped variant for the manuscript. |
| `corpus_disposition_artifact.html` | Browser-readable version of the same. |

## 02_ground_truth/

| file | what it is |
|---|---|
| `ground_truth_disagreements.tex` | The 15 papers NCI and NHLBI both reviewed, and where they disagree. Binary keep/exclude agreement is 12/15. |

## 03_figures/

`pipeline_flowchart.{tex,drawio,pdf}` — the pipeline diagram. `.drawio` is the editable source.

## 04_classification/

Empty until the promptbook loop runs. Will hold `promptbook_accuracy_history.csv` (one row per
scoring round, with the promptbook's git commit) and `run_log.csv` (one row per batch run — model,
API or CLI, cost, duration, retry count; see PLAN.md's Batch run log).

## review/

The human queue. Numbered by the script that writes each file, not by date.

| file | what a human decides |
|---|---|
| `01_papers_to_review.csv` | PDFs whose identity failed verification. Worked in `03_review_mismatches.py`. |
| `02_removed_testing_duplicates.csv` | 207 US papers also present in the HLS. Rule-decided, logged. |
| `03_validation_internal_duplicates.csv` | 15 HLS pairs fetched from both NCI and NHLBI. |
| `04_papers_reviewed_results.csv` | Audit trail of every hand decision: who decided what, and why. |
| `05_label_match_review.csv` | **Open.** 6 institutional disagreements + 1 unresolved citation, held out of the labels until a human reads the paper. |
| `06_merged_validation_duplicates.csv` | Which duplicate merged into which. |
| `07_ground_truth_unjoined.csv` | Citations that could not be matched to a `paper_id`. Never guessed. |
| `09_nhlbi_unreviewed_dropped.csv` | 23 NHLBI papers cited but never judged. |
| `10_nonjudgeable_exclusions_dropped.csv` | 41 HLS papers excluded for a cross-paper reason the promptbook forbids (protocol paper, random drop). |
