# Script docs

## Script 01 — logical steps

- Read manifest, keep fetched
- Extract first two pages
- Score DOI, title, authors
- Apply ordered verdict ladder
- Optionally retry other attachments
- Write verdicts to manifest
- Write per-signal report

## Script 02 — logical steps

- Read manifest, keep VERIFIED
- Skip rows missing PDFs
- Hash PDF, check cache
- Re-extract if md5 changed
- Flag failures, corrections, thin text
- Append flagged to review queue
- Write extraction report

## Script 03 — logical steps

- Load queue, drop resolved
- Ask scope, resume position
- Show finding, open sources
- Record decision per paper
- Re-verify replaced PDFs immediately
- Append decision to log
- Update manifest verdict
- Clear stale cached text

## Script 13 — logical steps

Read-only. Asks whether the HLS has stopped shrinking, so the DC42 restore is safe.

- Load manifest, labels, review logs
- C1-C2: label parity, verdict closure
- C3-C5: queue drained, text present and clean
- C6-C8: label categories and vocabulary
- C9-C12: duplicates, disagreements, unjoined citations
- C13-C14: split unassigned, ledger agrees
- Preview DC42 restore candidates, restore nothing

## Script 14 — logical steps

Read-only. The US has no labels, so every check asks about *inputs* instead.

- Load manifest, cache, review logs
- U1-U2: cached text present, verdicts resolved
- U3-U5: queue drained, no bad parse, no correction notice
- U6-U7: no duplicate inside the US, none shared with the HLS
- U8-U9: removals still justified, restores recorded (DC42)
- U10-U12: ledger agrees, PDFs accounted for, count matches the published figure

## Script 15 — logical steps

DC42: US papers whose HLS twin was later dropped are no longer duplicates.

- Find removed US papers whose twin lost its label
- Skip any already back in the manifest
- Fetch those item keys directly, no collection walk
- Download PDFs, merge manifest + meta rows
- Compare fresh md5 against the archived copy
- Log what came back and why

## Script 16 — logical steps

Replays human decisions that `01_verify_identity.py` overwrites (DC44).

- Read every drop log and the manual review log
- Sort all decisions by timestamp, newest wins
- Skip rows already matching the manifest
- Write verdict + verdict_reason back
- Idempotent; run after every identity re-run

## Script 17 — logical steps

Cuts the build split into fixed rounds so two rounds are comparable (DC47).

- Read build-split papers from validation_labels
- Split into survivor / excluded strata
- Order each stratum by sha256(seed + paper_id)
- Interleave strata so every 50-window holds both in proportion
- Cut exclusion into 7 rounds, power/data into 3 each
- Write results/04_classification/build_rounds.csv

## Script 22 — evaluate persisted judgments

Read-only. It never calls a model and never changes `data/review.db`.

- Select one task or all three, the build or holdout split, and optionally a promptbook version
- Read the latest persisted judgment per paper/task
- Keep missing, `undecidable`, `wrong_text`, and unlabelled rows visible
- Calculate the confusion matrix, accuracy, sensitivity, specificity, precision, F1, balanced accuracy, and Cohen's kappa
- Write a Markdown dashboard, summary CSV/JSON, and paper-level cases CSV
