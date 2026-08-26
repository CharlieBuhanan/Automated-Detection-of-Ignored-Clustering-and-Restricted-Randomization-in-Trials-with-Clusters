# Automated Ignore

Classifies papers with Claude on three independent tasks — **exclusion**, **power_analysis**,
**data_analysis** — and scores that against human labels.

The corpus is gated, not classified wholesale: exclusion runs on all 1,287 study papers, and only
survivors are scored on power and data analysis. Promptbooks are built empirically
against the Human Labelled Set until accuracy plateaus.

[PLAN.md](research%20design/PLAN.md) — roadmap and schemas · [DESIGN_CHOICES.md](research%20design/DESIGN_CHOICES.md) — every decision, and what is still open ·
[CLAUDE.md](.claude/CLAUDE.md) — project rules ·
[Deb.md](research%20design/Deb.md) — open questions · [promptbooks/](promptbooks/) — the four codebooks

## Status

| | Count |
|---|---|
| Study papers to classify | 1,287 |
| Human Labelled Set PDFs fetched | 569 (232 NCI + 337 NHLBI) |
| Human Labelled Set papers active | 530 |
| …with one clean label | 523 |
| Papers extracted to text | 1,814 |

Corpus prep is complete. **Promptbook work is blocked** on 7 held-out papers — 6 NCI/NHLBI
disagreements and 1 unresolved citation, in `results/review/05_label_match_review.csv`. The
build/holdout split may only be assigned once, so it cannot be fixed on a partial label set.

## Order to run things

```
00_fetch_zotero.py           once per corpus change    safe to re-run
01_verify_identity.py        ONCE, already done        *** DO NOT RE-RUN ***
        |
        v
02_extract_pdfs.py  <---+    anytime                   safe to re-run
        |               |
        |  flags thin/unreadable/correction PDFs into
        |  results/review/01_papers_to_review.csv
        v               |
03_review_mismatches.py +    when that queue has undecided rows
        |                    (Replace or Drop clears that paper's cached text)
        v
07_build_ground_truth.py <-+ anytime, regenerates from source
        |                  |
        v                  |
09_drop_unreviewed_nhlbi.py+ when a source drops a citation   idempotent
        |
        v
04_load_ground_truth.py      anytime, regenerates from source
05_build_exclusions.py       anytime, regenerates from source
```

`08_tex_to_xlsx.py` is a standalone convenience, outside this chain.

**Why `01` must not be re-run.** Its `verdict` columns now hold hand-made decisions — 20
`MANUAL_REPLACED`, 4 `MANUAL_OK`, every `DROPPED` paper. A re-run overwrites them with automated
verdicts and silently returns dropped papers to the corpus. To re-check identity, restore the
manifest from git first, then replay `04_papers_reviewed_results.csv` on top.

Everything else repeats safely: `00` skips PDFs matching their recorded md5, `02` re-parses only
changed ones, `05` and `07` rebuild from scratch.

## Scripts

| script | what it does | state |
|---|---|---|
| `00_fetch_zotero.py` | Pulls Zotero into `data/raw_pdfs/<Set Name>/`; writes the manifest (tracked) and `zotero_meta.jsonl` (gitignored). | 1,287 US + 569 HLS |
| `01_verify_identity.py` | Checks each PDF really is the paper Zotero claims — first two pages vs. title, author, DOI. | 2,041 VERIFIED, 24 resolved by hand |
| `02_extract_pdfs.py` | Full text → `data/extracted_text/<id>.json`. Manifest-driven, so it only touches `VERIFIED` papers; a glob would extract the MISMATCH files still on disk. | 1,856 papers, PyMuPDF, no OCR |
| `03_review_mismatches.py` | tkinter GUI to triage flagged PDFs: No Issue / Replace / Drop / Skip. Replacements re-verify on the spot. | 24 decided — 20 replaced, 4 confirmed |
| `07_build_ground_truth.py` | Merges every institute's label file into `data/ground_truth.csv` as a wide union, keeping each source string in a `*_raw` column. | 569 rows, 567 joined; reproduces NCI's published 20/11/5/60 |
| `09_drop_unreviewed_nhlbi.py` | Drops NHLBI papers cited but never judged. Nothing deleted — files move to `data/removed_pdfs/`. Re-run `07` after. | 23 dropped; 553 → 530 |
| `04_load_ground_truth.py` | Loads the CSV into SQLite, collapsing source rows to one per paper. Agreeing NCI/NHLBI pairs merge; disagreeing ones are held out, never resolved by picking a side. | 523 loaded, 7 held out |
| `05_build_exclusions.py` | Every departed paper with `stage`, `reason`, `evidence`, `decided_by`. Rebuilt each run, never hand-edited. | reconciles 2,063 → 1,814 |
| `06_merge_validation_duplicates.py` | Collapses papers in both Human Labelled Set collections, so none is split across the holdout. Idempotent. | 15 pairs merged |
| `08_tex_to_xlsx.py` | tex → `.xlsx` for visual review, reusing `07`'s parser so the two cannot drift. | `crt_review_table_112.xlsx` |

## Library modules

| module | what it holds |
|---|---|
| `src/zotero_fetch.py` | Collection walking, download, md5 verification, manifest writing |
| `src/pdf_extract.py` | `extract_head_text()` for identity; `extract_and_cache()` for the PyMuPDF → pdfplumber → OCR ladder. Text only, no table grids — `research design/PLAN.md` step 2 has the measurements |
| `src/identity.py` | Normalization, DOI/title/author signals, verdict ladder. Pure functions, so re-checks reuse the same logic |
| `src/db.py` | SQLite: `validation_labels` (human) and `judgments` (model, append-only). `assign_split()` hashes `seed + paper_id`, runs once, refuses to re-run. Extracted text deliberately lives outside |
