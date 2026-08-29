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

## Script 19 — strip references from the cached text

Offline and free. No model call, no network, no subscription quota. Re-runnable.

- Read every `data/extracted_text/*.json`; never modify it (DC6)
- Find the LAST standalone references heading; decline if there is none, if it sits in the first 30% of the document, or if the cut would remove over 60%
- Splice back any appendix or supplement that followed the bibliography
- Leave a `[REFERENCES SECTION REMOVED]` marker so a trimmed paper does not read as an abstract (E2)
- Write the copy to `data/extracted_text_stripped/<paper_id>.json` with a `references_strip` audit record (source hash, ruleset, chars removed, reason)
- Skip files already produced from the same source by the same rules unless `--force`
- Report the character and token saving, every paper left whole and why, and both accounting gaps: sources with no copy, copies with no source
- `--check` reports all of the above and writes nothing

Measured 2026-08-28: 1747/1783 stripped, 21.6% of the corpus removed (~6.9M tokens).

## Script 22 — evaluate persisted judgments

Read-only. It never calls a model and never changes `data/review.db`.

- Select one task or all three, the build or holdout split, and optionally a promptbook version
- Read the latest persisted judgment per paper/task
- Keep missing, `undecidable`, `wrong_text`, and unlabelled rows visible
- Calculate the confusion matrix, accuracy, sensitivity, specificity, precision, F1, balanced accuracy, and Cohen's kappa
- Write a Markdown dashboard, summary CSV/JSON, and paper-level cases CSV
- Produce a read-only snapshot only: it does not append `promptbook_accuracy_history.csv` or make a DC17/G11 plateau claim
- Once request-level route/effort/run/prompt-hash provenance is migrated, require a homogeneous configuration before any explicit history append; label legacy-high/new-medium reuse as exploratory mixed configuration

## Script 23 — review table per checked round

Read-only. It never calls a model and never writes to `data/review.db`; output goes only to `results/04_classification/review_tables/`.

- Take the checked report for one task/round as the spine, so one table covers exactly one promptbook version
- Join the paper title, first author, year, journal and DOI from `data/zotero_manifest.csv`
- Join the human answer from `validation_labels` via `db.expected_decision` — the same mapping Script 22 scores against, so `outcome` here and a row in its `cases.csv` cannot disagree
- Classify each row as `true_positive` / `true_negative` / `false_positive` / `false_negative`, or name it `undecidable`, `wrong_text`, `failed` or `unlabelled` rather than folding it into the confusion matrix
- Sort errors first, most confident first: a confident error is the one worth reading
- `--all-rounds` builds every checked report into its own table, which is also how the two `power_analysis` round 1 reports are handled instead of refused as ambiguous
- `--html` also writes a self-contained page: filter chips by outcome, and each cited rule expanded to its full text from the promptbook the round actually ran under
- `--html <csv>` re-renders an existing review table with no database and no manifest; the CSV carries the task and promptbook version on every row
- Degrade rather than refuse when a legacy round has no `run_environment.json`: the table still builds, and the page says the promptbook is unrecorded instead of claiming the rule was not found
