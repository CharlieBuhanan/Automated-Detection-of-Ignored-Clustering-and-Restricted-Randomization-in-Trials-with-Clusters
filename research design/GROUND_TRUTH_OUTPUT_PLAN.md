# Draft plan: ground-truth-shaped model output

Status: planning only; no implementation is authorized. The final exported per-paper CSV must have
the same 43 columns, names, and order as `data/ground_truth.csv`; Claude generates only the fields
needed for its current task and inferable from the paper. Target configuration is
`claude-sonnet-5`, medium effort, Anthropic Batch API.

## Decisions recorded

1. The **final CSV**, not every response, contains all 43 columns. Each model call returns only its
   task's fields; for example, exclusion does not discuss data-analysis correctness.
2. An excluded paper stops at the gate. Its post-gate fields remain blank.
3. Claude returns normalized structured values; the exporter renders legacy-compatible strings.
4. Raw/source/join fields are wrapper-supplied wherever possible, never guessed.
5. Wide extraction targets all **176 labelled survivors**. Today only 88 have detailed NHLBI truth,
   but Deb and Keith may label the remainder; evaluation reports current coverage explicitly.
6. Production remains Sonnet 5, medium effort, Batch API.

## Recommended contract

Keep the gate as a separate call. A valid gate response adds a normalized `exclusion_reason` to the
existing decision/audit fields. Only kept papers enter one **wide combined-analysis** call.

- **Wrapper-supplied (13):** `paper_id`, `paper_id_note`, `source_institute`, `source_file`,
  `source_row`, `citation_raw`, `cite_key`, `matched_by`, `match_score`, `source_note`, `source_doi`,
  `source_pmid`, `reason_source`. These are corpus/provenance facts, not claims in a paper; Claude is
  blinded to several of them and must not guess them.
- **Claude-extracted/judged across task-specific calls (22):** `excluded`, `exclusion_reason`, `power_correct`, `data_correct`,
  `n_trt`, `n_levels`, `comment_levels`, `n_outer`, `n_2nd`, `n_3rd`, `n_4th`, `unit_rand`,
  `ind_samp_unit`, `restricted_rand_raw`, `icc`, `n_long`, `stepped_wedge_raw`, `data_done`,
  `data_should`, `data_comment`, `power_done`, `power_should`. Use explicit null/`NR` rules and retain
  the existing reasoning, rule evidence, confidence, and blinded-token audit data outside the
  43-column compatibility export.
- **Derived (6):** `labeled`; normalized `restricted_rand` and `stepped_wedge`; and the three raw
  label fields (`exclusion_reason_raw`, `power_correct_raw`, `data_correct_raw`) copied from the
  corresponding model response before normalization.
- **Unsupported legacy fields (2):** leave `review_category` and `review_category_raw` blank. The
  reading-room notes and DC31 establish that this NCI-only A/B/C/D field is redundant with
  `data_correct`, absent from NHLBI, and lacks a documented reproducible mapping.

This yields an exact ground-truth-shaped artifact without asking the model to invent source records.
Write predictions under `results/04_classification/`; never overwrite or join answers into the
blinded model prompt from `data/ground_truth.csv`.

### Draft normalized vocabulary

Use structured internal values and render the existing free-text columns only at export. This draft
collapses common language observed in the 88 original detailed reviews (for example, “accounted for
clustering,” “mixed model,” “GEE,” “not reported,” “stratified,” and “pair matching”).

- **Missingness:** `null` = not applicable/not requested; `not_reported` = the paper was searched but
  did not report it; `unclear` = reported text is contradictory or uninterpretable. Never conflate
  these with zero, `no`, or an empty string.
- **Counts:** `n_trt`, `n_levels`, and `n_long` are integers when ascertainable. Cluster-count fields
  use `{status: exact|approximate|range|per_parent|not_reported|unclear, value/min/max, per_unit}`;
  the exporter renders values such as `10`, `~20/school`, a range, or `NR`.
- **Nested units:** an ordered inner-to-outer array, rendered as `patient within physician within
  clinic`. Canonical unit names are lowercase singular (`clinic`, `school`, `practice`, `village`,
  `hospital`, `physician`, `family`, `site`, `community`, etc.), with `other` plus retained text
  instead of forcing an incorrect category. `unit_rand` and `ind_samp_unit` select from those units.
- **Restricted randomization:** zero or more schemes from `pair_matched`, `matched_sets`,
  `stratified`, `blocked`, `constrained`, `minimization`, plus optional factors/details; otherwise
  `none`, `not_reported`, or `unclear`. Render both `restricted_rand_raw` and the legacy normalized
  `restricted_rand` (`yes|no|unclear`) in the wrapper.
- **ICC:** `{status: exact|range|multiple|not_reported|unclear, values, level_or_population}` so a
  scalar, range, or subgroup-specific set is not flattened prematurely.
- **Stepped wedge:** `yes|no|unclear|not_reported`; the wrapper supplies both raw and normalized
  legacy columns.
- **Data method used:** `mixed_effects`, `gee`, `cluster_level`, `cluster_robust_se`, `permutation`,
  `bayesian_hierarchical`, `individual_level`, `other`, or `not_reported`, plus modeled levels and
  handled/omitted factors from `clustering`, `restricted_randomization`, and `longitudinality`.
- **Power method used:** `icc_or_design_effect`, `simulation`, `coefficient_of_variation`,
  `between_cluster_variance`, `individual_level`, `post_hoc`, `other`, or `not_reported`, with the
  same handled/omitted factors. `data_should` and `power_should` use required factors and levels,
  rather than unconstrained prose.
- **Correctness:** `yes|no|undecidable`, judged under the task rubric using the structured “done” and
  “should” record and returned with independent reasoning, evidence rule, and confidence.
  `data_comment` becomes optional issue tags (`unclear_reporting`, `missing_method`, `wrong_level`,
  `restriction_ignored`, `longitudinality_ignored`, `label_inconsistency`, `other`) plus a short note.

Before implementation, Deb and Keith should confirm whether `*_should` is exhaustive and whether
longitudinality should be extracted descriptively even though DC49 excludes it from correctness.

## Repository changes to implement after approval

1. **Freeze a field dictionary.** Promote the 43-column order and the meanings in
   `Ground Truth Raw/NOTES.md` into one machine-readable contract. Specify type, nullability,
   normalization, gate applicability, allowed vocabulary, source (`model|wrapper|derived`), and
   evaluation rule for every column. Resolve ambiguous concepts first, especially nesting order,
   independent sampling unit, repeated-measure count, exhaustive versus shorthand `*_should`, and
   `NR` versus absent.
2. **Revise schemas without weakening current judgments.** Add a strict wide extraction model and
   combined response wrapper in `src/schemas.py`; generate the Batch JSON Schema from it; validate
   CLI and API responses through the same object. Keep exclusion and post-gate responses atomic,
   forbid extra keys, and reject partial wide records rather than silently filling them.
3. **Refactor promptbooks.** Add a versioned `combined_analysis.md` with one shared preamble, a
   design-extraction section based on the field dictionary, then isolated power and data rules.
   Update `exclusion.md` to return the normalized reason. Update the template/version log and bump
   `promptbooks/CURRENT` only after offline tests and expert answers; the first paid/raw call freezes
   the version under DC53/DC57.
4. **Extend routing, checking, and persistence.** Update prompt construction and semantic checks in
   `src/reading_room.py`, both runner/checker scripts, and `src/api_contract.py`. Store the immutable
   wide response in a new extraction table (or equivalently normalized child table) linked to
   `run_id`/`response_id`; continue writing the two existing task judgments for current evaluation.
   Preserve raw replies, retries, hashes, and one-paper isolation.
5. **Export and score field-by-field.** Add a deterministic exporter that combines task-specific model fields,
   wrapper metadata, and derived values into exactly the 43-column header. Extend evaluation beyond
   binary accuracy: exact/normalized agreement for categorical fields, numeric agreement with a
   declared tolerance, and missingness plus adjudicated rubric scoring for free text. Score detailed
   extraction on all 176 survivors, but score it only where human truth exists (currently 88 NHLBI
   rows); do not treat the other 88 blank records as negative labels. Expand scoring coverage if Deb
   and Keith complete those labels, without changing the already-frozen model responses.
6. **Test before spend.** Add schema, null/gate, normalization, export-order, provenance, retry,
   atomicity, and ground-truth-leakage tests, including excluded rows and the exceptional
   `EXCLUDED but data preserved` source row. Run offline tests, then a 2-paper paid smoke test and a
   small stratified calibration set. Freeze a request manifest and maximum-cost estimate before any
   full Batch submission.
7. **Update documentation.** Amend `PLAN.md`, `API_BUILD_SET_IMPLEMENTATION.md`, `Costs.md`,
   `ReadingRoom/README.md`, `ReadingRoom/tests/TEST_PLAN.md`, methods, promptbook version notes, and
   script docs so the wide artifact, evaluation denominator, and cost/provenance rules agree.

## Output-token time and cost (planning range)

The 88 populated ground-truth extractions serialize to only ~160 visible tokens on average, but
Claude usage also bills reasoning tokens. Existing runs average 218 output tokens for power and 746
for data (high effort); budget **800–1,600 total output tokens per wide medium-effort survivor** until
the smoke test replaces this estimate. At current Sonnet 5 pricing ($10/MTok output standard) and the
50% Batch discount ($5/MTok), output-only cost is approximately:

| Wide records | Output tokens | Batch output cost |
|---:|---:|---:|
| 88 | 0.07–0.14M | $0.35–$0.70 |
| **176 selected survivors** | **0.14–0.28M** | **$0.70–$1.41** |
| 476 projected future production survivors | 0.38–0.76M | $1.90–$3.81 |

For 176 survivors, the whole wide post-gate job—not just output—is roughly **$4–$6 Batch** if input
remains ~20–25k tokens/paper and the new rubric adds no more than ~3k. A low-confidence Opus
review pass, retries, US-only inference, or a higher survivor rate is extra. Do not use these figures
as a spend authorization; replace them with the two-paper run log and frozen-manifest calculation.

CLI wall time was previously estimated near 40 seconds/call; a wider answer should be budgeted at
roughly **1–2 minutes/paper** until measured (about 3–6 hours serial for 176, or 20–45 minutes at
eight workers, subject to the subscription window). Anthropic Batch is asynchronous and should be
planned as an overnight job rather than an interactive run.
