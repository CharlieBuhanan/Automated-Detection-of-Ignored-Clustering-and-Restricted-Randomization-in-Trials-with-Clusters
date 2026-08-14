# Ground truth sources — notes

What is in this folder, what each file means, and what was found while merging them.
Everything here is a **read-only source**. The merged output is `data/ground_truth.csv`,
rebuilt by `scripts/07_build_ground_truth.py`.

## Files

| File | What it is |
|---|---|
| `GroundTruthDataNCI01.xlsx` | NCI labels. 232 rows, 5 columns, one sheet (`Combined`). |
| `crt_review_table_112.tex` | NHLBI labels. A LaTeX `longtable`, 159 entries, 22 columns. |
| `crt_review_table_112.pdf` | The same table, compiled. No extra information. |
| `NHLBI_Ignore03_v11_bundle/` | NHLBI analysis code and draft manuscript. Documentation, not data. |

### Inside the bundle

- `p0101_read_nhlbi.sas` — **the column dictionary.** Its header comment lists all 22 tex
  columns in order; `scripts/07_build_ground_truth.py` copies that list rather than guessing.
- `p0102`–`p0104` — Table 1, the CMH tests, and the PRISMA diagram. Downstream analysis only.
- `README.txt` — folder layout and run order for the SAS programs.
- `references.bib` — **not the bibliography for the review table.** It is the manuscript's
  reference list (1,137 entries) and contains **none** of the 159 cite keys. The table cites
  `Ignore03_NHLBI.bib`, which was not included in the bundle.
- `NHLBI_Ignore03_v04.tex` — draft manuscript, mostly outline placeholders. Useful for one
  thing: it hard-codes the published NCI 2×2 (20 / 11 / 5 / 60), which the merged CSV
  reproduces exactly. That is the check that the NCI parse is faithful.

## Coverage — the important gap

| Set | PDFs on disk | Rows in source | Actually labeled |
|---|---|---|---|
| NCI | 232 | 232 | **232** |
| NHLBI | 337 | 159 | **136** |
| Total | 569 | 391 | **368** |

NCI is complete and one-to-one with its PDFs. **NHLBI is not.** 178 of the 337 papers have no
table row at all, and 23 more are cited but left entirely blank — unreviewed, not "reviewed and
kept". That is 201 NHLBI papers with no human answer.

The 159 are **not** the first 159 alphabetically: they run Abdullahi → Yuan and span every year
2018–2025 at roughly 47% each. Coverage is uneven by letter (H is 11/14, T is 3/16), so it is
neither a prefix nor a clean random sample — most likely a review in progress, worked in
batches. The Zotero collection is named `Locked_26_01_08_337`, so 337 is the intended target.

**Open question for the data owner:** are further `crt_review_table_NNN.tex` versions coming?

## Column meanings

**NCI (5 columns).** `Citation` is an APA-style reference-list entry (`83. (Hershman, Bansal,
Barlow, et al., 2023)`) — no DOI, no key. `Reason excluded` blank means the paper was kept.
`Power` and `Stats` are YES/NO. `Review Category` is A/B/C/D.

**NHLBI (22 columns).** Column 1 is a citation, columns 3–15 are the design extraction (arms,
levels, cluster counts, unit of randomization, ICC, repeated measures, stepped wedge), and
columns 16–22 are the judgments: what each analysis *did*, what it *should have done*, whether
it was correct, plus a free-text comment on the data analysis.

The two sets overlap on only four fields. Everything else is NHLBI-only, which is why the
merged CSV is a wide union with blanks rather than an intersection.

### Review Category A/B/C/D — partly decoded, not documented

`A` is **data analysis correct**: all 31 `A` rows have `Stats = YES`, and no other category
does. `B` (19), `C` (33), and `D` (13) are all `Stats = NO`, so they are three flavors of
incorrect.

They are **not** the SAS `ignored_data_c` strata. Those split the 65 incorrect papers
14 / 26 / 25 (ignored clustering / ignored RR only / ignored both); B/C/D split them 19 / 33 / 13.
So B/C/D encode something else — most likely severity tiers. **Ask Dr. Glueck.** Until then the
value is carried through verbatim and nothing downstream interprets it.

Note also that `db.expected_decision()` currently returns this raw letter as the expected answer
for the `inclusion` task, where the model returns yes/no. Those can never agree; it needs a
mapping once the letters are defined.

## Things that would have gone wrong silently

- **14 tex rows have 21 fields, not 22** — a trailing `&` was never typed. All 14 are excluded
  papers with no data, so padding right is safe. An exact field count would have dropped them.
- **Hyphenated surnames.** 13 of the 159 cite keys are `abrahams-gessel…`, `philis-tsimikas…`.
  Splitting the key on capital letters turns the second half of the name into a title word and
  the author match fails. The surname is the leading lowercase run, hyphens included.
- **Curly apostrophes.** The NCI sheet writes `O’Connor` (U+2019); Zotero holds `O'Connor`
  (U+0027). Unfolded, they reduce to `connor` and `oconnor` and never match.
- **Free text in yes/no columns.** Two NHLBI judgments read `yes (close enough)` and
  `no — uncertain how to do power for this study`. The SAS reader converts anything that is not
  exactly `yes`/`no` to **missing**, losing both. The merged CSV reads the leading word and keeps
  the reviewer's wording in `*_raw`, so NHLBI power-correct is 16, not the 15 SAS reports.
- **`restricted_rand` is not a yes/no column.** It holds 30+ distinct free-text descriptions
  (`yes, stratified by department`, `constrained`, `none`, `unclear`). Normalized to yes/no/unclear
  with the description preserved.
- **Exclusion vocabularies differ.** NCI wrote `secondary`, NHLBI wrote `secondary data analysis`
  and `secondary analysis` for the same thing; NCI's `random` is NHLBI's `second study by same
  group, excluded randomly`. Mapped in `EXCLUSION_VOCAB`, raw wording kept.
- **The two reviews did not use identical criteria.** NHLBI excludes stepped-wedge designs
  (9 papers) and NCI does not — NCI has no stepped-wedge column at all. Worth stating in the
  methods section before pooling the two sets.
- **LaTeX escapes survive in three fields** (`$\sim$`, `Hern\'andez-Galdamez`), and entry 158 has
  a stray closing brace in its cite key.
- **Entry 13 is marked `EXCLUDED but data preserved`** — it carries an exclusion reason *and* a
  full extraction, including `data_correct = yes`. It is treated as excluded; the data is kept.

## Joining to the corpus

389 of 391 rows resolve to a Zotero `paper_id`, including all 159 NHLBI rows:

| Rule | Rows |
|---|---|
| NCI first author + year unique in collection | 216 |
| NCI extra authors compared by position | 14 |
| NHLBI cite-key author + year unique | 151 |
| NHLBI title words break a tie | 7 |
| NHLBI title only, corporate author | 1 |
| Unresolved → `results/review/07_ground_truth_unjoined.csv` | 2 |

The corporate-author rule exists for entry 69, whose first author is
`ICU-RESUS and Eunice Kennedy Shriver National Institute of Child Health`. A consortium has no
surname, so the author signal is unavailable and the title has to carry the match alone. It only
fires on a near-exact title (≥90) with no rival above 70; entry 69 scores 93 against a runner-up
of 59.

The two left over are a real ambiguity, not a parser failure. `(Patterson et al., 2022a)` and
`(2022b)` point at `IT2B87LL` (the article) and `JBUFJCLU` (`Correction to:` the same article).
APA adds the `a`/`b` suffix exactly when two references share an author and year, so the suffix
is the labeller recording that *they* could not separate them either — there is nothing in the
citation to decide on.

It carries little risk, though: **both rows hold identical labels** — excluded, reason `random`
("second study by same group, excluded randomly"), with no Power, Stats, or Review Category. The
expected decision is the same either way, so no accuracy number depends on the answer.

What it does imply is that the reviewers wrote a row for the article **and** a row for its
correction notice. When `JBUFJCLU` is dropped as a correction notice (queued in PLAN.md), the
surviving row should join to `IT2B87LL` and the other should be **discarded** — pointing both at
the survivor would enter one paper into the denominator twice.

Getting `Ignore03_NHLBI.bib` would make the NHLBI join exact rather than fuzzy: it carries DOIs.
Worth asking for.
