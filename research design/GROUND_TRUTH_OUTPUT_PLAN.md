# Plan: model output in ground-truth format

**Status:** Steps 1-3 built 2026-11-24 (field dictionary, schemas, v2 promptbooks); steps 4-7 not started.
**Artifact:** https://claude.ai/artifact/QWtopzdiZFmfwPqZMNba4K
**Schema page (for Deb):** https://claude.ai/artifact/VBmQr3SP4Zjzn8EnerxzYT

## Goal

Produce one CSV of model answers with the same 43 columns (same names, same order) as
`data/ground_truth.csv`, so model and human answers can be compared column by column.
Model: Claude Sonnet via UF NaviGator (DC59), medium effort.

## Decisions

**Which papers get a row**

1. One row per paper for the **477 active HLS papers**. The **77 dropped HLS papers** go to a
   separate audit file. Read these counts from the frozen manifest; stop with an error if they change.
2. Papers labelled by both NCI and NHLBI whose human answers still conflict are **skipped for now**
   (logged with a reason). Once the humans settle them, run them through the same pipeline. Never more
   than one row per paper.

**What the model is asked**

3. Each call answers only its own task. The exclusion call says nothing about power or data; the
   full 43-column row is assembled afterward.
4. Exclusion stays its own call and now also returns a standard `exclusion_reason`.
5. All **176 papers the humans kept** get the detailed power/data/design call, even if the model
   wrongly excluded them. This is an evaluation-only exception, so one gate mistake doesn't hide a
   paper's other columns. It is logged in the run record. Papers that don't get this call have
   `null` in every post-gate column.
6. Longitudinal measures (`n_long`) are recorded but don't affect power or data correctness (DC49).

**What the model returns**

7. The model picks values from fixed lists; our code turns them into the old CSV text. The full
   structured answer is saved too, because the CSV loses detail (e.g. several ICCs at different levels).
8. Missing information has three separate values, never confused with 0, "no", or blank:
   - `null`: doesn't apply, or wasn't asked
   - `not_reported`: the paper was checked and doesn't say
   - `unclear`: the paper says something contradictory or unreadable
9. The model never guesses source/provenance fields. Our code fills those.
10. `review_category` and `review_category_raw` stay blank. They're NCI-only, only `A` has a known
    meaning, and they repeat `data_correct`.
11. `labeled` = 1 when the model answered that paper. (In the human file it means a person reviewed it.)
12. Exactly one main data method per paper. `power_done` is **not** a method pick: it records what
    the power calculation accounted for (see Allowed values). No power calculation at all is
    `reported: no`, exported as `Not reported`.
18. **Every list is a starting point, not a closed set** (Deb, 2026-11-09). Lists come from 88 reviewed
    papers and will miss methods in larger sets. The model may answer `other` + a short label; code
    logs every new label, and labels that recur get promoted into the list in the next promptbook
    version (pattern rule: several papers, never one).

**How it's scored**

13. Only 88 of the 176 survivors (the NHLBI ones) have detailed human answers. Run all 176, but score
    only where a human answer exists; a blank human answer is not counted as wrong. If Deb and Keith
    label the rest, score those too, without re-running the model.
14. Human `data_should` / `power_should` notes are shorthand, not complete lists. A correct extra
    requirement from the model is not a disagreement.
15. Cluster counts must match **exactly**. `NR` matches only `NR`.
16. Free-text fields: score the structured parts automatically; a person spot-checks a sample of the
    text. No model-as-judge.
17. No Opus second pass for now. Revisit after checking how well Sonnet's confidence tracks accuracy.

## Deb's review (2026-11-09)

- Exclusion and data analysis: approved as drafted.
- **Added** `cluster_fixed_effects` data method and `few_clusters_no_correction` comment tag.
- Lists are incomplete by design → decision 18 (open lists).
- `power_done` draft list was flawed → rebuilt (below).

**Why the old `power_done` list was wrong.** It mixed three kinds of answer into one pick:
inputs (`icc_or_design_effect`, `coefficient_of_variation`, `between_cluster_variance` are numbers a
formula takes in, used by nearly every CRT, and the ICC already has its own column), timing
(`post_hoc`), and a judgment (`individual_level` = clustering ignored). Humans wrote what the power
calc *accounted for*: 73 of 88 answers mention clustering, ~8 name a method, 0 mention variance or CV.

## Deb's answers (2026-11-09)

Open follow-ups are tracked in [Deb.md](Deb.md) items 2-3; the schema page is updated to match.

- **Q1. Few clusters = a GEE with 40 or fewer clusters** needs a small-sample bias correction.
  Total vs. per arm not stated; count **total randomized clusters** until told otherwise (Deb.md 3a).
- **Q2. "Yes."** `few_clusters_no_correction` = GEE with ≤40 clusters and no bias correction, and it
  makes `data_correct` "no". This departs from Ignore02 rule 6, and `Y7PRFE3Z` (Olson 2025, 22
  clusters, uncorrected GEE) is marked correct, so confirmation is pending (Deb.md 3b).
- **Q3. Still open:** does the tag cover mixed models without a df adjustment, or only GEE? (Deb.md 3c)
- **Q4. Rebuilt `power_done` approved**, except **longitudinality has no `unclear` option**
  (Allowed values updated).
- **Q5. All levels:** every correlated level must be accounted for, not only the randomized unit.
- **Q6. Shorthand:** `*_should` columns are shorthand (decision 14 stands). Deb and Keith may
  expand them later.
- **Q7. Yes:** a planned-only analysis can get `data_correct` = yes.
- **Q8. `n_levels` = levels of clustering above the individual** (units in `comment_levels` − 1).
  The 16 two-unit rows coded 2 and 17 three-unit rows coded 3 are wrong, plus 4 more
  (`TT7PIVLD`, `TEXLFQSL`, `QMLU4TM8`, `3B8K39D8`); all listed at the end of Deb.md. Score the human
  side as units − 1 from `comment_levels`; never edit the human file (asking Deb and Keith, Deb.md item 2).

**Fixed 2026-11-09 (no Deb needed):** `exclusion_reason` rebuilt from the v1 E-numbers (dropped
`protocol_paper`, added E2/E4). `comment_levels` units gained patient / participant / student.

**Open on our side:** decisions 1, 5 and 13 send all 477 HLS papers (and all 176 kept) through the
model, which includes holdout papers. That breaks "holdout touched once, at the end". Proposed:
2-paper smoke test → 50-paper build round → full build split; holdout last.

## Where each column comes from

| Source | # | Columns |
|---|---:|---|
| Our code (corpus facts) | 13 | `paper_id`, `paper_id_note`, `source_institute`, `source_file`, `source_row`, `citation_raw`, `cite_key`, `matched_by`, `match_score`, `source_note`, `source_doi`, `source_pmid`, `reason_source` |
| Model | 20 | `excluded`, `exclusion_reason`, `power_correct`, `data_correct`, `n_trt`, `n_levels`, `comment_levels`, `n_outer`, `n_2nd`, `n_3rd`, `n_4th`, `unit_rand`, `ind_samp_unit`, `restricted_rand_raw`, `icc`, `n_long`, `stepped_wedge_raw`, `data_done`, `data_comment`, `power_done` |
| Worked out from model answers | 8 | `labeled`; `restricted_rand` and `stepped_wedge` (yes/no/unclear); `exclusion_reason_raw`, `power_correct_raw`, `data_correct_raw` (the model's text before standardizing); `data_should`, `power_should` (from `correlated_units`, restriction status, and `n_long`; changed 2026-11-24 so the model never states the same fact three times) |
| Left blank | 2 | `review_category`, `review_category_raw` |

Reasoning, cited rule, and confidence are kept alongside, outside the CSV. Output goes in
`results/04_classification/`. Human answers never go into a model prompt.

## Allowed values (draft, pending supervisor review)

| Field | Allowed values |
|---|---|
| `excluded` | yes, no, undecidable (only when the text is missing or unreadable). Exported as 1 / 0 |
| `exclusion_reason` | Model returns the v1 criterion ID (DC45); export shows the readable name: E1 preprint, E2 methodology_journal, E3 stepped_wedge_design, E4 secondary_in_title, E5 secondary_analysis, E6 baseline_only, E7 implementation_study, E8 methods_paper, E9 not_randomized, E10 not_group_randomized, E11 qualitative_study, E13 pilot_study, E14 cohort_study, E15 review_article, E16 comment_or_letter. Blank when kept. No protocol_paper (E12 is not a criterion); `duplicate_group_random_drop` exists only in the human file (E17) |
| `n_trt`, `n_levels`, `n_long` | whole number |
| `n_outer` … `n_4th` | exact, approximate, range, per parent unit, `not_reported`, `unclear`. Exported as e.g. `10`, `~20/school`, `5-8`, `NR` |
| `comment_levels` | units listed inner to outer, e.g. `patient within physician within clinic`. Unit names are lowercase singular: clinic, school, classroom, practice, hospital, ward, physician, nursing_home, village, community, household, family, worksite, site, or `other` + the paper's wording |
| `unit_rand`, `ind_samp_unit` | one unit from `comment_levels` |
| Restricted randomization | any of: pair_matched, matched_sets, stratified, blocked, constrained, minimization. Otherwise: none, not_reported, unclear |
| `icc` | exact, range, multiple (each with its level or group), not_reported, unclear |
| Stepped wedge | yes, no, unclear, not_reported |
| Data method | one of: mixed_effects, gee, cluster_level, cluster_robust_se, permutation, bayesian_hierarchical, cluster_fixed_effects, individual_level, `other: <label>`, not_reported. Plus: levels modeled, and whether clustering / restricted randomization / longitudinality were handled or ignored |
| `power_done` | **reported**: yes / no. **clustering**: all_levels / some_levels (+ which units) / ignored / unclear. **restricted_rand**: accounted / ignored / not_applicable / unclear. **longitudinality**: accounted / ignored / not_applicable (no `unclear`, Q4). **method**: formula / simulation / `other: <label>` / not_described (+ optional source note, e.g. Donner & Klar). **timing**: before_trial / post_hoc / not_stated. Exported like `Simulation accounting for clustering at clinic, not restricted rand.` |
| `data_should`, `power_should` | the required factors and levels (structured, not prose) |
| `power_correct`, `data_correct` | yes, no, undecidable, each with reasoning, cited rule, and confidence |
| `data_comment` | tags: unclear_reporting, missing_method, wrong_level, restriction_ignored, longitudinality_ignored, label_inconsistency, few_clusters_no_correction, `other: <label>`. Plus a short note |

## Checklist

- [x] Draft schema and allowed values
- [x] Deb review: exclusion + data approved; two values added; lists made open
- [x] Rebuild `power_done` as "what it accounted for" (schema page updated)
- [x] Deb answers Q1-Q8 (2026-11-09); Q3 and three follow-ups still open in Deb.md items 2-3
- [ ] Code the 88 human `power_done` strings into the same parts (clustering / restricted / longitudinal / method), person-checked, so scoring compares like with like
- [x] Field dictionary file (step 1): `data/field_dictionary.csv`, built by `scripts/24_build_field_dictionary.py`
- [x] Schemas in `src/schemas.py`, incl. `other: <label>` handling (step 2): `ExclusionWithReason`, `FullAnalysis`; tests in `ReadingRoom/tests/test_o_full_analysis_schema.py`
- [x] Promptbook: `combined_analysis.md` + exclusion reason, lists framed as starting points (step 3): in place in un-run `v2` (see `v2 doc.md`)
- [ ] Pipeline + new-label log (step 4)
- [ ] 43-column export and per-column scoring (step 5)
- [ ] Offline tests → 2-paper paid test (user runs) → calibration → frozen cost estimate (step 6)
- [ ] Docs (step 7)

## Build steps (after approval)

1. **Field dictionary.** One machine-readable file defining every column: type, allowed values,
   source, which task fills it, and how it's scored. Built from `Ground Truth Raw/NOTES.md`.
2. **Schemas** (`src/schemas.py`). A strict model for the detailed answer, used to check both CLI
   and API replies. Reject partial answers rather than filling gaps.
3. **Promptbooks.** New `combined_analysis.md`: shared intro, then design extraction, then separate
   power and data rules. `exclusion.md` adds the reason. The first paid call freezes the version.
4. **Pipeline.** Update prompt building and checks (`src/reading_room.py`, runner/checker scripts,
   `src/api_contract.py`). Save the detailed answer in a new table linked to the run; keep writing
   the existing power/data judgments. Keep raw replies, retries, hashes, and one paper per prompt.
5. **Export and scoring.** Build the 43-column CSV in order and score each column by the rules
   above. Main file = active papers; dropped and skipped papers go to separate audit files. Report
   the skipped count rather than quietly shrinking totals.
6. **Test before spending.** Offline tests for schemas, missing values, column order, provenance,
   retries, human answers leaking into prompts, excluded rows, and the odd
   `EXCLUDED but data preserved` row. Then a 2-paper paid test, a small calibration set, and a frozen
   cost estimate before the full batch.
7. **Docs.** Update `PLAN.md`, `API_BUILD_SET_IMPLEMENTATION.md`, `Costs.md`,
   `ReadingRoom/README.md`, `ReadingRoom/tests/TEST_PLAN.md`, methods, promptbook notes, script docs.

## Cost and time (rough; replace after the 2-paper test)

Budget 800-1,600 output tokens per paper (including reasoning). Batch output is $5 per million tokens. NaviGator likely has no batch discount (DC59), so expect
roughly double the figures below.

| Papers | Output cost (Batch) |
|---:|---:|
| 88 | $0.35-$0.70 |
| **176** | **$0.70-$1.41** |
| 476 (future full run) | $1.90-$3.81 |

- The whole 176-paper job (input + output) is about **$4-$6 on Batch**, assuming ~20-25k input
  tokens per paper. Retries, an Opus pass, or more survivors cost extra. These figures don't approve
  any spending.
- Time: ~1-2 min per paper on the CLI (3-6 h one at a time, 20-45 min with 8 workers). Batch
  results come back later, so plan it as an overnight job.
