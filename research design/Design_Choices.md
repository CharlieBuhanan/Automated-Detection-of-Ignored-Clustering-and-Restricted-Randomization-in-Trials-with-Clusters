# Design choices

Every decision that shapes this repo, in one place. Rationale lives in [PLAN.md](PLAN.md);
this is the index. Standing rules are in [CLAUDE.md](../.claude/CLAUDE.md).

---

## Open — still need a decision

Nothing below is blocked on code. Each needs a human answer before the phase it gates can run.

| | Question | Blocks |
|---|---|---|
| **O1** | **Exclusion criteria breakdown.** What actually makes a paper excludable, rule by rule. `promptbooks/exclusion.md` is a v0 stub. | The whole promptbook loop |
| **O2** | **Is NCI's `Review Category` A/B/C/D worth defining at all?** `A` is provably "data analysis correct"; B/C/D are three flavours of incorrect, but which is which is unknown. It covers only 95 of the 176 kept papers and no NHLBI paper. Now that `inclusion` is dropped (DC9) it blocks nothing — the only question is whether it adds a usable cross-check on data_analysis. | Nothing — optional |
| **O3** | **Build/holdout batching.** Three sub-questions: how the 523 labelled papers split; whether to stratify on gate-survivor status (a flat 30% holdout leaves only ~29 survivors to score power/data on); and the per-round sample size. | `--assign-split`, which runs **once** |
| **O4** | **Do correction notices belong in the corpus?** An erratum that fixes a sample size or a p-value makes the *uncorrected* paper wrong on exactly what this study scores. Now **2 parents affected, both Unlabelled Set** — the Patterson pair resolved and left the study (see PLAN.md's Erratum pass), so no labelled paper depends on this any more. Lower stakes than it was. | Corpus definition |
| **O5** | **Adjudicate 6 institutional disagreements** (NCI vs NHLBI on the same paper; one is a complete flip). No automated way to pick a side — the paper has to be read. See `results/review/05_label_match_review.csv`. | 7 papers held out of the labels |
| **O6** | **Find `NBBD4EVE`'s parent paper**, or record why it is absent. | Ledger completeness |
| **O7** | **Promptbook edits on a miss: hand-written or Opus-proposed?** Model-assisted is faster but every rule needs a spot-check. | Promptbook loop mechanics |
| **O8** | **Extracted-text integrity scan?** 100M characters have only ever been checked for length — mojibake, multi-article PDFs and truncation are unmeasured. | Confidence in the inputs |
| **O10** | **Revise the promptbooks for both API and CLI.** One prompt block currently serves both. The API path forces `tool_choice` (the answer-format table becomes a tool schema); the CLI path must ask for JSON in prose and re-prompt on failure. They need separate wording, and the ISO-ScreenPrompt repeat-after-article step needs building into whichever wrapper sends them. | Promptbook loop |
| **O11** | **Deb to review `promptbooks/exclusion.md` v0** — in particular E13 (pilot/feasibility), which Ignore02 is silent on and which is ON by decision, not by reproduction. | v1 promptbook |
| **O9** | **Three leftovers from the US/HLS rename** (all cosmetic, all safe to defer): the `assign_split()` seed is still the string `"cluster-paper-review"`; `"Both Validation Institutes"` is still a live value in 15 manifest rows; `zotero_fetch_draft.md` still describes a superseded scheme. | Nothing |

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

- **DC22 — Message Batches API for the full run; `claude -p` CLI for the promptbook loop.** The full
  run is batch classification, not agentic tool use — Batches API, not sync calls, no MCP. The
  promptbook-refinement rounds run through the CLI instead, on subscription quota, **including their
  scored numbers** (see DC14 and DC24 for the trade-off that buys). Label leakage there is blocked
  structurally, not by instruction: scratch cwd outside the repo, no tools, `--max-turns 1`, text on
  stdin, blinded paper IDs. See PLAN.md step 6.
