# Roadmap

Reference doc. Not loaded into context automatically — read when starting a new phase.
Standing rules live in [.claude/CLAUDE.md](../.claude/CLAUDE.md).

## Run 1 is a proof of concept

**One promptbook-refinement pass and one full run, finished by **2026-08-28**, for
about **$60** against a $100 budget.** The goal is to prove the pipeline end to end,
not to produce the final numbers: single pass, no self-consistency voting,
refinement on the CLI against subscription quota so the budget goes entirely to
the Batch API production run. Full breakdown in [Costs.md](Costs.md).

What that buys: a survivor count with per-paper drop reasons, power and data
accuracy on the survivors, and one holdout number. What it does not buy:
majority voting, a second refinement pass, or any claim that the promptbooks
have plateaued. Those wait for run 2.

## TODO now

- [ ] **Run `db.assign_split()`.** Gate-survivor stratification is implemented (DC30); the dry run
      gives 123/53 survivors and 215/92 excluded. It runs once. Nothing blocks it now.
- [ ] **Email Deb the four open exclusion criteria** (E3 stepped wedge, E5 secondary analysis,
      E12 protocol, E17 random drop) plus the longitudinality question and the seven
      restricted-randomization label rows. All six are written up as a checklist in
      [Deb.md](Deb.md) — send that, not a summary. This blocks the v1 promptbook.
- [ ] **Build the Reading Room** — the isolated CLI harness the promptbook loop runs in. See
      "The Reading Room" below. Nothing in the refinement loop can start without it.
- [ ] `src/schemas.py` does not exist. Neither do `promptbook_builder.py`, `evaluate.py`,
      `two_pass.py`, or anything in `results/04_classification/`. The classification half of this
      plan is documented and unwritten.

### Two ways to lose work, both real, both now guarded

**Re-running `01_verify_identity.py` silently undoes every human verdict** (DC44). It rewrites
`verdict` for every manifest row from what the identity ladder can see in a PDF, so a `DROPPED`
paper whose PDF was moved aside comes back `PDF_UNREADABLE`, a `DROPPED` paper whose PDF stayed
comes back `VERIFIED` and re-enters the corpus, and a `WEAK` paper a human cleared scores `WEAK`
again. **Always run `scripts/16_reapply_drops.py` straight afterwards** — it replays every recorded
decision, newest wins.

**Re-running `00_fetch_zotero.py --set human_labelled` undoes the duplicate merge** — the 15 removed NHLBI
rows are gone from the manifest and their PDFs are moved aside, so `completed_ids()` no longer skips them
and they come back. Re-run `scripts/06_merge_hls_duplicates.py` afterwards; it is idempotent and
skips pairs already merged.

## Goal

Rate scientific papers on **power_analysis** and **data_analysis** correctness, after filtering the
corpus with **exclusion** criteria. **1306 study papers** to classify; a separate
human-labeled Human Labelled Set (HLS).

**The corpus is 1306 papers.** 2115 counted *collection placements*, not papers — 483 papers are filed
under two or more NIH institutes. Full reconciliation (2115 raw → 2113 paper-placements → 1494 unique)
is in `results/01_corpus_build/unvalidated_set_summary.tex`. Also excluded: `sample NCI-new` (104 papers, disjoint from
every other collection) and one non-article item (a `videoRecording`). 207 came off in the
cross-set duplicate check — papers already sitting in the Human Labelled Set with a human label —
and 23 of those came back when their HLS twin was itself dropped (DC42,
`scripts/15_restore_dc42_duplicates.py`), leaving 184 removed (1494 → 1310, minus 4 later drops
→ **1306 active**).

**569 HLS PDFs were fetched; 530 are active in the corpus and 523 carry one clean label.**
`FinalCollectionFor Publication` (NCI) held 232 and `Locked_26_01_08_337` (NHLBI) held 337. NCI's
ground truth is complete (`GroundTruthDataNCI01.xlsx`, 232 rows). NHLBI's arrived in two disjoint
files that together covered all 337: `crt_review_table_112.tex` (159 papers taken to full
extraction) and `NHLBI_exclusions_178.csv` (178 rejected before extraction). The remaining 23 tex
entries were cited but never judged and will not be — dropped by
`scripts/09_drop_unreviewed_nhlbi.py`, not waited on. Of the 530, 5 were institutional disagreements
— NCI and NHLBI reached different answers on the same paper — and are now dropped rather than held
(DC37; `scripts/12_drop_institutional_disagreements.py`). Every "500 / 350 / 150" figure in earlier
drafts predates counting what is actually there. **Current active corpus: run
`python scripts/05_build_exclusions.py --check` for the up-to-date count** — this paragraph describes
the fetch/label-load stage, before later drops (nonjudgeable exclusions, disagreements).

All three label files are merged into `data/ground_truth.csv` by `scripts/07_build_ground_truth.py` — a
wide union of the three source schemas, one row per HLS paper, 567 of 569 joined to a `paper_id`.
Source strings are preserved in `*_raw` columns beside their normalized forms. The sources and every
quirk found in them are documented in
[Ground Truth Raw/NOTES.md](../Ground%20Truth%20Raw/NOTES.md).

The criteria have real nuance — many things, including rare events, can make a paper "incorrect power
analysis." The promptbooks are built empirically from Human Labelled Set misses rather than written up front.

## Study design

Three decisions shape everything below.

**The corpus is gated, not classified wholesale.** Exclusion runs first, on all 1306. Only survivors go
to power_analysis and data_analysis. A paper proceeds if exclusion says *keep*.

**`inclusion` was dropped as a fourth task — nothing in the human labels encodes it.** The only
candidate column, NCI's `review_category`, covers 96 of the 176 kept papers, carries no NHLBI paper
at all, and restates `stats` exactly where it is present (DC31). There is no human answer an
inclusion call could be scored against. Exclusion alone is the gate. `review_category` stays in the
database as a transcription of the source file, mapped to no task and read by nothing.

**Power/data correctness is only meaningful for papers that pass the gate.** A dropped paper gets no
power_analysis or data_analysis row at all — not a null, not an "N/A" decision, no row. This applies to
the Human Labelled Set too: build the power/data promptbooks only on HLS papers that pass the gate, and
compute their accuracy over that subset. Scoring a paper the study would have thrown out measures
nothing.

This is **not** the flat `2115 x 4 = 8460` figure that earlier drafts used — wrong on every count: the
paper count, the task count, and the gating. The real shape is two sequential batch jobs:

```
job 1:  1306 x 1 (exclusion)                 = 1306 calls
        + Opus review of low-confidence gate calls
job 2:  <survivors> x 2 (power, data)        = 2 x however many survive
```

Survivor count is unknown until job 1 finishes; it determines job 2's size and cost.

**The gate gets a second pass, the other tasks get one too — but the gate's matters more.** There are no
human labels for the 1306, so a paper's fate rests on the model's own exclusion call, and a
false exclusion is unrecoverable: the paper never reaches power/data analysis and silently leaves the
study. Low-confidence gate calls go to Opus **before** gating, not after.

**30% of the labeled papers are held out.** Promptbooks are built and iterated on the build split; the
confidence threshold is tuned on that same split. The holdout is touched **once**, at the very end, with
the final production config (Sonnet + Opus second pass). That single number is the honest accuracy
estimate — everything measured on the build split is optimistic, because the promptbook was written to fix
those exact papers.

The same holdout is used for all four tasks. Splitting per-task would leak: a paper studied while
building the exclusion promptbook is no longer unseen when scoring data_analysis.

**The split is assigned once, by `db.assign_split()`, and refuses to re-run.** It hashes
`seed + paper_id`, so it depends on nothing but a paper's identity — not row order, not when it was
loaded, not how many labels existed at the time. Adding the NHLBI labels later and re-running leaves
every existing assignment untouched. Re-assigning takes an explicit `force`, because reshuffling after
seeing a disappointing holdout number is the easiest way to publish an inflated one.

## Decision schema

All three tasks return the same object via forced `tool_choice`, validated by pydantic
(`src/schemas.py`):

```python
{
  "decision":        "yes" | "no" | "undecidable" | "wrong_text",  # wrong_text: exclusion only
  "reasoning":       str,    # why, in the model's own words
  "promptbook_evidence": str,    # which promptbook rule(s) drove it, quoted or cited
  "confidence":      float,  # 0-1
}
```

**`wrong_text` is exclusion-only, and is a different abstention from `undecidable`.** The model
checks, before anything else, whether the fetched text describes a study at all — a survey
instrument, a letter, a comment, or a form is `wrong_text`, not forced into `yes`/`no`. `undecidable`
means the text is readable but the *call* is genuinely unclear; `wrong_text` means the text is
probably not the paper. Both route to human review (see below), but under separate reasons, so a
reviewer knows whether to read closely or to check Zotero for the right PDF. This complements
`scripts/11_scan_text_integrity.py` (step 2b): the offline scan catches parse-level garbage
(mojibake, truncation); `wrong_text` catches a cleanly-extracted document that is simply the wrong
one — exactly the CONSORT-EHEALTH submission forms that scan later learned to detect by pattern
(F8) were first the kind of thing this decision exists to catch at classification time, corpus-wide.

| task | `yes` means | `no` means |
|---|---|---|
| exclusion | exclude this paper | keep it |
| power_analysis | power analysis is correct | incorrect |
| data_analysis | data analysis is correct | incorrect |

**`reasoning` is capped at 200 characters.** Long enough to name the deciding evidence, short enough that
a human can scan 1306 of them. The cap is stated in every promptbook's prompt block; anything longer
is the model narrating rather than deciding, and it costs output tokens on every paper.

**A paper that reports no power analysis at all is `no` (incorrect)** — absent and wrong collapse into
one label. Say this explicitly in `promptbooks/v0/power_analysis.md`; it is the most likely place for the model
to hedge.

**`undecidable` is an abstention, not a third category.** It means the evidence in the paper is
genuinely insufficient to call either way — not that the call is hard, and never a substitute for a
judgment the promptbook already covers. "No power analysis reported" is `no`, not `undecidable`. The promptbook
must say this outright, or the model will reach for `undecidable` whenever a case is merely difficult,
and the human queue fills with work that did not need a human.

Every `undecidable` goes to the human review queue. In the worst case a researcher looks at the paper
directly, which is the point: a model that cannot decide should say so rather than guess.

**`promptbook_evidence` is separate from `reasoning` on purpose.** `reasoning` is the argument;
`promptbook_evidence` is which rule it rests on. Keeping them apart makes the promptbook loop mechanical — when
a paper is misjudged, you can see whether the promptbook was misapplied, or was silent, or was wrong, and
those three call for different fixes.

## Human review queue

`results/needs_review.csv` — everything a human has to look at before the study is complete, from
whatever stage produced it:

| source | reason |
|---|---|
| step 1 | `MISMATCH` — the PDF does not appear to be the paper Zotero claims |
| step 1 | `PDF_MISSING` / `PDF_UNREADABLE` — nothing to classify |
| step 0 | multi-PDF `warning` where step 1 came back `WEAK` |
| any task | `decision == "undecidable"` after the Opus second pass |
| exclusion | `decision == "wrong_text"` — check the fetched PDF, not the paper's eligibility |

A paper is only truly undecidable once **both** passes have said so — a low-confidence or `undecidable`
Sonnet call routes to Opus first. Papers in this queue are excluded from accuracy math rather than
scored as misses.

## Pipeline

0. **Fetch** — `src/zotero_fetch.py` walks the collection named by `ZOTERO_COLLECTION_KEY` **and every
   collection nested under it, at any depth**, downloads each record's PDF attachment, checks it against
   Zotero's own md5, and writes `data/raw_pdfs/{set}/{paper_id}.pdf` where `paper_id` is the Zotero item
   key (DOI/PMCID are not always present, so they are metadata only).

   **Crash-safe and resumable.** `zotero_meta.jsonl` is written *before* the first download — it needs
   no network, and writing it first means no PDF ever sits on disk without a record of what it is (they
   are named by item key, so an orphaned PDF is opaque). The manifest checkpoints every 50 rows, inside
   a `try/finally`, so an interrupt or a crash still leaves a usable file.

   A re-run skips any paper whose manifest row is `OK` and whose PDF matches its recorded md5 — verified
   locally, no API call. `--refresh` forces a full re-check; without it, a PDF swapped in Zotero after
   the first fetch goes unnoticed. A no-op re-run still costs ~3 minutes, since the collection walk has
   to happen regardless; it is the ~1306 per-paper round trips that the skip avoids.

   **Folder metadata.** Two columns record where a paper came from: `folder` is the immediate collection
   name (`NCI`), `folder_path` is the full path from the root (`Boring Task / NCI`). Depth is not
   assumed — institutes today, institutes-by-year later, no code change either way.

   **Two outputs.** `data/zotero_manifest.csv` is the scannable one-row-per-paper summary;
   `data/zotero_meta.jsonl` is the complete record behind it. Both merge on `paper_id`. See the two
   sections at the end of this file.

   **A paper in two collections gets one row**, with the folders joined (`folder = "NCI; NHLBI"`).
   `paper_id` has to stay unique: it is what the PDF, the cached text, and every later join are keyed on,
   and a duplicate row would double-count in accuracy math.

   **Attachment rules.** A Zotero record can carry several attachments:
   | Record has | Action | Warning? |
   |---|---|---|
   | Exactly one PDF | Take it | No |
   | One PDF plus links/snapshots/notes | Take the PDF | No — this is the normal shape |
   | More than one PDF | Take the highest-priority one, list all of them | **Yes** — one is likely a supplement, appendix, or old version |
   | Only a `linked_file` PDF | Cannot download; its bytes never left the original machine | `PDF_MISSING` |
   | No PDF at all | Nothing to fetch | `PDF_MISSING` |

   Multi-PDF warnings go in the manifest's `warning` column (persisted, not just printed) and are
   summarized at the end of a run — scoped to the records *that run* touched, not the whole manifest, so
   a `--set human_labelled` run doesn't dredge up the Unlabelled Set's old warnings. `--list-warnings` prints
   every warning on file, across every set and past run, without fetching anything. They do not block
   the paper — identity verification (step 1) is the net that catches a wrong pick.

   **Scope: the study papers live in one Zotero collection** — group `Glykos`, collection
   `Boring Task` (both are the literal names in Zotero). The labeled HLS papers are **not**
   in it and arrive by a separate route (open question 1). The `--set` flag both tags the
   rows a run writes and picks the destination directory — `data/raw_pdfs/Unlabelled Set/` or
   `data/raw_pdfs/Human Labelled Set/` — since Zotero records nothing about the split; it is a property of which
   collection you point at. Those directories exist to make the split visible at a glance; the manifest's
   `set` column stays authoritative, and every other attribute (`verdict`, `folder`, `status`) is a
   manifest filter, never a directory.

   **Cross-set duplicate check, once both sets are fetched.** The two sets come from different
   Zotero groups, so the same physical paper can land in both with two different `paper_id`s —
   `paper_id` can't catch it. Cross-check `set=unlabelled` vs `set=human_labelled` manifest rows by normalized
   DOI/PMID/PMCID (PDF md5 as a fallback for records missing all three). If a paper appears in both:
   drop it from the Unlabelled Set, keep it in the Human Labelled Set — it already has a human label, so classifying it
   blind in the corpus wastes a call and risks a leaked-label sanity check.
   **Claude: surface any overlap found to the user for a decision before starting the promptbook loop or any
   classification run — do not resolve it silently.**

1. **Verify identity** — DONE, `scripts/01_verify_identity.py` + `src/identity.py`. Light PyMuPDF
   extraction of the **first 2 pages only**, then rapidfuzz-compare title / first author / DOI against
   the Zotero metadata:

   **Measured on the corpus (2026-08-10): 2041 VERIFIED (98.9%), 3 WEAK, 18 MISMATCH, 1 unreadable.**
   Of the VERIFIED, 1989 passed on DOI and 52 on title+author (accepted manuscripts carry no DOI).
   Full per-signal detail in `results/01_corpus_build/identity_report.csv`; verdicts also land in the manifest's
   `verdict` / `verdict_reason` / `title_score` columns.

   **A title match is not proof on its own — check `title_pos`.** Title similarity searches all of
   pages 1-2, reference lists included, so a paper that merely *cites* the target scores 100.
   `AULRV66J` does exactly this: a different Ophthalmology article whose reference list contains the
   Zotero title at 64% of the way down the text. Author matching is what caught it (0/12 authors).
   `title_pos` records where the match landed (0=top, 1=end) precisely so this is visible during
   triage — genuine papers sit at 0.00-0.02, that one sits at 0.64.

   Three things the build measured that changed the original design:
   - **The last page is not extracted.** It contributed zero DOI hits that pages 1-2 had not already
     found, while adding reference-list DOIs that only create noise.
   - **PMID/PMCID are not used.** They appear in the text of 1% and 0% of PDFs respectively — Zotero
     holds them, the documents do not print them. DOI is the only usable objective identifier (95%).
   - **`author_frac` is recorded but never gated on.** Consortium papers list 30+ authors whose names
     run past page 2, so a low fraction is normal and meaningless. First-author presence carries the
     author signal instead.

   **A grant-paperwork check blocks before any other rule.** The corpus really does contain NIH/PCORI
   summary statements and study-section review sheets filed where the article should be. Title
   similarity cannot catch them — a grant and the paper it funds share a title, and the PI is usually
   the first author, so they score 96+ and pass the author check; two were VERIFIED on those grounds
   before the rule was added. Three header phrases ("privileged communication", "summary statement",
   "resume and summary of discussion"), matched only in the first 1500 characters, flag 12 documents
   with zero false positives. Weaker candidates were tested and rejected: "principal investigator:"
   hit 8 papers of which 7 were genuine, "consort-ehealth" hit 6 of which 3 were real papers citing
   the checklist.
   - `VERIFIED` — enters the corpus.
   - `WEAK` — enters flagged; identity is re-checked at classification time (see below).
   - `MISMATCH` / `PDF_MISSING` / `PDF_UNREADABLE` — **blocked, no API call.** A sentinel row is written
     so the paper surfaces in results instead of vanishing, and it is excluded from accuracy math rather
     than scored as a miss:
     ```
     [[CORPUS_ERROR: PDF_MISSING | paper_id=4XKQ7B2M | folder=NCI | doi=10.1001/... ]]
     [[CORPUS_ERROR: METADATA_MISMATCH | paper_id=7QP2LM4X | title_score=41 | doi_hit=false ]]
     ```
   A valid DOI in the text that differs from the Zotero DOI is a hard `MISMATCH` regardless of title
   score — that is the signature of the wrong PDF on the right record. Thresholds are provisional;
   calibrate them on the Human Labelled Set before trusting them on the 1306.

   `author_frac` needs **every** author surname, so it reads from `data/zotero_meta.jsonl` via
   `load_meta()` — the manifest only carries `first_author`.

   **`WEAK` papers get their identity checked once, on the exclusion task only** — not four times.
   Prepend the Zotero metadata to that one prompt and add `metadata_mismatch: bool` to the schema. A
   paper flagged there gets the `METADATA_MISMATCH` sentinel and never reaches the other three tasks.
   Doing it on every task would repeat the same check four times and mix an identity question into
   promptbook-driven judgments, which the "never conflate tasks" rule exists to prevent.

2. **Extract** — DONE, `scripts/02_extract_pdfs.py`. Full text for `VERIFIED` papers only (which
   includes every `WEAK` paper resolved in step 3, since the review GUI writes their verdict back as
   `VERIFIED`). PyMuPDF primary, pdfplumber fallback, pytesseract only on exception. Cached to
   `data/extracted_text/{paper_id}.json`. Parsed once per paper, ever.

   **Driven off the manifest, not a directory listing.** MISMATCH and DROPPED papers are still sitting
   in `data/raw_pdfs/`, so a glob would extract exactly the files step 1 exists to keep out.

   **Measured on the corpus (2026-08-12): 1856/1856 extracted by PyMuPDF in 60 seconds.** Zero OCR, zero
   failures, zero pages without a text layer. 100,245,032 characters (~25M tokens), median 51,713 per
   paper. Only two fall under 3,000 characters and both are genuinely short documents rather than broken
   extractions — `NBBD4EVE` is a Corrigendum, `A3H3NDHF` an Erratum. Per-paper detail in
   `results/01_corpus_build/extraction_report.csv`.

   **OCR is dead code here, and that is worth knowing.** Not one PDF in the corpus needs it; Tesseract is
   not installed on the build machine. The rung stays for future fetches, but it now records *why* it
   failed (missing binary vs. unreadable scan) instead of silently returning sparse text.

   **Correction notices are screened out here, by title.** Journals index an erratum or retraction as
   its own record with its own DOI, so Zotero holds it and identity verification passes it — the PDF
   really is the document the record names. It is still not a study. `identity.looks_like_correction()`
   matches seven markers (`erratum`/`errata`, `corrigendum`, `correction`, `retraction`/`retracted`,
   `withdrawn`, `addendum`, `expression of concern`) **anchored to the start of the title** and followed
   by the separator a notice always uses.

   The anchoring is the whole rule. Matching those words anywhere in a title throws away real papers:
   this corpus contains "Reentry from **Corrections** to Community Treatment" and "Neonatal Opioid
   **Withdrawal**", both genuine trials. Measured over all 1,856 titles the anchored form flags 4
   documents and every one is a real notice. It deliberately errs toward missing one — a journal that
   marks a retraction only in the body will slip through, which costs far less than dropping a study.

   Size cannot do this job: `AT7F9XWR` is a correction notice running 5,513 characters, past any
   thinness threshold that does not also flag legitimate short reports.

   Flagged papers are appended to `results/review/01_papers_to_review.csv` as `CORRECTION_NOTICE` and
   dropped by hand in step 3, so each exclusion carries a recorded human decision.

   **Text only — no table grids.** Measured against pdfplumber's `extract_tables()` and PyMuPDF's
   `find_tables()`: journal tables are unruled, so line-based detection finds nothing, and text-based
   detection slices a two-column page into a fake grid that shreds the surrounding prose. Plain
   `get_text()` already preserves reading order *inside* a table, linearizing it into label→value runs
   that survive multi-arm headers (`Usual care (n = 992)` stays attached to its column). Spot-checked on
   20 papers with multi-arm Table 1s: all 20 keep arm labels. If power/data_analysis later turn out to
   miss table content, the move is `pymupdf4llm`, not pdfplumber grids.

2b. **Scan the cached text for bad parses** — `scripts/11_scan_text_integrity.py`. Offline, no
   re-parsing. Seven checks, in report order: **F1** mojibake, **F2** a second `Abstract` heading
   *after* the first reference list (two articles in one PDF), **F3** no reference marker anywhere
   (extraction stopped early), **F4** chars-per-page under 40% of the corpus median, **F5** full text
   shorter than 3x the Zotero abstract, **F6** under 60% letters (font-encoding failure), **F7** over
   30% duplicate lines (headers swamping the body).

   **Measured 2026-08-25: 48 of 1772 flagged, 4 genuinely wrong documents.** All 4 are Unlabelled Set
   and all passed identity on `TITLE_AUTHOR_MATCH` — a submission form carries the paper's own title
   and first author, so title+author matching cannot catch it. `J2RUD3YQ` was a conference-abstract
   submission; `FRIPQN6I`, `GY63DGR9`, `Y2SLUV8T` are CONSORT-EHEALTH forms printed from Google Forms.
   Listed in `results/review/11_text_integrity_flagged.csv` for replacement or drop.

   The other 44 are false positives, and the thresholds were tuned against them: counting `Abstract`
   twice flagged 70 papers (journals print "Abstract (continued)"; reference lists cite conference
   abstracts; "to abstract data" is a verb), and "ends without a full stop" flagged 257 (papers end on
   a Wiley licence footer). The 12 remaining F4 papers are accepted manuscripts in double-spaced
   repository layout — legitimately thin per page.

   **This vindicates a rule step 1 rejected.** `consort-ehealth` was tested as a header phrase and
   dropped for hitting 6 papers of which 3 were real. Those 3 false positives cost 3 true positives —
   exactly the documents found here.

3. **Review the flagged PDFs by hand** — `scripts/03_review_mismatches.py`, a small tkinter window that
   walks `results/review/01_papers_to_review.csv` one paper at a time. Each screen shows what step 1
   found, opens the PDF, the DOI, PubMed, and the Zotero record, and offers four choices: **No Issue**
   (the PDF really is the paper), **Replace PDF…** (pick the correct file, usually saved out of Zotero),
   **Drop** (no correct PDF exists), or **Skip**.

   Runs alongside step 2, not before it — extraction only touches `VERIFIED` papers, so the two never
   contend for the same rows.

   **A replacement is re-verified the moment it is chosen**, using the same `src/identity.py` ladder, and
   the window says whether the new file passes before you move on. Guessing at an attachment is cheap;
   discovering weeks later that the guess was wrong is not.

   Decisions write straight through to `data/zotero_manifest.csv` (`verdict` becomes `VERIFIED` /
   `DROPPED`, `verdict_reason` becomes `MANUAL_OK` / `MANUAL_REPLACED` / `MANUAL_DROPPED`) — a decision
   that stopped at the log would not change what gets classified. They are also appended to
   `results/review/04_papers_reviewed_results.csv`, which is the audit trail of who decided what and why.
   Replaced PDFs are backed up to `data/removed_pdfs/replaced/` first, so no original is destroyed.

   Saves on every click and reopens at the first undecided paper, so the queue can be worked in short
   sittings.

4. **Ground truth** — `src/db.py` + `scripts/04_load_ground_truth.py`. Loads every `GroundTruth*.xlsx`
   into SQLite and records the split as a column, so it is fixed once and cannot drift between runs.
   **NCI is loaded (230 rows); NHLBI's labels have not arrived yet, so the split is not yet assigned.**

   **The join is the hard part, and it is why this is a script and not a spreadsheet import.** The
   labels identify papers the way a reference list does — `83. (Hershman, Bansal, Barlow, et al., 2023)`
   — with no DOI, no PMID, no Zotero key. The citation is parsed back to (first author, year) and matched
   against `zotero_meta.jsonl`, scoped to that file's own collection so a common surname cannot collide
   with an unrelated paper in another institute's folder:

   | Rule | How | Result on NCI01 |
   |---|---|---|
   | first author + year is unique | direct index lookup | 216 |
   | two papers share both | APA extends the citation one author at a time, so compare the extra names by **position**, not membership — same research group, same names, different order | 14 |
   | neither works | `results/review/05_label_match_review.csv` | 2 |

   Position is what makes rule 2 work: `(Harry, Asche, …)` and `(Harry, Chrenka, …)` are the same lab, and
   both surnames appear on both papers — only the *second author slot* differs.

   The 2 leftovers are `(Patterson et al., 2022a)` / `(2022b)`: the suffix means the labeller could not
   tell the two apart by author and year either. One candidate is a `Correction to:` notice and the other
   the article it corrects, which is a corpus question, not a matching one. **Nothing is ever guessed** —
   a wrong label silently corrupts every accuracy number computed afterwards, so unresolved citations go
   to a human and stay out of the database.

   Label columns map onto the three tasks: `Reason excluded` → exclusion, `Power` → power_analysis,
   `Stats` → data_analysis. `Review Category` maps to nothing and is read by nothing (DC31).
   The 347/176 split across all 523 labels confirms the gate (136/96 on NCI alone) — only
   papers the humans kept carry power/stats labels, exactly as `expected_decision()` assumes.

5. **Promptbooks** — three independent markdown files, one per task. Never merged, never
   cross-referenced.

   **Versioned by directory, not just by commit.** A judgment records
   `promptbook_version`, so a rule that changes under a fixed version makes every earlier
   judgment unreproducible. Each version is a frozen directory; editing one in place is the
   thing this layout exists to prevent.

   ```
   promptbooks/
     CURRENT              one line: the active version, e.g. "v0"
     _TEMPLATE doc.md     copy this into each new version
     v0/
       exclusion.md  power_analysis.md  data_analysis.md
       v0 doc.md          what changed, why, which papers, what it scored
     v1/  v2/  ...
   ```

   **To change a rule:** copy `vN/` to `vN+1/`, edit there, update `CURRENT`, fill in the new
   version's doc, commit. One commit per version bump, with the accuracy delta in the message.

   **`vX doc.md` is the human record; the CSV is the machine record.** The doc is tables only
   (no prose): what changed and why, the paper_ids each rule was written against, and every
   round run against that version with its accuracy, `undecidable` rate, `wrong_text` rate and
   parse-retry count. Every number in it must match a row in
   `results/04_classification/promptbook_accuracy_history.csv`, which is what gets plotted and
   cited — the doc explains, the CSV counts. DC23's other half lives here too: a miss with no
   pattern behind it is logged in the doc's "misses not generalized" table rather than written
   into a rule.

   Each promptbook opens with the same two-paragraph documentation rule — rules are numbered
   lines, rationale goes in the version doc, and a frozen version is never edited.

6. **Promptbook loop** — `src/promptbook_builder.py`, one task at a time, using **Opus** via forced tool-use:
   load promptbook -> sample <100 unreviewed papers **from the build split** -> judge -> compare to the SQLite label
   -> log every result -> on a miss, hand-write or have Opus propose (for review) a generalized rule or
   worked example, append it to that task's promptbook, commit with the accuracy delta in the message.
   Opus is worth the cost here: one-time, low-volume, high-stakes, and it shapes the promptbook Sonnet
   relies on for the cheap full run.

   **Option: run the promptbook loop through the Claude Code CLI instead of the API, to spend subscription
   quota rather than API credits.** `claude -p "<prompt>" --output-format json` runs headless and
   authenticates off the subscription login. A small script walks `data/extracted_text/*.json`, pipes
   each paper's text in with the current promptbook, and writes one response JSON per paper to a new
   directory for hand-inspection. Only for promptbook refinement — the full run stays on the Batches API
   (see the standing rule). Two trade-offs to accept if we go this way: no forced `tool_choice`, so the
   prompt has to ask for JSON and the wrapper validates with pydantic and re-prompts on a parse failure;
   and one process per paper, so no prompt caching and it runs slower. Fine at <100 papers a round.

   **Decided: the CLI carries the promptbook loop's scored numbers too, not just its drafts.** The cost
   is a known one — **log every parse failure and retry, with paper_id and attempt count.** Retries are
   not randomly distributed: a paper that makes the model hedge or wrap its JSON in prose is usually a
   genuinely borderline paper, so retries land on exactly the cases the accuracy number is most
   sensitive to. Logged, that is a measurable rate to report beside accuracy; unlogged, it is an
   invisible bias in the direction of the study's own subject matter. Report the retry rate in the
   methods section.

   **Label leakage must be blocked structurally — `claude -p` is agentic, not a completion endpoint.**
   Run inside the repo it has file tools, and `data/ground_truth.csv`, `data/review.db`, and an
   auto-loaded CLAUDE.md naming both are right there. Telling it not to look is not a control. Four rules,
   enforced by the wrapper:
   - **Run from a scratch directory outside the repo** — no CLAUDE.md, no memory index, no relative path
     to the answers resolves. Never `--add-dir` the repo.
   - **No tools, one turn** (`--max-turns 1`, empty allowed-tools) — makes it a pure text completion,
     behaviorally identical to an API call.
   - **Text on stdin, never a file path.** Write outputs outside the scratch cwd, so one paper's response
     is not readable by the next.
   - **Blind the identifier** — send a random token, keep the token→`paper_id` map in the wrapper, so a
     leak is not lookup-able even if one happens.

   Verified three ways: `--output-format stream-json` logs every `tool_use` block, so assert zero per
   paper and discard any run with one; a canary run of ~20 papers against a decoy `ground_truth.csv` with
   flipped labels and tools deliberately *on* (accuracy tracking the decoy proves it is reading, not
   reasoning); and the holdout, run once via the API, which does not depend on trusting the loop at all.

   Each invocation is independent — fresh process, no shared history — unless `--resume`, `--continue`,
   or a reused `--session-id` is passed. Don't.

7. **Regression** — `src/evaluate.py` re-runs the current promptbook against the whole build split, computes
   accuracy/precision/recall, appends to `results/04_classification/promptbook_accuracy_history.csv` with the commit hash.

   **Plateau = two consecutive rounds each improving accuracy by less than 1 percentage point.** Then
   stop and move to step 7.

   **A new rule needs a pattern, not a paper.** A new promptbook rule needs a **pattern** behind it — several similar misses, never a single paper. A promptbook rewritten hard against one disagreement encodes noise from that sample instead of a general rule, and the rounds are under 100 papers. Collect the
   round's misses, find the repeated shape, write the rule against that; log a one-off rather than
   generalizing it. Track the `undecidable` rate alongside accuracy: a rate that climbs while
   accuracy holds means the promptbook is teaching the model to abstain rather than to judge.

8. **Sonnet check** — once a promptbook plateaus on Opus, re-run the build split with **Sonnet** and record that
   accuracy alongside. The promptbook was shaped by Opus's reasoning; if Sonnet is materially worse, tighten
   the promptbook for Sonnet before spending on the full run. Skipping this means discovering the gap after
   thousands of calls.

9. **Two-pass tuning** — `src/two_pass.py`: Sonnet everywhere, anything under the confidence threshold
   routes to Opus. Tune the threshold **on the build split**, once all four promptbooks have plateaued and passed
   step 7.

10. **Gate run** — batch job 1: exclusion across all 1306 (1306 calls), Opus second pass on
   low-confidence calls, then apply the gate (`keep`). Record the survivor count and the
   drop reason per paper — this is a study result in its own right, not just plumbing.

11. **Analysis run** — batch job 2: power_analysis + data_analysis across the survivors only, same
    two-pass. Merge in SQLite/pandas and export.

12. **Holdout** — run the holdout once, end to end, with the exact production config. Report that number.

## Phase order

**Do not parallelize across tasks.** Take `exclusion` to a plateau before touching `power_analysis`,
then `data_analysis`.

- [x] Repo, `requirements.txt`, `.env`, git init
- [x] `src/pdf_extract.py` — two-stage: `extract_head_text()` for identity, `extract_pdf_text()` for the full pass
- [x] `src/zotero_fetch.py`, `scripts/00_fetch_zotero.py` — fetch + md5 check + manifest + metadata
- [x] Dry-run the fetch, confirm the collection tree resolves, then pull the study papers
- [x] Settle where the HLS PDFs come from and fetch them with `--set human_labelled` — 569 fetched
      (232 NCI + 337 NHLBI)
- [x] Cross-check US vs HLS for duplicate papers (DOI/PMID/PMCID); flag any overlap to the
      user before proceeding
- [x] Identity verification (`01_verify_identity.py`) — thresholds calibrated, verdicts in the manifest
- [x] Cross-set duplicate check — 207 US papers also in the HLS; removed from the US
      (1494 → 1306), logged in `results/review/02_removed_us_duplicates.csv`
- [x] **Decide the 15 NCI↔NHLBI duplicate pairs inside the HLS.** Resolved by
      `scripts/04_load_ground_truth.py`, not by a manual decision: 9 pairs agree on every label and are
      collapsed to one `validation_labels` row automatically; 6 disagree — one pair a complete flip
      (NCI: both analyses correct; NHLBI: both incorrect). Both sides held out, never silently
      preferred, in `results/review/05_label_match_review.csv`.
- [x] **Institutional disagreements dropped, assumed unresolved.** 5 of the 6 (one resolved once
      Patterson's ambiguity closed). Fully dropped from the active corpus, not just held out of the
      labels — `scripts/12_drop_institutional_disagreements.py` (DC37). May be restored if adjudicated.
- [x] Triage the 24 flagged papers with `scripts/03_review_mismatches.py` — 20 PDFs replaced, 4 marked
      fine, none dropped. Audit trail in `results/review/04_papers_reviewed_results.csv`
- [x] Rewrite `scripts/02_extract_pdfs.py` for two-stage extraction; extract `VERIFIED` (1856 papers,
      all by PyMuPDF, no OCR)
- [x] `src/db.py` — labels + append-only judgments schema, with the split guard
- [x] Load the ground truth into SQLite (`scripts/04_load_ground_truth.py`, rewritten to read
      `data/ground_truth.csv` rather than parse a spreadsheet itself) — 523 papers in
      `validation_labels`; `--assign-split` now hard-refuses while any active HLS paper still
      lacks a label (`--allow-incomplete` overrides deliberately)
- [x] **Resolved `(Patterson et al., 2022a)` / `(2022b)`.** One real paper, `IT2B87LL`; the join now
      skips `MANUAL_DROPPED` candidates like `JBUFJCLU` so the suffix resolves on its own. `IT2B87LL`
      itself was then dropped as `duplicate_group_random_drop` — a coin-flip exclusion the model can
      never reproduce (E17) — so the whole pair is out of the study.
- [x] Merge every label file into `data/ground_truth.csv` (`scripts/07_build_ground_truth.py`) —
      569 rows, 567 joined to paper_ids; NCI 2×2 reproduces the published 20/11/5/60. Also fixed here:
      15 NHLBI citations were resolving to a paper_id `06_merge_hls_duplicates.py` had already
      retired (the join reads `zotero_meta.jsonl`, which the merge script never prunes) — now remapped
      to the surviving paper_id, logged in the `paper_id_note` column.
- [x] **The 23 unlabeled NHLBI papers are dropped, not chased.** `scripts/09_drop_unreviewed_nhlbi.py` —
      manifest verdict `DROPPED`, files moved to `data/removed_pdfs/nhlbi_unreviewed/`, logged in
      `results/review/09_nhlbi_unreviewed_dropped.csv`. Active Human Labelled Set: 553 → 530.
- [x] **Batching scheme settled** — 30% holdout **stratified on gate-survivor status** (~53 survivors
      held out, guaranteed rather than left to the hash); promptbook rounds sample 50 from the build
      split. `assign_split()` still needs the stratification implemented before it is run.
- [x] Exclusion ledger (`scripts/05_build_exclusions.py`) — every departed paper with its reason and
      who decided; reconciles 2063 fetched → active corpus (`--check` for the current count)
- [x] `promptbooks/v0/exclusion.md` — 17 criteria, prompt block, `wrong_text` decision added. Deb has
      confirmed E13 and the protocol-citation rule; E3/E5/E12/E17 still await her sign-off (O1).
- [x] **Extracted-text integrity scan** (`scripts/11_scan_text_integrity.py`, step 2b) — 45 of 1772
      flagged, 4 genuinely wrong documents found: 3 replaced and re-extracted, 1 dropped
      (`J2RUD3YQ` — no full text exists, only a conference-abstract supplement; DC43).
- [x] **`NBBD4EVE`'s parent found and confirmed out of scope** — does not belong in the study (DC38).
- [ ] Promptbook loop on exclusion against the build split until plateau; Sonnet check
- [ ] Same for power_analysis, then data_analysis
- [ ] Tune the two-pass confidence threshold on the build split
- [ ] Gate run (job 1), record survivors
- [ ] Analysis run (job 2) on survivors
- [ ] Holdout run — report this number

## The Reading Room

The isolated harness the promptbook loop runs in. Named for what it is: a sealed room where a
reviewer is handed exactly one paper, may not bring anything else in, and hands back exactly one
filled-in form. Nothing else enters or leaves.

**It exists because `claude -p` is agentic, not a completion endpoint.** Run inside this repo it has
file tools, and `data/ground_truth.csv`, `data/review.db`, and an auto-loaded CLAUDE.md naming both
are sitting right there. Telling it not to look is not a control; removing the ability to look is.

### The four walls

| Wall | How | What it stops |
|---|---|---|
| **Empty room** | `cwd` is a scratch directory outside the repo. Never `--add-dir`. | No CLAUDE.md, no memory index, no relative path to the answers resolves |
| **No hands** | `--max-turns 1`, empty `--allowed-tools` | Makes it a pure text completion. It cannot read a file even if it decides to |
| **Paper by hand** | Text on **stdin**, never a path. Output captured from stdout, written by the wrapper outside the scratch cwd | One paper's response is not readable by the next |
| **No name** | Send a random token; the wrapper keeps token → `paper_id` | A leak is not lookup-able even if one happens |

The wrapper writes the JSON, not Claude. That removes the whole class of "did it corrupt the output
file" failure, and it means the model has no write target to be confused about.

### Two scripts

**`scripts/20_reading_room.py`** — runs one round. Reads `promptbooks/CURRENT`, samples from the
build split, and for each paper spawns one `claude -p` process with the promptbook and the paper
text on stdin. **Papers are judged one at a time, never batched into one prompt**: ten papers in one
context would let the model make exactly the cross-paper judgments E12 and E17 forbid, and position
effects inside the batch would contaminate the accuracy number. Speed comes from running 5-8
processes concurrently, which buys the same wall-clock and none of the contamination.

**`scripts/21_check_responses.py`** — validates what came back, before any of it is scored. In
order: exit code → **zero `tool_use` blocks** in `--output-format stream-json`, and discard the
whole run if any appear → JSON parses, recording whether fence-stripping was needed → pydantic
(`src/schemas.py`) → `decision` in the allowed set, `wrong_text` only on exclusion → `reasoning`
within 200 characters → `promptbook_evidence` cites a rule ID that actually exists in the promptbook
in force → `confidence` in [0,1] and not constant across papers → the blinded token echoes back.
Failures go to a retry ledger (`paper_id`, attempt, failure kind), which is DC24's reportable number.

### Reproducible procedure, not reproducible bytes

Never pass `--resume`, `--continue`, or a reused `--session-id`; each invocation must be a fresh
process with no shared history. Pin the full model ID, `--strict-mcp-config` with no servers, and a
committed `--settings` file. Point `CLAUDE_CONFIG_DIR` somewhere empty so no user-level CLAUDE.md or
memory loads.

**The CLI exposes neither temperature nor seed**, so identical bytes are not achievable and claiming
otherwise would be false. What is achievable is a reproducible *procedure*: log the model ID, CLI
version, promptbook version (the git commit), and the verbatim raw response before parsing. That is
what a reader needs to re-run it, and it is what the run log already records.

### Verified three ways

1. `--output-format stream-json` logs every `tool_use` block. Assert zero per paper; discard any run
   with one.
2. **Canary run**: ~20 papers against a decoy `ground_truth.csv` with flipped labels, tools
   deliberately *on*. If accuracy tracks the decoy, it is reading rather than reasoning.
3. The holdout, run once through the Batch API, which does not depend on trusting the loop at all.

## Batch run log

**Every batch run writes a header row to `results/04_classification/run_log.csv` before it starts, and closes it when
it finishes.** A run nobody can date, price, or attribute to a model is not reproducible, and this is
the cheapest possible insurance against having to re-run 1306 papers to answer a reviewer.

```
run_id, task, started_at, finished_at, duration_s,
processing_type,        # api_batch | api_sync | cli
model,                  # claude-sonnet-5, claude-opus-5, ...
promptbook_version,     # git commit of the promptbook in force
n_papers, n_ok, n_undecidable, n_parse_retries, n_failed,
input_tokens, output_tokens, cost_usd,
split,                  # build | holdout | none (full corpus)
git_commit,             # of the repo, not just the promptbook
notes
```

`cost_usd` is null on a CLI run (subscription quota, not billed per call) — record
`processing_type` so a null reads as "not applicable" rather than "we forgot".
`n_parse_retries` is DC24's number and belongs here, not in a side file.

`started_at` is written **before** the first call, so an interrupted run still leaves a dated row
saying what was attempted.

## Erratum pass

**The erratum pass is Unlabelled-Set-only.** Four correction notices exist, all `DROPPED`:

| notice | set | parent | parent status |
|---|---|---|---|
| `A3H3NDHF` | US | `J9F7U6CX` | active |
| `AT7F9XWR` | US | `MPSTWIIE` | active |
| `NBBD4EVE` | US | *unknown* | **not found — see O6** |
| `JBUFJCLU` | HLS | `IT2B87LL` | **dropped, out of the study** |

The one Human-Labelled-Set notice no longer needs handling. Its parent `IT2B87LL` was the
`(Patterson et al., 2022a/b)` paper, and the humans had excluded that by random coin flip — a
`duplicate_group_random_drop`, which the promptbook forbids the model to reproduce (E17). So
`IT2B87LL` left the scored set with the other 41 nonjudgeable exclusions, and the whole pair is out.
Nothing in the HLS depends on a correction notice any more.

Run the remaining two as a small pass over the notice **plus its parent's full text**, so the
question "does this correction change the power or data analysis being scored?" is asked with both
documents in context. Two papers does not justify a batch job, and folding them into the main 1306
would ask the model to judge a correction notice as if it were a trial. `NBBD4EVE` waits on O6.

## Exclusion ledger

**Every paper that leaves the corpus must be recoverable with its reason.** The methods section has to
account for the path from 2115 raw placements to whatever number is finally analysed, and right now that
evidence is scattered across five files that share no schema:

| Stage | Where it lives now | Papers |
|---|---|---|
| Collection placements → unique papers | `results/01_corpus_build/unvalidated_set_summary.tex` | 2115 → 1494 |
| Cross-set duplicates (kept in the HLS) | `results/review/02_removed_us_duplicates.csv` | 207 |
| Wrong document / unreadable, dropped by hand | manifest `verdict=DROPPED` + `04_papers_reviewed_results.csv` | 2 so far |
| Correction notices | same route, `CORRECTION_NOTICE` in the review queue | 4 found |
| HLS internal duplicates | `results/review/03_hls_internal_duplicates.csv` | 15 pairs, undecided |
| Unjoinable labels | `results/review/05_label_match_review.csv` | 2 |
| Gate exclusions (model) | SQLite `judgments`, once the gate runs | unknown |

**Consolidate these into `results/01_corpus_build/exclusions.csv`**, one row per departed paper:
`paper_id, set, stage, reason, evidence, decided_by (rule/human/model), decided_at, source_record`.
Built by a script that reads the files above rather than maintained by hand — a ledger someone has to
remember to update is a ledger that is wrong by the time it matters.

Two rules this enforces:
- **A paper never leaves silently.** Dropping a row from the manifest would erase the evidence, which is
  why `DROPPED` is a verdict and not a deletion.
- **`decided_by` is not decoration.** A reviewer needs to know which exclusions were a human's judgment,
  which were a deterministic rule, and which were the model's — they carry very different weight in a
  methods section, and conflating them would be a fair criticism of the study.

## Judgment storage

SQLite, single file, via `src/db.py`. **One row per judgment, append-only** — a paper that goes to the
Opus second pass produces two rows, not an overwrite:

```
paper_id, task, judgment_index, pass_name, model_used, decision, reasoning,
promptbook_evidence, confidence, promptbook_version, timestamp
```

**`judgment_index`** — how many times this paper has been judged on this task, including the row it sits
on. First ever judgment of `4XKQ7B2M` on `exclusion` is `1`; its Opus review is `2`; a re-run after the
next promptbook edit is `3`, and so on. Counts across the whole project, not per run: promptbook-building rounds
re-judge the same papers repeatedly, and the total is the number you want when asking how much scrutiny
a paper has already received.

`UNIQUE(paper_id, task, judgment_index)` — this is the real payoff. It makes a double-write physically
impossible, so an interrupted batch can be resumed by replaying it without risking duplicate judgments
silently inflating the accuracy math.

Useful slices:
- Passes within one promptbook version: filter on `promptbook_version`, then read `pass_name`.
- Papers the model keeps struggling with: `judgment_index` high while `decision` keeps flipping.
- Current answer for a paper: highest `judgment_index` for that `(paper_id, task)`.

`pass_name` is `primary` or `review`. Keeping both rows is what lets you ask why Opus overturned Sonnet,
which promptbook rule each leaned on, and whether the disagreement clusters somewhere the promptbook is weak.
Overwriting would destroy exactly the evidence that makes the second pass worth paying for.

`promptbook_version` is the git commit hash of the promptbook in force at the time, so any judgment can be
traced back to the exact rules that produced it.

## Manifest

`data/zotero_manifest.csv` — one row per Zotero record, tracked in git (PDFs are gitignored; this table
is the reproducible record of what was pulled):

```
paper_id, folder, folder_path, title, first_author, doi, pmid, pmcid, year, journal,
attachment_key, md5, status, detail, warning, verdict, verdict_reason, title_score,
set, fetched_at
```

Rows are **merged on `paper_id`**, never overwritten wholesale — the HLS papers come from a
different source and share this file, so a study re-fetch must not delete them.

`verdict` / `verdict_reason` / `title_score` are filled by step 1
(`scripts/01_verify_identity.py`); the full per-signal detail behind them lives in
`results/01_corpus_build/identity_report.csv`. `set` is `unlabelled` (the study papers to classify) or `human_labelled` (the
human-labeled papers), set by the fetch's `--set` flag.

## Zotero metadata

`data/zotero_meta.jsonl` — one JSON object per record, written by the same fetch, merged on `paper_id`
the same way. Gitignored: derived data, re-creatable from Zotero, and large once abstracts are in it.

```json
{"paper_id": "4XKQ7B2M", "set": "unlabelled",
 "folders": ["NCI"], "folder_paths": ["Boring Task / NCI"],
 "zotero_version": 1423, "title": "...", "authors": ["Smith", "Jones", "Lee"],
 "first_author": "Smith", "doi": "10.1001/...", "pmid": "", "pmcid": "",
 "year": "2021", "journal": "...", "abstract": "...", "fetched_at": "...",
 "zotero_item": {"...": "Zotero's untouched JSON for this record"}}
```

Read it with `load_meta(path) -> {paper_id: record}` from `src/zotero_fetch.py`.

**PMID / PMCID: dedicated field first, free text second.** Recent Zotero added `PMID`/`PMCID` fields on
`journalArticle`, but older records and older connectors still keep them in free text, so
`parse_identifiers()` tries both, in priority order: the dedicated field, then `Extra` (`PMID: 123`,
with or without the colon), then `archiveID`, then the item `url` (`pubmed.ncbi.nlm.nih.gov/123`,
`/pmc/articles/PMC456`). Field values are run through the same patterns rather than trusted raw — a
"dedicated" field can still contain `PMID: 123`. PMCID is normalized to carry its `PMC` prefix, the form
PubMed and the labels file use. The fetch prints DOI/PMID/PMCID coverage at the end of a run — worth
watching, since these are what will join this corpus to the human labels.

`zotero_item` is the escape hatch — volume, issue, pages, ISSN, URL, tags, itemType and anything else
Zotero holds stay recoverable without re-pulling the library. `zotero_version` is what would enable an
`If-Modified-Since-Version` re-sync later instead of a full re-pull.

## Open questions

**1. Where do the 500 HLS papers and their PDFs come from?** They are *not* under *Boring Task*,
so the fetch script never sees them. Two things are unsettled: (a) where the PDFs live — another Zotero
collection/group, or a local folder; and (b) how `validation_labels.csv` keys them — almost certainly
DOI or PMCID, not a Zotero item key. If they come from Zotero, the same fetch code points at a different
collection and `paper_id` stays a Zotero key, joined to the labels by normalized DOI. If they come from
a folder, they need their own `paper_id` scheme and a metadata source for identity verification.
Blocks step 3.

Partially settled: the HLS PDFs live in Zotero, but split across **two separate groups —
NCI and NHLBI — each with its own group ID and collection key**, not one shared collection like
*Boring Task*. `00_fetch_zotero.py` fetches one `--collection` (and its subtree) from one group per
run, so pulling the Human Labelled Set needs **two runs**, one per group, both with `--set human_labelled` so
they merge into the same manifest rows rather than overwriting each other. `.env`'s
`ZOTERO_LIBRARY_ID`/`ZOTERO_COLLECTION_KEY` will need to point at each group in turn (or the script
extended to accept a library ID override alongside `--collection`).

**Settled for the PDFs.** NCI: group `5573699`, collection `V3822KC9` ("FinalCollectionFor
Publication", flat, 232 papers, no subcollections), fetched 2026-08-10 with `--set human_labelled`, zero
multi-attachment warnings. NHLBI: group `6363893`, fetched as `Locked_26_01_08_337`, **337 papers**.
569 HLS PDFs are on disk and all 569 are VERIFIED.

**Still open: the NHLBI *labels*.** Only `GroundTruthDataNCI01.xlsx` has arrived. Until NHLBI's
equivalent lands, 337 of the 569 HLS papers have PDFs but no human answer, so they can be
neither scored nor split. This is what blocks `--assign-split`.

**2. Do all HLS papers carry labels for all four tasks?** **No — and by design.** Measured on
NCI01: of 232 rows, 136 carry an exclusion reason and nothing else, and 96 carry Power and Stats.
That is the gate showing up in the ground truth exactly as intended — a paper the
humans excluded never got scored on power or stats — and `db.expected_decision()` returns `None` for
those, so they drop out of the denominator rather than counting as misses.

The consequence for the split is real though: a single 30% holdout drawn over *all* labeled papers
leaves only ~53 gate survivors to score power_analysis and data_analysis on, which is thin for a
headline accuracy number. Two options when the NHLBI labels arrive: stratify the split on
gate-survivor status so both tasks get a proportional holdout, or accept the wide interval and report
it. Decide before calling `--assign-split`, because it only runs once.

**3. Promptbook updates on a miss: manual or model-assisted?** Manual = you read the miss and write the
rule. Model-assisted = feed the miss + current promptbook to Opus and have it propose the edit. Faster, but
every proposed rule needs a spot-check before it is committed. Not yet decided.
