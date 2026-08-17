# Cluster-Paper Review

Classifies scientific papers with Claude across four independent tasks — **exclusion**,
**inclusion**, **power_analysis**, and **data_analysis** — and measures that classification
against human labels.

The corpus is gated rather than classified wholesale: exclusion and inclusion run on all 1,287
study papers first, and only survivors are scored on power and data analysis. Rubrics are built
empirically, by iterating against a human-labeled validation set until accuracy plateaus.

See [PLAN.md](PLAN.md) for the full roadmap, schemas, and the reasoning behind each design
decision. Project rules are in [.claude/CLAUDE.md](.claude/CLAUDE.md).

## Status

| | Count |
|---|---|
| Study papers to classify | 1,287 |
| Validation PDFs fetched | 569 (232 NCI + 337 NHLBI) |
| Validation papers active | 530 — 23 NHLBI papers dropped, cited but never reviewed |
| Validation papers with one clean label | 523 |
| Papers extracted to text | 1,814 |

Corpus preparation is complete. **Rubric work is blocked** on 7 held-out papers — 6 where NCI and
NHLBI disagreed, 1 unresolved citation — read `results/review/05_label_match_review.csv`. The
build/holdout split cannot be fixed on a partial label set, and it may only be assigned once;
`--assign-split` now enforces this on its own.

## Order to run things

Steps 2 and 3 loop until the review queue is empty; everything else is a straight line.

```
00_fetch_zotero.py        once per corpus change      safe to re-run
01_verify_identity.py     ONCE, already done          *** DO NOT RE-RUN ***
        |
        v
02_extract_pdfs.py        anytime                     safe to re-run
        |
        |  flags anything thin, unreadable, or a correction notice
        |  into results/review/01_papers_to_review.csv
        v
03_review_mismatches.py   whenever that queue has undecided rows
        |
        |  Replace or Drop clears that paper's cached text
        |
        +---> back to 02, which re-extracts only what changed
        v
07_build_ground_truth.py  anytime, regenerates from source    safe to re-run
        |
        |  09 reads this to know which citations are permanently unreviewed
        v
09_drop_unreviewed_nhlbi.py  as needed, when a source drops a citation   idempotent
        |
        +---> back to 07, so its coverage numbers reflect the smaller active corpus
        v
04_load_ground_truth.py   anytime, regenerates from source    safe to re-run
05_build_exclusions.py    anytime, regenerates from source    safe to re-run
```

`08_tex_to_xlsx.py` is a standalone convenience (tex → readable spreadsheet) and doesn't sit in
this chain.

**Why `01` must not be re-run.** It writes `verdict` and `verdict_reason` for every paper it
checks, and those columns now hold hand-made decisions — 20 `MANUAL_REPLACED`, 4 `MANUAL_OK`,
and every `DROPPED` paper. A re-run would overwrite all of them with fresh automated verdicts,
silently returning dropped papers to the corpus. If identity genuinely needs re-checking,
restore the manifest from git first and replay `04_papers_reviewed_results.csv` on top.

Everything else is safe to repeat: `00` skips papers whose PDF still matches its recorded md5,
`02` re-parses only papers whose PDF md5 changed, and `05` and `07` rebuild their output from
scratch each time.

## Scripts

**`00_fetch_zotero.py`** — pulls the corpus from Zotero into `data/raw_pdfs/<set>/`, writing
`data/zotero_manifest.csv` (a scannable summary, tracked in git) and `data/zotero_meta.jsonl`
(full per-paper metadata, gitignored). `--list-warnings` prints every multi-attachment warning
on file, across all sets and past runs; the end-of-run summary covers only that run.
*Complete: 1,287 `testing` papers (1,494 fetched, 207 removed as cross-set duplicates) and 569
`validation`.*

**`01_verify_identity.py`** — confirms each PDF really is the paper Zotero claims. Reads the
first two pages, compares title, first author, and DOI against the Zotero metadata, and assigns
`VERIFIED` / `WEAK` / `MISMATCH` / `PDF_UNREADABLE` into the manifest plus a per-signal report
in `results/identity_report.csv`. `--retry-attachments` re-downloads a record's other PDFs and
swaps in one that verifies.
*First pass: 2,041 VERIFIED (1,989 via DOI, 52 via title and author), 3 WEAK, 18 MISMATCH,
1 unreadable. The 24 non-VERIFIED were resolved by hand in `03`.*

**`02_extract_pdfs.py`** — full-text extraction, cached to `data/extracted_text/<paper_id>.json`.
Driven off the manifest rather than a directory listing, so it only ever touches `VERIFIED`
papers — a glob would extract the MISMATCH files still sitting on disk. Re-runs read the cache
and re-parse nothing unless `--overwrite`.
*Complete: all 1,856 papers extracted by PyMuPDF in 60 seconds, no OCR needed, ~100M characters.
Per-paper detail in `results/extraction_report.csv`.*

**`03_review_mismatches.py`** — a desktop GUI (tkinter, no extra install) for triaging flagged
PDFs one at a time. Opens the PDF, DOI, PubMed entry, and Zotero record, then offers **No
Issue** / **Replace PDF…** / **Drop** / **Skip**. A replacement is re-verified on the spot.
Decisions are appended to `results/review/04_papers_reviewed_results.csv` and written through to
the manifest. Saves on every click and resumes where you left off.
*Complete: all 24 flagged papers decided — 20 PDFs replaced, 4 confirmed correct.*

**`07_build_ground_truth.py`** — merges every institute's label file into `data/ground_truth.csv`.
The sources arrived in different formats holding different fields (NCI: a 5-column spreadsheet;
NHLBI: a 22-column LaTeX table plus a 13-column exclusions CSV with DOI/PMID), so the output is a
wide union — one row per source citation, one column per distinct source field, every source
string preserved in a `*_raw` column beside its normalized form. Also resolves each row to a
Zotero `paper_id`, remapping the 15 NCI/NHLBI duplicate-pair papers to whichever paper_id
`06_merge_validation_duplicates.py` kept active. `--report` prints the reconciliation without
writing.
*569 rows, 567 joined. The NCI 2×2 reproduces the published 20/11/5/60 exactly. Sources and
their quirks are documented in [Ground Truth Raw/NOTES.md](Ground%20Truth%20Raw/NOTES.md).*

**`09_drop_unreviewed_nhlbi.py`** — drops NHLBI papers cited in the review table but never judged,
and confirmed to stay that way. Source is `data/ground_truth.csv`, filtered to
`source_institute == "NHLBI" and labeled == "0"`, so a future `crt_review_table_NNN.tex` with the
same pattern is picked up without editing this script. Nothing is deleted: the PDF and its cached
extracted text both move to `data/removed_pdfs/nhlbi_unreviewed/`, and the manifest verdict
becomes `DROPPED` / `NHLBI_UNREVIEWED` — a code distinct from `03`'s `MANUAL_DROPPED` so
`05_build_exclusions.py` can describe the two reasons separately rather than call this "dropped
during hand review", which it was not. `--dry-run` reports without writing. Re-run `07` afterward
so its coverage numbers reflect the smaller active corpus.
*23 papers dropped; active validation corpus 553 → 530.*

**`04_load_ground_truth.py`** — loads `data/ground_truth.csv` into SQLite's `validation_labels`
table (one row per paper; `07` already did the harder job of joining citations to paper_ids).
Its own job is collapsing multiple source rows down to one: 15 papers were reviewed by both NCI
and NHLBI independently, and where the two agree they're merged automatically, but where they
disagree — 6 pairs, including one where NCI calls a paper's analyses correct and NHLBI calls the
same paper's analyses incorrect — both sides are held out and written to
`results/review/05_label_match_review.csv` for a human, never resolved by picking one. The
exclusion gate is enforced explicitly here too: any excluded row has power/stats/category forced
blank regardless of what the source data says. `--assign-split` now refuses to run while any
active validation paper still lacks a label (`--allow-incomplete` overrides deliberately, since
the split may only be fixed once). `--dry-run` reports without writing.
*523 of 530 active validation papers loaded; 7 held out (6 institutional disagreements, 1 real
unresolved citation).*

**`08_tex_to_xlsx.py`** — direct, unnormalized translation of the newest
`crt_review_table_NNN.tex` into a readable `.xlsx` for visual review, reusing `07`'s own tex
parser so the two cannot drift apart. Adds two columns the source lacks: `reviewed` (blank rows
are unmistakably flagged, not silently misread as "reviewed, nothing to report") and `note`.
*Output: `Ground Truth Raw/crt_review_table_112.xlsx`.*

**`05_build_exclusions.py`** — consolidates every paper that left the corpus into
`results/exclusions.csv`, one row per departed paper with `stage`, `reason`, `evidence`, and
`decided_by` (rule / human / model). Rebuilt from source every run, never hand-edited. Prints a
reconciliation from papers fetched down to the active corpus and warns if the numbers do not
balance. `--check` reports without writing. The methods section is written from this file.

**`06_merge_validation_duplicates.py`** — collapses papers that appear in both validation
collections into a single row, so no paper is double-counted or split across the holdout.
Idempotent; skips pairs already merged.

## Library modules

**`src/zotero_fetch.py`** — Zotero collection walking, download, md5 verification, and manifest
writing.

**`src/pdf_extract.py`** — PDF to text. `extract_head_text()` reads the first two pages for
identity checks; `extract_and_cache()` runs the full PyMuPDF → pdfplumber → OCR ladder and
caches the result. Text only, no table grids — see PLAN.md step 2 for the measurements behind
that choice.

**`src/identity.py`** — the identity rules: text normalization, DOI/title/author signals, and
the verdict ladder. Pure functions with no I/O, so classification-time re-checks reuse the same
logic.

**`src/db.py`** — SQLite (`data/review.db`), holding `validation_labels` (the human answers) and
`judgments` (what the model said — one row per judgment, append-only, keyed
`UNIQUE(paper_id, task, judgment_index)`). `assign_split()` fixes the build/holdout split once
by hashing `seed + paper_id`, and refuses to re-run. Extracted text is deliberately not stored
here.
