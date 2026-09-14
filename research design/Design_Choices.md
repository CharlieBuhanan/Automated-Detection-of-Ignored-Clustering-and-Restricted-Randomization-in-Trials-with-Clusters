# Design choices

Every decision that shapes this repo, in one place. Rationale lives in [PLAN.md](PLAN.md);
this is the index. Standing rules are in [CLAUDE.md](../.claude/CLAUDE.md).

---

## Open — still need a decision

Everything else has been settled; the decisions are recorded as DC1-DC55 below.

| | Question | Blocks |
|---|---|---|
| **O1** | **The 5 stepped-wedge papers NHLBI kept and scored — adjudicate after 2026-09-02.** DC52 moved them to the expert-review pile pending an individual re-read; they are currently outside scoring and may be restored only with final labels. | Nothing; scoring is clean while they are pending |
| **O2** | **Inter-rater statistic for the 15 dual-reviewed pairs.** Deferred, not declined: raw agreement is 12/15 = 80%. Decide before writing the methods section whether Cohen's kappa is reported alongside it. | Methods section |
| **O3** | **The 7 rows flagged `restricted_rand = yes` whose `should` never asks for it.** Three were scored *correct* despite the restriction being unaccounted for — the Cattamanchi shape (DC50). Written up as a table for Deb in [Deb.md](Deb.md); decides whether they join the expert-review pile, and whether `data_should` can be compared against `promptbook_evidence` at all. | Nothing yet |
| **O4** | **Is the 5-hour subscription ceiling metered on raw tokens or on cost-equivalent?** If cost-equivalent, the 1.25× cache-write premium is costing ~20% for nothing — `cache_read` is zero on all 134 calls measured, because each sealed process writes a cache it never reads — and killing that premium jumps above lever 2 in priority. If raw tokens, it is worth nothing and can be ignored. Cheap to settle: one round's usage blocks against the observed window. | Ordering of the cost levers (PLAN.md TODO) |
| **O6** | **How many refinement rounds until plateau?** Decides whether lever 2 (exploratory rounds on a fixed 50-paper subset, no history row) is sufficient on its own, or whether Batch API credits are a prerequisite for finishing rather than an optimization. Nothing to decide yet — it is answered by rounds 1-3 under `v2`, and it is worth writing the guess down first. | Whether lever 3 is on the critical path |

---

## Decided

### Corpus and identity

- **DC1 — `paper_id` is the Zotero item key.** Always present, unique, stable across edits.
  DOI/PMCID are missing or inconsistently formatted on some records, so they are metadata only.
- **DC2 — Two sets, not one pool.** The **Unlabelled Set (US)** is the papers to classify; the
  **Human Labelled Set (HLS)** is the regression suite. A paper in both is dropped from the US — it
  already has a human answer. Current counts: `python scripts/05_build_exclusions.py --check`.
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
- **DC7 — The cache's `source_path` is provenance and is never rewritten.** It records where the PDF
  was read from *at parse time*, so the 1814 fields still name the pre-rename folders. Updating them
  would assert a file was read from somewhere it was not; re-parsing to fix them honestly is what DC6
  forbids. Nothing locates files by it — `set_dir()` (DC3) does that.
- **DC56 — References are stripped into a derived cache, never at send time.** Decided 2026-08-28;
  implemented by `scripts/19_strip_references.py` and `src/reference_strip.py`. Of 1,783 cached
  papers, 1,747 (98%) have a standalone references heading; the removable text is 20.7M characters
  (21.6%, ~6.9M tokens) and can contain misleading cited study descriptions. The original cache is
  untouched; `data/extracted_text_stripped/` has one same-named, auditable file per input with a
  `references_strip` source hash, ruleset, removed-char count, and reason.
  A cut requires a standalone heading after 30% of the document and must remove at most 60%; 36
  ambiguous papers remain whole. Post-reference appendices/supplements are restored (134 papers),
  and `[REFERENCES SECTION REMOVED]` prevents E2 from treating the trim as an abstract. Run logs
  record `refs_removed=N` or `refs_kept:<reason>`.
- **DC8 — Text only, no table grids.** Journal tables are unruled, so line detection finds nothing and
  text detection shreds two-column prose. Plain `get_text()` already keeps reading order inside a
  table. If power/data analysis later misses table content, the move is `pymupdf4llm`.

### Classification

- **DC9 — Three independent tasks: exclusion, power_analysis, data_analysis.** One promptbook, one
  prompt, one pipeline each. Never merged, never cross-referenced — failure modes differ and
  cross-contamination invalidates the study. **A fourth task, `inclusion`, was dropped: nothing in
  the human labels encodes it** (DC31), so an inclusion call would have no answer to score against.
  Exclusion alone is the gate.
- **DC10 — The corpus is gated, not classified wholesale.** Exclusion runs on all 1306; only papers
  it *keeps* reach power/data analysis. A dropped paper gets **no row at all** — not a null, not
  "N/A". Same rule for the HLS, so power/data accuracy is computed only over gate survivors. In the
  labels this shows as 176 kept papers of 483, and only those 176 carry power/stats answers.
- **DC54 — The gate stays separate; post-gate power and data analysis share one call.** Decided
  2026-08-28. The combined prompt has isolated rule blocks and returns two independent judgments;
  the wrapper validates/retries them together and stores one row per task. This removes one repeated
  paper payload without mixing gate and analysis or task audit trails.
- **DC55 — Production effort is pinned to `medium`.** Decided 2026-08-28. Reading Room and Batch API
  scored calls use `medium`, not the unaffordable prior `high`; preflight is required after a change.
- **DC57 — References-stripping is a new promptbook version, without restarting the baseline.**
  Decided 2026-08-28. The promptbook bytes do not change, but the text supplied to the model does;
  `v2` records that new reading condition. `exclusion_r1` remains the baseline: its 49 accepted
  `v1`/whole-text judgments are retained for the first history row when it is created, and round 1
  does not restart. Later `v2`/stripped-text results must identify their version and preparation
  method when compared with that retained baseline. The directory is cut and `promptbooks/CURRENT`
  moved immediately before the first `v2` request.
- **DC58 — Reading Room is serial by default; `--parallel` is opt-in.** Decided 2026-08-28. Serial
  makes Ctrl-C and a sealing breach stop before the next spend; parallel submits its pool up front
  and only collects breaches. The display includes running billed tokens. `--parallel` plus
  `--serial` refuses; both modes share one result-handling path.
- **DC11 — A false exclusion is unrecoverable**, so low-confidence gate calls get an Opus second pass
  **before** gating, not after.
- **DC12 — `undecidable` is an abstention, not a third category.** It means the evidence is genuinely
  insufficient — never that the call was merely hard. "No power analysis reported" is `no`. Every
  `undecidable` goes to the human queue and is excluded from accuracy math rather than scored as a miss.
- **DC13 — `reasoning` and `promptbook_evidence` are separate fields.** `reasoning` is the argument;
  `promptbook_evidence` is which rule it rests on. Keeping them apart makes a miss diagnosable: rule
  misapplied vs. missing vs. wrong — three different fixes.
- **DC14 — Schema-constrained output, validated locally, on both routes.** API classification requests
  use native JSON Schema structured output only: `output_config.format` with
  `type: "json_schema"`, the task's schema, and `output_config.effort: "medium"`. They do **not**
  use a client tool declaration or `tool_choice`. The `claude -p` CLI route (DC22) cannot impose that
  provider constraint, so its prompt asks for JSON and the wrapper validates and re-prompts on a parse
  failure. Provider-constrained syntax is still not scientific validation: every reply is parsed into
  the same Pydantic model and passes token-binding, rule-ID, and task-semantic checks. There is no
  silent fallback from the API route to free-text JSON or forced tool use.
- **DC24 — Every parse failure and retry is logged**, with paper_id and attempt count, never silently
  retried. Retries are not randomly distributed: a paper that makes the model hedge or wrap its JSON
  in prose is usually a genuinely borderline paper, so they concentrate on exactly the cases accuracy
  is most sensitive to. Unlogged that is invisible bias; logged it is a reportable rate. After the
  configured attempts are exhausted, record a terminal `review_required` / retry-exhausted state and
  preserve all raw replies. Do **not** invent an `undecidable` judgment: that is a model abstention,
  not a transport or parsing failure (DC12).

### Method and storage

- **DC15 — Promptbooks are markdown in `promptbooks/vN/`, one directory per version.** Built
  empirically from misses, not written up front. `promptbooks/CURRENT` names the active version; after
  a version is run-frozen, a rule change means copying `vN/` to `vN+1/`, never editing in place,
  because a judgment records `promptbook_version` and a rule that moved under a fixed version makes
  every earlier judgment unreproducible. Each version bump is its own commit; include an accuracy delta in the message only
  when a comparable reporting row exists. Each version carries a tables-only `vN doc.md` recording
  what changed, why, and which papers it was written against. **Amended by DC53.**
- **DC53 — Versions have draft, run-frozen, and reporting states.** Draft edits are in place; a new
  directory before the first paid/raw request requires a human-verified rubric change or a repeated
  miss pattern (DC23), not wording/format/token trimming. The first paid/raw request records the
  hash and freezes the version; every later wording or rule change copies `vN` to `vN+1`. A history
  row is separate: it requires an accepted, configuration-homogeneous comparable result and never
  makes a frozen version editable. Intermediate draft wording remains in git history.
- **DC16 — Opus builds, Sonnet runs.** Opus 5 for the promptbook loop (one-time, high-stakes); Sonnet 5
  for the full run with an Opus second pass on low confidence. Every promptbook gets a Sonnet check
  once it plateaus on Opus — otherwise the gap surfaces after thousands of calls.
- **DC17 — Plateau = two consecutive rounds each under 1pp gain.** Watch the `undecidable` rate too:
  rising while accuracy holds flat means the promptbook is teaching abstention, not judgment.
- **DC23 — A rule needs a pattern, not a paper.** Several similar misses, never one. Rounds are under
  100 papers, so a rule written against a single disagreement encodes that sample's noise. Collect
  the round's misses, find the repeated shape, write the rule against that; log the one-off instead.
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
- **DC25 — Promptbooks are markdown, deliberately.** Two audiences read one file: a human editing a
  rule, and a model handed it as a prompt. Headings and numbered lists give the model structure it
  follows well (Cao et al. 2024) while staying diffable in git. JSON/YAML is machine-clean and
  miserable to edit; prose is readable and unstructured.
- **DC26 — Each promptbook opens with its own prompt block**, structured after ISO-ScreenPrompt
  (Cao et al. 2024): objective → numbered criteria → article → **instructions repeated after the
  article**. The repeat is the point of the method: instructions placed only before a full text get
  lost in long context. Includes a zero-shot chain-of-thought instruction ("think it through step by
  step") and the answer format.
- **DC27 — `reasoning` is capped at 200 characters.** Enough to name the deciding evidence, short
  enough to scan across 1306 papers. Beyond that the model is narrating, not deciding, and it costs
  output tokens on every paper. **Characters, not words** (changed 2026-08-26 from a 60-word cap):
  the validator can check a character count exactly, where "60 words" needs a tokenizer nobody
  agrees on and produces a rule the model can violate without either side noticing.
- **DC52 — The model never drops a paper at random, for any reason. Confirmed by Deb, 2026-08-27.**
  E17 was already retired as cross-paper (DC28); this generalizes it from "not this criterion" to a
  standing prohibition in the v1 promptbook. Ignore02 used `randuni` to keep one of several
  same-first-author papers, which is unreproducible from text and not a property of the paper being
  judged. If the only argument for excluding is that some other paper resembles this one, the
  answer is `no`.
- **DC28 — Cross-paper reasons are never exclusion criteria.** A paper is judged on its own text.
  "Its outcomes paper exists elsewhere" and "we kept a different paper by the same group" are facts
  about the corpus, which the model cannot see, so the 41 rows carrying them left the scored set
  (`scripts/10_drop_nonjudgeable_exclusions.py`) rather than counting as misses. Duplicates and
  superseded papers are cleaned up post-hoc. E5 was rewritten the same way: self-declared only —
  **confirmed by Deb, 2026-08-27**, with the caveat that it is knowingly incomplete. Papers are
  *supposed* to declare a secondary analysis and often do not; the human reviewers frequently only
  catch one when it names its protocol or primary-outcomes paper, which is already E5's second
  clause. Provisional by agreement, to be refined once the rounds show what it misses.
- **DC29 — Every batch run writes a dated row to `results/04_classification/run_log.csv`** — model, processing type
  (API or CLI), promptbook version, git commit, token counts, cost, duration, retry count. Written
  before the first call, so an interrupted run still leaves a record of what was attempted. See
  PLAN.md's Batch run log.

- **DC30 — The build/holdout split is stratified on gate-survivor status.** 30% drawn separately
  from each stratum, so power_analysis and data_analysis get a *guaranteed* 53-survivor holdout
  (123 build / 53 holdout of 176) rather than whatever the hash happens to deal. Implemented in
  `db.assign_split()`: papers are **ranked** by hash within a stratum and the lowest 30% held out —
  thresholding cannot guarantee a count. The cost is that assignment now depends on stratum
  membership, so it is not stable under adding labels later; the run-once guard is what makes that
  safe. **Run 2026-08-26 and now permanent:** 338 build / 145 holdout, 123/53 survivors, 215/92
  excluded. Papers dropped after this point shrink their split rather than triggering a re-cut
  (DC47).
- **DC31 — NCI's `review_category` is dropped, not used.** Measured over the 96 NCI rows that carry
  it, the letter agrees with `stats` perfectly in both directions, so it restates a column the study
  already has. No NHLBI paper carries one. Transcribed as a raw record of the source file; nothing
  reads it.
- **DC32 — Each promptbook round samples 50 papers from the build split.** Small enough to read every
  miss, large enough for a repeated failure shape to be visible — which DC23 requires before any rule
  is written. At 25 a single paper moves accuracy 4pp and the plateau rule fires on noise; at 100
  nobody reads the misses carefully.
- **DC33 — Opus proposes promptbook rules, a human approves before commit.** The miss plus the current
  promptbook go to Opus, which drafts the rule; nothing enters the promptbook unapproved. DC23's
  pattern requirement and the approval step are the two guards against overfitting to one paper.
- **DC34 — Corrections are appended to the prompt, never to the cache.** At the end of the project
  the 2 remaining erratum parents are re-judged with the notice appended after the article text,
  behind a flag saying the model is seeing a paper *and* a correction. Concatenation happens at
  prompt-assembly time, so DC6 and DC7 hold — the cache still records exactly what was parsed.
- **DC35 — One promptbook file per task; the wrapper adapts it per route.** The file is the single
  source of truth. For an API run the answer-format table becomes the native
  `output_config.format` JSON Schema; for a CLI run it is rendered as a JSON instruction and repeated
  after the article text. The criteria are byte-identical either way, so the two routes cannot drift.
- **DC36 — Extracted text is scanned for bad parses before any classification spend.** Seven offline
  checks (`scripts/11_scan_text_integrity.py`, PLAN.md step 2b). Thresholds were tuned against their
  own false positives, which outnumbered true positives 11:1 on the first pass — the report records
  what each rejected rule cost.
- **DC37 — Irreducible human disagreement is dropped from the active HLS, assumed unresolved.** A
  label two trained reviewers split on is not ground truth. The 5 papers where NCI and NHLBI
  disagreed are fully dropped (`scripts/12_drop_institutional_disagreements.py`), not just held out
  of the labels — same treatment as any unrecoverable-label category (DC28). Restorable if Deb
  adjudicates, but nothing downstream waits on that.
- **DC38 — A missing parent that would not survive the gate is recorded absent, not chased.**
  `NBBD4EVE`'s parent was found and read: an estimator/methods paper E8 would exclude anyway.
  Confirmed rather than inferred from the title; closed.
- **DC39 — Pilot/feasibility studies are excluded (E13). Confirmed by Deb.** No longer contested.
- **DC40 — Citing a protocol paper for power or data analysis is `no`, confirmed by Deb.** Both
  tasks (P2, D3). DC12 already made "absent or unclear" incorrect rather than `undecidable`; this
  settles the manuscript that names its protocol instead of describing its own analysis. The paper
  is still judged on its own text (DC28) — it fails P2/D3 rather than being excluded.
- **DC41 — Exclusion has a fourth decision, `wrong_text`, distinct from `undecidable`.** The model
  checks first whether the text describes a study at all; a survey, letter, comment, or form is
  `wrong_text`, never forced into `yes`/`no`. `undecidable` says the *call* is unclear; `wrong_text`
  says the *document* is probably wrong. Both route to human review, under separate reasons, so a
  reviewer knows whether to read closely or check Zotero. Exclusion-only: power/data see gate
  survivors, which have already passed this check. Complements DC36's offline scan — that catches
  parse-level garbage, this catches a clean extraction of the wrong document.
- **DC42 — A US paper's cross-set-duplicate removal is conditional on its HLS twin surviving.** 207
  US papers were dropped because an HLS copy already carried a usable answer (DC2). When that copy is
  itself dropped later, the reason no longer holds and the paper should re-enter the pool rather than
  leave the study. **Done: 23 restored** by `scripts/15_restore_dc42_duplicates.py`, gated on
  `13_check_hls_clean.py` passing all 14 checks first so the HLS had stopped shrinking. It fetches
  those 23 item keys directly rather than re-walking the collection, which would resurrect all 207.
  184 removals stand.
- **DC43 — `J2RUD3YQ` dropped: no full text exists.** Its DOI resolves to an *Annals of Family
  Medicine* conference-abstract supplement, not an article — every download returned the same 2-page
  abstract. One paper, so the established manual-drop trail applied directly rather than a dedicated
  script: `verdict_reason = MANUAL_DROPPED`, logged in `04_papers_reviewed_results.csv`, cached text
  cleared, removed from the review queue.

- **DC44 — The manifest's `verdict` column is derived, and every human decision is replayed onto
  it.** `01_verify_identity.py` rescores every row from what the identity ladder can see in a PDF,
  so a re-run silently reverses two things a human already settled: a `DROPPED` paper comes back
  (`PDF_UNREADABLE` if its PDF was moved aside, `VERIFIED` if it was not — and that one re-enters
  the active corpus), and a `WEAK` paper cleared by hand scores `WEAK` again, because what resolved
  it was a person reading the PDF and that is not in the file. One re-run on 2026-08-26 reversed all
  75 drops and 2 cleared papers at once.
  **Fixed at the source rather than by a follow-up step:** `src/review_log.py` reads every decision
  back out of the logs, ordered by timestamp so the newest wins (a paper cleared in script 03 and
  *later* dropped by script 09 stays dropped), and `01_verify_identity.py` now **skips** those papers
  instead of rescoring them. `scripts/16_reapply_drops.py` stays as the repair path.
  This is DC20 paying off twice: because no paper ever left silently, the clobbered manifest was
  fully rebuildable, and the same logs are what the guard now reads.
- **DC45 — The promptbook's E-numbers are the canonical exclusion taxonomy.** NCI used 8 reason
  strings and NHLBI 13, a union of 15 that mixes genuinely new criteria with renamings of the same
  idea. Rather than invent a third vocabulary, exclusion reasons map onto E1-E16 — already the
  vocabulary the model emits, and already explicit about the renamings (E14 cohort and E15 review
  are E9/E10 and E8 under other names). Institute strings stay in the `*_raw` columns as the source
  record. The payoff is that a human reason and a model `promptbook_evidence` become directly
  comparable, which is what makes a miss diagnosable at all (DC13). `stepped_wedge_design` → E3 is
  now an **active** rule (DC48), so its 9 rows are scored like any other exclusion. Two reasons
  still map to no active rule and that is the point: `protocol_paper` → E12 and
  `duplicate_group_random_drop` → E17, both retired as cross-paper (DC28), which is exactly why
  their papers left the scored set.
- **DC46 — The human labels are two reviewers' opinion, and the paper says so.** Ignore02 describes
  them as "the opinion of two knowledgeable reviewers," not ground truth, and this project's own
  data agrees: 5 papers had NCI and NHLBI reach different answers (DC37) and raw agreement on the 15
  dual-reviewed pairs is 12/15. So model-vs-human disagreement is not automatically model error, and
  raw accuracy against these labels is bounded by how much the humans agree with each other. The
  labels are still the best available comparator and the study uses them as such — the commitment
  here is only that the write-up states what they are rather than calling them truth. Exactly how
  that is reported (raw accuracy, κ against a human-agreement ceiling, or both) is O2, decided when
  the results exist.

- **DC47 — Build rounds are cut once and written down, not sampled fresh.** DC32 fixes the round
  size at 50; this fixes *which* 50. A round drawn at random each run makes two rounds
  incomparable, so the plateau rule (DC17) would measure sampling noise as often as the promptbook.
  `scripts/17_assign_build_rounds.py` hashes `seed + paper_id` and writes
  `results/04_classification/build_rounds.csv`, regenerable byte-identically anywhere. Rounds are
  **per task** because the denominators differ — the gate is scored on all 338 build papers (7
  rounds), power and data only on the 123 build survivors (3 rounds each, DC10). Each exclusion
  round is **stratified** at the build split's own 36% survivor rate (18/32 per round): an
  unstratified round could come out 80% excluded, and comparability across rounds is the only thing
  rounds are for.
  **A paper dropped after the cut shrinks its round; it does not trigger a re-cut** (Deb,
  2026-08-27). Rounds exist to be comparable to each other, and a 49-paper round is comparable to a
  50-paper one — where a re-cut reshuffles every round's membership and makes *all* of them
  incomparable to anything already run. So round sizes are allowed to vary, and the round a paper
  left is recorded with the drop. This holds for a handful of papers, not a wave: if drops ever
  reach a size where a round's stratum balance visibly moves off 18/32, re-cut instead and say so.

- **DC48 — E3 stepped-wedge trials ARE excluded. Ruled by Deb, 2026-08-27.** This reverses v0's
  *contested, default OFF*. The v0 reasoning was that NHLBI applied the criterion inconsistently —
  9 papers excluded for it, 5 others kept and fully scored — and that under DC11 a wrong exclusion
  is unrecoverable, so the safer default was to keep them all. Deb settled the criterion rather
  than the inconsistency: stepped wedge excludes. What that buys and costs is asymmetric and worth
  stating, because the promptbook is now expected to disagree with 5 labels **by construction**:
  the 9 excluded rows become scorable hits, and the 5 kept rows become guaranteed misses (O1)
  unless they join the expert-review pile. DC11 still applies with more force than before — E3 is
  a search-stage rule that fires early and cheaply, so a stepped-wedge call landing under the
  confidence threshold should get its Opus second pass before the gate closes, not after.
- **DC49 — Longitudinality does not make a data analysis incorrect. Ruled by Deb, 2026-08-27.**
  Ignore02 rule 6 counts exactly two things — clustering and restricted randomization — and
  explicitly forgives every other statistical flaw. NHLBI departed from that on at least one paper,
  scoring `MQF2Y5AM` (Altinger 2024) incorrect for assuming exchangeability across repeated
  measures. Deb's ruling is to follow the published rule: D14 stops being contested and folds into
  D13's *what must not count* list. `MQF2Y5AM` is therefore a **known, accepted expected miss** —
  it sits in the holdout, so it costs a holdout point and is not available to tune against, which
  is the right place for it. Provisional by agreement, like E5: refine if the rounds show a pattern.
- **DC50 — A label the reviewers now believe is wrong is dropped to an expert-review pile, never
  silently corrected.** First member: `XHFTHUCG` (Cattamanchi 2021), which carries restricted
  randomization unaccounted for yet was scored `data_correct = yes`, where ~40 papers of that shape
  were scored `no`. Deb's call is that the label is wrong. Editing it in place would make the
  labels partly *our* opinion rather than the reviewers', which DC46 says the write-up must not
  claim; scoring against a label two people now disagree with reproduces DC37's problem. So the
  paper leaves the scored set the same way the 5 institutional disagreements did — moved, logged,
  reversible — and Keith and Deb adjudicate the pile after **2026-09-02**. The pile is a growing
  list, not a one-off: O1's 5 stepped-wedge rows and Deb.md's 7 restricted-randomization rows are
  candidates for it.
- **DC51 — A label contradicted by a *rule* stays in the scored set as an accepted miss; only a
  label contradicted by a *reviewer* leaves.** The line between DC50 and this one is who says the
  label is wrong. Deb read `XHFTHUCG` and judged that row wrong, so it leaves (DC50). Nobody has
  re-read the 5 stepped-wedge papers NHLBI kept — all that changed is a criterion, and inferring
  five bad labels from one ruling is a conclusion the reviewers have not drawn. Dropping them would
  also set the worse precedent: a test set curated by removing whatever disagrees with the current
  promptbook is one that can no longer measure it, and DC46 already commits the write-up to
  reporting real human disagreement rather than hiding it. So they stay, scored, and wrong on
  purpose. The cost is made explicit instead: a **−0.9pp build / −1.4pp holdout floor** on exclusion
  accuracy, documented in `v0 doc.md`'s *Known expected misses* and reported by `evaluate.py` as its
  own line rather than folded into `miss`. Two guards follow from it — a round's Δ is compared
  against the floor, not 0 (it is most of one plateau step, DC17), and an `E3` miss can never drive
  a promptbook rule without being checked against the five first, or the loop will learn its way
  back to E3 OFF from five known-bad labels (DC23, DC33). Revisit after 2026-09-02: re-scoring them
  as excluded erases the floor and loses nothing, and is the outcome to prefer.
  **Superseded by DC52, 2026-08-27 — the 5 were dropped after all.**
- **DC52 — DC51 reversed: the 5 analyzed stepped-wedge papers join the expert-review pile.**
  Decided 2026-08-27, executed by `scripts/18_drop_expert_review.py`. Build 338 → 335, holdout
  145 → 142; three exclusion rounds run short and are **proceeded with, never re-cut** (DC47).
  DC51's reasoning was right while E3 was contested and wrong once Deb ruled it ON (DC48): with the
  criterion settled, NHLBI's own 9 stepped-wedge exclusions contradict these 5 keeps, so the label
  set disagrees with *itself*, not merely with our promptbook. Scoring against a label
  self-contradicted that way is DC37's problem exactly — a number computed against an answer nobody
  stands behind. DC51's precedent worry stands and is answered by *where* they go: not deleted, not
  corrected, but moved to the pile Keith and Deb adjudicate after 2026-09-02, logged with a reason,
  restorable in one command (`16_reapply_drops.py`). What it buys is not cosmetic — the alternative
  was carrying a −0.9pp/−1.4pp floor through every exclusion figure for the rest of the study, with
  a standing rule that no `E3` miss may drive a promptbook change without first being checked
  against five known-bad labels. **The pile records that these five are a different kind of member
  from `XHFTHUCG`:** Deb read Cattamanchi and rejected it; she ruled the criterion these five follow
  from and has not re-read them. `judged_by` says which is which, and the adjudication must not
  flatten the two.

- **DC22 — Message Batches API for the full run; `claude -p` CLI for the promptbook loop.** The full
  run is batch classification, not agentic tool use — Batches API, not sync calls, no MCP. The
  promptbook-refinement rounds run through the CLI instead, on subscription quota, **including their
  scored numbers** (see DC14 and DC24 for the trade-off that buys). Label leakage there is blocked
  structurally, not by instruction: scratch cwd outside the repo, no tools, `--max-turns 1`, text on
  stdin, blinded paper IDs. See PLAN.md step 6.
