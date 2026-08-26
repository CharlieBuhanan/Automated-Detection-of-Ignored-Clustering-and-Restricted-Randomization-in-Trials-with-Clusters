# Design choices

Every decision that shapes this repo, in one place. Rationale lives in [PLAN.md](PLAN.md);
this is the index. Standing rules are in [CLAUDE.md](../.claude/CLAUDE.md).

---

## Open — still need a decision

Everything else has been settled; the decisions are recorded as DC1-DC43 below.

| | Question | Blocks |
|---|---|---|
| **O1** | **Deb's sign-off, partial.** Confirmed: E13 pilot exclusion ON (DC39); a paper citing its protocol for power/data analysis is `no`, not `undecidable` (DC40). Still open: E3 wedge OFF, E12/E17 retired as cross-paper, E5 rewritten self-declared. The 5 institutional disagreements are dropped and assumed unresolved (DC37) — no longer blocking; Deb's read may restore them later. See [Deb.md](Deb.md). | v1 promptbook |
| **O2** | **Inter-rater statistic for the 15 dual-reviewed pairs.** Deferred, not declined: raw agreement is 12/15 = 80%. Decide before writing the methods section whether Cohen's kappa is reported alongside it. | Methods section |
| **O3** | **What NCI's B/C/D categories mean.** `A` is provably data-correct and is used as a cross-check (DC31); B/C/D stay undefined. Ask Deb only if a finer error taxonomy is wanted for the paper. | Nothing — optional |

---

## Decided

### Corpus and identity

- **DC1 — `paper_id` is the Zotero item key.** Always present, unique, stable across edits.
  DOI/PMCID are missing or inconsistently formatted on some records, so they are metadata only.
- **DC2 — Two sets, not one pool.** The **Unlabelled Set (US)** is the 1287 papers to classify.
  The **Human Labelled Set (HLS)** is 569 fetched / 530 active / 523 with one clean label, and is
  the regression suite. A paper in both is dropped from the US — it already has a human answer.
- **DC3 — The `set` column stores a slug, never a directory name.** `unlabelled` / `human_labelled`
  in the data; `zotero_fetch.SET_DIRS` maps each to its folder (`Unlabelled Set/`,
  `Human Labelled Set/`). The map is the only place the two are joined, so renaming a folder never
  means rewriting 1841 rows again. `set_dir()` raises on an unknown slug rather than silently
  returning a dead path.
- **DC4 — Identity verification is deterministic Python, not a model call.** Comparing
  title/author/DOI is string work: free, reproducible, auditable. A wrong PDF on a right record is
  caught by first-author matching plus `title_pos` (a paper that merely *cites* the target scores 100
  on title alone).
- **DC5 — Correction notices are screened by title, anchored to the start.** Matching
  `erratum|corrigendum|correction|…` anywhere in a title throws away real trials ("Reentry from
  **Corrections** to Community Treatment"). Anchored, it flags 4 documents, all genuine notices.

### Extraction

- **DC6 — A PDF is parsed exactly once, ever.** `src/pdf_extract.py` caches to
  `data/extracted_text/<paper_id>.json`; all downstream code reads the cache, never the PDF.
- **DC7 — The cache's `source_path` is provenance and is never rewritten.** Each cached JSON records
  the absolute path the PDF was read from at parse time. When the folders were renamed
  `testing`/`validation` → `Unlabelled Set`/`Human Labelled Set`, those 1814 fields were deliberately
  **left pointing at the old paths**. Updating them would assert the file was read from somewhere it
  was not, and correcting them honestly would mean re-parsing — which DC6 forbids. Nothing reads
  `source_path` to locate a file; `set_dir()` (DC3) does that. Treat it as a historical record.
- **DC8 — Text only, no table grids.** Journal tables are unruled, so line detection finds nothing and
  text detection shreds two-column prose. Plain `get_text()` already keeps reading order inside a
  table. If power/data analysis later misses table content, the move is `pymupdf4llm`.

### Classification

- **DC9 — Three independent tasks: exclusion, power_analysis, data_analysis.** One promptbook, one
  prompt, one pipeline each. Never merged, never cross-referenced — failure modes differ and
  cross-contamination invalidates the study. **A fourth task, `inclusion`, was considered and
  dropped: nothing in the human labels encodes it.** NCI's `review_category` covers only 95 of the
  176 kept papers and no NHLBI paper at all, so an inclusion call would have no answer to be scored
  against. Exclusion alone is the gate.
- **DC10 — The corpus is gated, not classified wholesale.** Exclusion runs on all 1287; only papers
  it *keeps* reach power/data analysis. A dropped paper gets **no row at all** — not a null, not
  "N/A". Same rule for the HLS, so power/data accuracy is computed only over gate survivors. In the
  labels this shows as 176 kept papers of 523, and only those 176 carry power/stats answers.
- **DC11 — A false exclusion is unrecoverable**, so low-confidence gate calls get an Opus second pass
  **before** gating, not after.
- **DC12 — `undecidable` is an abstention, not a third category.** It means the evidence is genuinely
  insufficient — never that the call was merely hard. "No power analysis reported" is `no`. Every
  `undecidable` goes to the human queue and is excluded from accuracy math rather than scored as a miss.
- **DC13 — `reasoning` and `promptbook_evidence` are separate fields.** `reasoning` is the argument;
  `promptbook_evidence` is which rule it rests on. Keeping them apart makes a miss diagnosable: rule
  misapplied vs. missing vs. wrong — three different fixes.
- **DC14 — Structured output, validated by pydantic, on both routes.** API runs force it with
  `tool_choice`, which makes a malformed reply impossible. The `claude -p` CLI route (DC22) cannot
  force it, so there the prompt asks for JSON and the wrapper validates and re-prompts on a parse
  failure. Free-text JSON is never *trusted* — it is always parsed into the same pydantic model.
- **DC24 — Every parse failure and retry is logged.** A reply the wrapper could not read is recorded
  with its paper_id and attempt count, not silently retried. Retries are not random: a paper that
  makes the model hedge or add prose is usually a genuinely borderline paper, so retries concentrate
  on exactly the hard cases an accuracy number rests on. Logging them makes that selection effect
  measurable — a retry rate that clusters in one part of the corpus is a finding, and a methods
  reviewer will ask. Report the rate alongside accuracy.

### Method and storage

- **DC15 — Promptbooks are markdown in `promptbooks/`, versioned by git commit.** Built empirically
  from misses, not written up front. Each edit is its own commit with the accuracy delta in the
  message; `promptbook_version` on a judgment is that commit hash.
- **DC16 — Opus builds, Sonnet runs.** Opus 5 for the promptbook loop (one-time, high-stakes); Sonnet 5
  for the full run with an Opus second pass on low confidence. Every promptbook gets a Sonnet check
  once it plateaus on Opus — otherwise the gap surfaces after thousands of calls.
- **DC17 — Plateau = two consecutive rounds each under 1pp gain.** Watch the `undecidable` rate too:
  rising while accuracy holds flat means the promptbook is teaching abstention, not judgment.
- **DC23 — A rule needs a pattern, not a paper.** A new promptbook rule needs a **pattern** behind it — several similar misses, never a single paper. A promptbook rewritten hard against one disagreement encodes noise from that sample instead of a general rule, and the rounds are under 100 papers. So: collect the round's misses,
  look for the repeated shape, and write the rule against that. A one-off miss is logged, not
  generalized.
- **DC18 — The holdout is touched once, at the very end.** Promptbooks and the confidence threshold are
  tuned on the build split only. `db.assign_split()` hashes `seed + paper_id`, so assignment depends on
  nothing but a paper's identity; it runs once and refuses to re-run without an explicit force —
  reshuffling after a disappointing holdout is the easiest way to publish an inflated number.
- **DC19 — Judgments are append-only, one row per judgment.** An Opus second pass adds a row, never
  overwrites. `UNIQUE(paper_id, task, judgment_index)` makes a double-write impossible, so an
  interrupted batch can be replayed safely.
- **DC20 — No paper leaves silently.** Every departure is recoverable with its reason and who decided
  it, in `results/01_corpus_build/exclusions.csv`. `DROPPED` is a verdict, not a deletion. `decided_by` distinguishes
  rule / human / model — they carry very different weight in a methods section.
- **DC21 — Nothing is ever guessed on a label join.** An unresolvable citation goes to a human and stays
  out of the database; a wrong label silently corrupts every accuracy number computed afterwards.
- **DC25 — Promptbooks are markdown, deliberately.** One file is read by two audiences: a human
  editing a rule and a model being handed it as a prompt. Markdown is the only format both parse
  well — headings and numbered lists give the model the structured input it follows best (Cao et al.
  2024 label sub-criteria numerically for exactly this reason), while staying diffable in git so a
  rule change shows up as a reviewable line. JSON or YAML would be machine-clean and miserable to
  edit; prose would be readable and unstructured.
- **DC26 — Each promptbook opens with its own prompt block**, structured after ISO-ScreenPrompt
  (Cao et al. 2024): objective → numbered criteria → article → **instructions repeated after the
  article**. The repeat is the point of the method: instructions placed only before a full text get
  lost in long context. Includes a zero-shot chain-of-thought instruction ("think it through step by
  step") and the answer format.
- **DC27 — `reasoning` is capped at 60 words.** Enough to name the deciding evidence, short enough
  to scan across 1287 papers. Beyond that the model is narrating, not deciding, and it costs output
  tokens on every paper.
- **DC28 — Cross-paper reasons are never exclusion criteria.** A paper is judged on its own text.
  "Its outcomes paper exists elsewhere" (protocol) and "we kept a different paper by the same group"
  (random drop) are facts about the corpus, not the paper, and the model cannot see the corpus.
  Duplicate authors and superseded papers are cleaned up post-hoc. The 41 labelled rows carrying
  those two reasons left the scored set (`scripts/10_drop_nonjudgeable_exclusions.py`) rather than
  counting as misses. E5 secondary-analysis was rewritten the same way: self-declared only.
- **DC29 — Every batch run writes a dated row to `results/04_classification/run_log.csv`** — model, processing type
  (API or CLI), promptbook version, git commit, token counts, cost, duration, retry count. Written
  before the first call, so an interrupted run still leaves a record of what was attempted. See
  PLAN.md's Batch run log.

- **DC30 — The build/holdout split is stratified on gate-survivor status.** 30% holdout, drawn
  separately from survivors and non-survivors, so power_analysis and data_analysis get a
  *guaranteed* ~53-survivor holdout rather than whatever the hash happens to produce. Without
  stratification the survivor count in the holdout is left to chance, and it is the number the two
  hardest tasks are scored on.
- **DC31 — NCI's `review_category` is a cross-check, not a task.** `A` provably means "data analysis
  correct" (all 30 A rows have `stats = yes`; no other letter does), so `A ⟺ stats == yes` is asserted
  as a consistency check on the 95 NCI survivors that carry a letter. If it ever breaks, the label
  join broke. B/C/D stay undefined and unused — they are not the SAS strata and cover no NHLBI paper.
- **DC32 — Each promptbook round samples 50 papers from the build split.** Small enough to read every
  miss, large enough for a repeated failure shape to be visible — which DC23 requires before any rule
  is written. At 25 a single paper moves accuracy 4pp and the plateau rule fires on noise; at 100
  nobody reads the misses carefully.
- **DC33 — Opus proposes promptbook rules, a human approves before commit.** The miss plus the current
  promptbook go to Opus, which drafts the rule; nothing enters the promptbook unapproved. DC23's
  pattern requirement and the approval step are the two guards against overfitting to one paper.
- **DC34 — Corrections are appended to the prompt, never to the cache.** At the very end of the
  project, the 2 remaining erratum parents are re-judged with the correction notice appended after
  the article text, behind an explicit flag telling the model it is seeing a paper *and* a correction.
  The cached extraction is never modified, so DC6 and DC7 hold: the cache still records exactly what
  was parsed, and the concatenation happens at prompt-assembly time.
- **DC35 — One promptbook file per task; the wrapper adapts it per route.** The file is the single
  source of truth. For an API run the answer-format table becomes the forced `tool_choice` schema;
  for a CLI run it is rendered as a JSON instruction and repeated after the article text. The
  criteria are byte-identical either way, so the two routes cannot drift.
- **DC36 — Extracted text is scanned for bad parses before any classification spend.** Seven offline
  checks (`scripts/11_scan_text_integrity.py`, PLAN.md step 2b). Thresholds were tuned against their
  own false positives, which outnumbered true positives 11:1 on the first pass — the report records
  what each rejected rule cost.
- **DC37 — Irreducible human disagreement is dropped from the active HLS, assumed unresolved.** The
  5 papers where NCI and NHLBI reached different answers are fully dropped from the corpus
  (`scripts/12_drop_institutional_disagreements.py`), not just held out of the labels — treated the
  same as any other unrecoverable-label category (DC28). Assumed permanent for now; may be restored
  if Deb adjudicates them later, but nothing downstream should wait on that. A label two trained
  reviewers split on is not ground truth.
- **DC38 — A missing parent that would not survive the gate is recorded absent, not chased.**
  `NBBD4EVE`'s parent ("Analysis of cluster-randomized test-negative designs: cluster-level methods")
  was searched for and found — it is an estimator/methods paper and does not belong in the study
  (E8 would exclude it regardless). Confirmed, not just inferred from the title; closed.
- **DC39 — Pilot/feasibility studies are excluded (E13). Confirmed by Deb.** No longer contested.
- **DC40 — Citing a protocol paper for power or data analysis is `no`, confirmed by Deb.** Applies to
  both tasks (P2, D3): DC12 already made "absent or unclear" incorrect rather than `undecidable`;
  this settles the specific case of a manuscript that names its protocol instead of describing its
  own analysis. Consistent with dropping E12 (DC28) — the paper is still judged on its own text, it
  just fails P2/D3 rather than being excluded outright.
- **DC41 — Exclusion has a fourth decision, `wrong_text`, distinct from `undecidable`.** The model
  checks first whether the fetched text describes a study at all; a survey, letter, comment, or form
  is `wrong_text`, never forced into `yes`/`no`. `undecidable` says the call is unclear; `wrong_text`
  says the document is probably wrong. Both route to human review under separate reasons. Scoped to
  exclusion only — power/data analysis only ever see gate survivors, which have already passed this
  check. Complements the offline scan (DC36): that catches parse-level garbage, this catches a
  cleanly-extracted document that just isn't the paper — what the scan's F8 rule later formalized as
  a pattern was first exactly this kind of case (the CONSORT-EHEALTH submission forms).
- **DC42 — A US paper's cross-set-duplicate removal is conditional on its HLS twin surviving.** 207 US
  papers were dropped because an identical HLS copy already carried a usable answer (DC2). If that
  HLS copy is later dropped too (DC37, or any other HLS-side removal), the reason for dropping its US
  twin no longer holds — the paper should be restored to the classification pool rather than lost
  from the study entirely. Not yet swept for existing cases; see the TODO in PLAN.md's checklist.
- **DC43 — `J2RUD3YQ` dropped: no full text exists.** Its DOI (`10.1370/afm.20.s1.2679`) resolves to
  an *Annals of Family Medicine* conference-abstract supplement, not a full article — every download
  returned the same 2-page abstract. Dropped the same way as any single-paper mismatch decision
  (`verdict_reason = MANUAL_DROPPED`, logged in `results/review/04_papers_reviewed_results.csv`),
  not via a dedicated script — there was only one paper, so the established manual-drop trail applied
  directly. Cached text cleared; removed from the mismatch review queue.

- **DC22 — Message Batches API for the full run; `claude -p` CLI for the promptbook loop.** The full
  run is batch classification, not agentic tool use — Batches API, not sync calls, no MCP. The
  promptbook-refinement rounds run through the CLI instead, on subscription quota, **including their
  scored numbers** (see DC14 and DC24 for the trade-off that buys). Label leakage there is blocked
  structurally, not by instruction: scratch cwd outside the repo, no tools, `--max-turns 1`, text on
  stdin, blinded paper IDs. See PLAN.md step 6.
