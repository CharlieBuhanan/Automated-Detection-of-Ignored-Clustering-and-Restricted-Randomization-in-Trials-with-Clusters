# Ground truth sources — notes

What's in this folder and what was found while merging it. Everything here is a **read-only
source**. The merged output is `data/ground_truth.csv`, rebuilt by `scripts/07_build_ground_truth.py`.
A readable, unnormalized copy of the NHLBI table alone is `crt_review_table_112.xlsx`, built by
`scripts/08_tex_to_xlsx.py`.

## Files

| File | What it is |
|---|---|
| `GroundTruthDataNCI01.xlsx` | NCI labels. 232 rows, 5 columns, one sheet (`Combined`). |
| `crt_review_table_112.tex` | NHLBI papers taken to full extraction. A LaTeX `longtable`, 159 entries, 22 columns. |
| `NHLBI_exclusions_178.csv` | NHLBI papers rejected before extraction. 178 rows, all exclusions, with DOI and PMID. |
| `crt_review_table_112.xlsx` | The tex table, translated to a readable spreadsheet. |
| `crt_review_table_112.pdf` | The tex table, compiled. No extra information. |
| `NHLBI_Ignore03_v11_bundle/` | NHLBI analysis code and draft manuscript. Documentation, not data. |

**The NHLBI review is recorded in two files, not one.** A paper taken to full extraction got a
row in the tex table; a paper rejected earlier appears only in the exclusions CSV. The two are
disjoint and together cover all 337 NHLBI papers — neither alone does. `07_build_ground_truth.py`
checks the disjointness rather than assuming it, since a paper in both would be double-counted
and could carry contradictory labels.

**Inside the bundle:** `p0101_read_nhlbi.sas` is the column dictionary — its header comment
lists all 22 tex columns in order, which `07_build_ground_truth.py` copies rather than guesses.
`p0102`–`p0104` build downstream tables (Table 1, CMH tests, PRISMA diagram) and aren't needed
here. `references.bib` is **not** the review table's bibliography — it's the manuscript's
reference list and contains none of the 159 cite keys; the table actually cites
`Ignore03_NHLBI.bib`, which wasn't included. `NHLBI_Ignore03_v04.tex` is a draft manuscript,
useful for one thing: it hard-codes the published NCI 2×2 (20/11/5/60), which the merged CSV
reproduces exactly — the check that the NCI parse is faithful.

## Coverage

569 HLS PDFs were fetched in total. 530 are active in the corpus today; the rest left for
one of two reasons, both logged rather than silently removed:

| Left the corpus | Papers | Where |
|---|---|---|
| NHLBI, cited but never reviewed — will not be reviewed | 23 | `data/removed_pdfs/nhlbi_unreviewed/` |
| Correction notice (`JBUFJCLU`) | 1 | `data/removed_pdfs/replaced/` (via `03_review_mismatches.py`) |
| Folded into a duplicate-pair survivor | 15 | still active, just counted once (see below) |

Of the 530 active papers, **523 carry one clean label**. The other 7 are held for a human, not
silently dropped: 6 papers where NCI and NHLBI reviewed the same paper and disagreed, and 1 real
unresolved citation (`(Patterson et al., 2022a/2022b)`, discussed below). Both are logged in
`results/review/05_label_match_review.csv`.

**The 23 unreviewed NHLBI papers are dropped, not pending.** They were cited in the tex with
every field blank — candidates for full extraction that never got it. That review will not
resume, so `scripts/09_drop_unreviewed_nhlbi.py` moved them out: manifest verdict `DROPPED`
(`verdict_reason = NHLBI_UNREVIEWED`), PDF and cached extracted text both moved — never
deleted — to `data/removed_pdfs/nhlbi_unreviewed/` (extracted text nested one level further, in
`extracted_text/`). The full list, with the reason and timestamp, is
`results/review/09_nhlbi_unreviewed_dropped.csv`. They still appear in `data/ground_truth.csv`
as `labeled=0` rows — dropping is a corpus-membership decision, transcribing the source citation
is a separate one, and the row is the historical record that the citation existed.

## NCI columns (5)

`Citation` is an APA-style entry (`83. (Hershman, Bansal, Barlow, et al., 2023)`) — no DOI, no
key. `Reason excluded` blank means the paper was kept. `Power` and `Stats` are YES/NO.

**`Review Category` is dropped: it is a restatement of `Stats`.** Measured over all 96 NCI rows
that carry it, the letter agrees with `Stats` perfectly in both directions — every one of the 31
data-correct papers carries the same letter, and no data-incorrect paper does. The remaining
letters split the 65 incorrect papers three ways but not along the SAS `ignored_data_c` strata
(those split the same 65 papers 14/26/25), and no NHLBI paper carries a letter at all. It encodes
nothing `Stats` does not already say, so nothing reads it. The column is still transcribed to
`data/ground_truth.csv` and `validation_labels` as a raw record of the source file.

## NHLBI columns (22)

The two label sets overlap on only four fields (exclusion reason, power-correct, data-correct,
and a rough equivalent of severity). Everything else below is NHLBI-only, which is why the
merged CSV is a wide union with blanks rather than an intersection.

| # | Column | Meaning |
|---|---|---|
| 1 | `citation` | Author + `et al.`, e.g. `Abrahams-Gessel et al.` — short form only; year lives in the `\cite{}` key, not shown as its own field. |
| 2 | `exclude_reason` | Blank = kept. Filled = why dropped. When filled, every later column is blank — the paper never got the full extraction. |
| 3 | `n_trt` | Number of treatment arms. Almost always 2. |
| 4 | `n_levels` | Number of nested clustering levels (1 = individually randomized, up to 5). |
| 5 | `comment_levels` | Free text describing what those levels are, e.g. `patient within PCC within province`. |
| 6–9 | `n_outer`, `n_2nd`, `n_3rd`, `n_4th` | Cluster counts, outermost first. Free text, not always numeric — ranges, approximations, and `NR` all appear. |
| 10 | `unit_rand` | The physical unit randomized to treatment — clinic, school, physician. |
| 11 | `ind_samp_unit` | The independent sampling unit — sometimes equal to `unit_rand`, sometimes a level below it. |
| 12 | `restricted_rand` | Restricted-randomization scheme. Free text, 30+ distinct values (`none`, `stratified`, `yes, pair matching`, fully spelled-out schemes). |
| 13 | `icc` | Intraclass correlation coefficient(s). Free text — single values, ranges, per-subgroup breakdowns, or `missing`. |
| 14 | `n_long` | Number of repeated/longitudinal measures. |
| 15 | `stepped_wedge` | `yes`/`no`. |
| 16 | `data_done` | Data-analysis method the paper actually used. |
| 17 | `data_should` | Method the reviewer judged it should have used. |
| 18 | `data_correct` | `yes`/`no` verdict comparing 16 to 17. Occasionally hedged free text instead of a clean answer. |
| 19 | `data_comment` | Reviewer's free-text note. No equivalent exists for power analysis. |
| 20 | `power_done` | Power/sample-size method actually used. |
| 21 | `power_should` | Method that should have been used. |
| 22 | `power_correct` | `yes`/`no` verdict comparing 20 to 21. |

`crt_review_table_112.xlsx` adds two columns not in the source: `reviewed` (`no` when every field
2–22 is blank — cited but not yet judged, easy to misread otherwise) and `note` (the trailing
annotation on the `% Entry N` comment line; only entry 13 has one).

## NHLBI exclusions CSV columns (13)

`pmid`, `doi`, `citation_key`, `first_author`, `year`, `title`, `journal`, `volume`, `issue`,
`pages`, `all_authors` — standard bibliographic fields, all populated. `exclusion_reason` is one
of 12 category headings. `reason_source` records where the reason came from (identical on every
row: *Ignore03_NHLBI exclusion document, category headings*).

Only `exclusion_reason`, `citation_key`, `doi`, `pmid`, and `reason_source` are carried into
`ground_truth.csv`. The bibliographic columns are not — every one is already in
`data/zotero_meta.jsonl` keyed by the `paper_id` the join produces, and no other source in the
merged file carries them, so copying them would make the schema lopsided without adding anything
recoverable.

Its 12 reasons introduce four categories the tex table never used — `protocol_paper`,
`cohort_study`, `comment_or_letter`, `preprint` — and reuse the rest under different wording
(`Baseline analysis` for the tex's `baseline`, `Multiple trials from the same research group` for
`second study by same group, excluded randomly`). All 12 map cleanly; none fall through to
`other`. Note the last of those records the same category as the tex but not the *tie-break* —
the tex says the survivor was chosen randomly, this file does not say how.

## Things that would have gone wrong silently

- **14 tex rows have 21 fields, not 22** — a trailing `&` was never typed. All 14 are excluded
  papers with no data, so padding right is safe; an exact field count would have dropped them.
- **Hyphenated surnames.** 13 cite keys are `abrahams-gessel…`, `philis-tsimikas…`. Splitting on
  capital letters turns the second half of the name into a title word and the author match fails.
  The surname is the leading lowercase run, hyphens included.
- **Curly apostrophes.** NCI writes `O’Connor` (U+2019); Zotero holds `O'Connor` (U+0027).
  Unfolded, they reduce to `connor` and `oconnor` and never match.
- **Free text in yes/no columns.** Two NHLBI judgments read `yes (close enough)` and
  `no — uncertain how to do power for this study`. The SAS reader turns anything not exactly
  `yes`/`no` into missing, losing both. The merged CSV reads the leading word and keeps the
  reviewer's wording in `*_raw`, so NHLBI power-correct is 16, not the 15 SAS reports.
- **Exclusion vocabularies differ between institutes.** NCI's `secondary` = NHLBI's `secondary
  data analysis`; NCI's `random` = NHLBI's `second study by same group, excluded randomly`.
  Mapped in `EXCLUSION_VOCAB`, raw wording kept.
- **The two reviews didn't use identical criteria.** NHLBI excludes stepped-wedge designs
  (9 papers); NCI has no stepped-wedge column at all. Worth stating in the methods section
  before pooling the two sets.
- **LaTeX escapes survive in three fields** (`$\sim$`, `Hern\'andez-Galdamez`), and entry 158
  has a stray closing brace in its cite key.
- **Entry 13 is marked `EXCLUDED but data preserved`** — it carries an exclusion reason *and* a
  full extraction, including `data_correct = yes`. Treated as excluded; the data is kept.

## Joining to the corpus

567 of 569 rows resolve to a Zotero `paper_id`, including all 337 NHLBI rows:

| Rule | Rows |
|---|---|
| NCI first author + year unique in collection | 216 |
| NCI extra authors compared by position | 14 |
| NHLBI exclusions CSV, unique DOI | 178 |
| NHLBI cite-key author + year unique | 151 |
| NHLBI title words break a tie | 7 |
| NHLBI title only, corporate author | 1 |
| Unresolved → `results/review/07_ground_truth_unjoined.csv` | 2 |

The exclusions CSV is the only source that carries identifiers, so it joins exactly — all 178 on
DOI, with none needing the PMID fallback and no DOI ambiguous within the collection. The other
two sources print author and year and nothing else, which is why they need the fuzzy ladder.

The corporate-author rule exists for entry 69, whose first author is `ICU-RESUS and Eunice
Kennedy Shriver National Institute of Child Health` — no surname for the usual signal, so the
title carries the match alone. It only fires on a near-exact title (≥90) with no rival above 70;
entry 69 scores 93 against a runner-up of 59.

The two left over are a real ambiguity, not a parser failure — though only one real paper is at
stake. `(Patterson et al., 2022a)` and `(2022b)` point at `IT2B87LL` (the article) and `JBUFJCLU`
(`Correction to:` the same article) — and `JBUFJCLU` is already `DROPPED` from the manifest. APA
only adds the `a`/`b` suffix when two references share an author and year, so the suffix is the
labeller recording that *they* couldn't separate them either. The join still can't resolve it
automatically because it searches `zotero_meta.jsonl`, which still lists `JBUFJCLU` as a live
candidate — the manifest's `DROPPED` verdict was never propagated back to it. Low risk either
way: both label rows hold identical values (excluded, reason `random`, no Power/Stats/Category),
so no accuracy number depends on which is which.

Getting `Ignore03_NHLBI.bib` would make the NHLBI join exact rather than fuzzy: it carries DOIs.
Worth asking for.

## Fifteen papers, two reviews each

15 papers were fetched into both Zotero groups and independently reviewed by both institutes —
`06_merge_hls_duplicates.py` already collapsed their *manifest* rows to one paper_id
apiece (the NCI side), but the fetch's raw metadata (`zotero_meta.jsonl`) was never pruned to
match, so an NHLBI citation could still resolve to the retired paper_id. `07_build_ground_truth.py`
now remaps those 15 rows to the surviving paper_id (visible in the `paper_id_note` column), so
every row in `ground_truth.csv` points at a paper that actually has a PDF and extracted text.

That remap is what surfaces the real finding: **9 of the 15 pairs agree on every label; 6 do
not.** One disagreement is a complete flip — NCI calls both power and data analysis correct for
a paper NHLBI calls both incorrect for. `04_load_ground_truth.py` collapses the 9 agreeing pairs
to one `validation_labels` row automatically and holds out both sides of the 6 disagreements,
writing them to `results/review/05_label_match_review.csv` with each institute's answer spelled
out. Neither side is guessed at — a paper held out this way gets no label at all until a human
reads it and decides, the same treatment as an unresolved citation.
