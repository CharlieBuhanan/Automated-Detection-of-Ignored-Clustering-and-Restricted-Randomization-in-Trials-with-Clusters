# Roadmap

Reference doc. Not loaded into context automatically — read when starting a new phase.
Standing rules live in [.claude/CLAUDE.md](.claude/CLAUDE.md).

## TODO now — human review, before continuing

**Start with `results/review/05_label_match_review.csv`** — 8 rows, covers items 2 and 3 below in
one file: each institute's answer is already spelled out, no PDF-hunting needed to see the shape
of the conflict (reading the actual paper is only needed to decide it).

- [ ] **Find the original paper for `NBBD4EVE`.** Missing from the corpus entirely — not a review-queue
      row. Detail under "Checklist — what's next" below.
- [ ] **Decide the Patterson papers** (`IT2B87LL` / `JBUFJCLU`). Two rows in the review file, one real
      paper — blocked on the correction-notice policy question (see the erratum item below). Deciding
      that question resolves this and item 4's third bullet together.
- [ ] **Adjudicate the 6 institutional disagreements** in the review file. NCI and NHLBI reviewed the
      same paper and reached different answers — one pair is a complete flip (NCI: both analyses
      correct; NHLBI: both incorrect). Read the paper, decide which institute's answer is right (or
      neither), and update `data/ground_truth.csv` or `results/review/05_label_match_review.csv`
      accordingly — there's no automated way to pick a side for these.
- [ ] **Other data checks before moving on:**
      - Read the 3 correction-notice pairs' PDFs for power/stats impact — same question as items 1–2.
      - Re-run `python scripts/05_build_exclusions.py --check` after any of the above changes anything.
      - Confirm the A/B/C/D definition is still with Dr. Glueck. (The 23 outstanding NHLBI reviews are
        no longer waiting on anyone — dropped, see below.)

## Checklist — what's next

Corpus prep is **done**: 1814 active papers (1284 testing + 530 validation), all extracted and cached.

- [ ] **Request `Ignore03_NHLBI.bib` from the NHLBI team.** The extraction table cites it, but the
      bundle shipped `references.bib` instead — the manuscript's own bibliography, which contains none
      of the 159 cite keys. The right file carries DOIs and would make the NHLBI join exact instead of
      fuzzy. Not blocking (all 337 NHLBI rows already resolve), but it would remove the fuzzy step.
- [ ] **Get the definition of NCI's `Review Category` A/B/C/D.** `A` is provably "data analysis
      correct" (all 31 `A` rows have `Stats = YES`, no other category does), and B/C/D are three
      flavors of incorrect — but they are *not* the SAS `ignored_data_c` strata, which split the same
      65 papers 14/26/25 rather than 19/33/13. Until the letters are defined,
      `db.expected_decision()` cannot map them: it currently returns the raw letter as the expected
      answer for `inclusion`, where the model returns yes/no, so the two can never agree.
- [ ] **Decide the validation/build batching scheme.** Earlier drafts assumed round numbers
      (350 / 150) that predate counting what is actually on disk. Settle, in this order: how the 523
      labeled papers divide into build and holdout; whether the split is stratified on gate-survivor
      status (open question 2 — a flat 30% holdout leaves only ~29 survivors to score power and data
      analysis on, which is thin for a headline number); and what per-round sample size the rubric loop
      draws from the build split (CLAUDE.md currently says under 100). All three have to be fixed
      before `--assign-split`, because it only runs once.
- [ ] **Resolve `(Patterson et al., 2022a)` / `(2022b)` — low risk, and now precisely scoped: only
      one real corpus paper is affected, not two.** The two citations point at `IT2B87LL` (the article,
      "A cluster randomized controlled trial for a multi-level, clinic-based smoking cessation program")
      and `JBUFJCLU` (`Correction to:` that same article) — and `JBUFJCLU` is already `DROPPED` from the
      manifest. APA only appends `a`/`b` when two references share an author and year, so the suffix is
      the labeller recording that *they* could not separate them either — nothing in the citation
      decides it, and `07_build_ground_truth.py` leaves both in
      `results/review/07_ground_truth_unjoined.csv` rather than guessing. The reason it still can't be
      resolved automatically is that the join reads `zotero_meta.jsonl`, which still lists `JBUFJCLU` as
      a live candidate — `06_merge_validation_duplicates.py`'s DROPPED verdict lives only in the
      manifest and was never propagated back to the metadata the join actually searches.

      **Both label rows carry identical labels** — `excluded`, reason `random` ("second study by same
      group, excluded randomly"), no Power/Stats/Category — so this is a counting problem, not a
      correctness one, and does not block `--assign-split`.

      **The fix, once decided:** teach the join to skip any candidate whose manifest `verdict` is
      `DROPPED`, so only `IT2B87LL` remains and the ambiguity resolves on its own. Held until the same
      policy question as the erratum item below is answered: whether `Correction to:` notices belong in
      the corpus at all.
- [ ] **Write `rubrics/exclusion.md` v0.** Nothing blocks this — start with "exclude if secondary
      analysis". Only the scoring loop needs step 4.
- [ ] **Decide on the extracted-text integrity scan.** 100M characters have never been checked for
      anything but length: mojibake, multi-article PDFs, and truncation are all still unmeasured.
- [ ] **Decide how an erratum affects its parent paper's power/data analysis.** Dropping the notice keeps
      the corpus clean, but the correction itself may change the very numbers being judged — an erratum
      that fixes a sample size, a test statistic, or a p-value makes the *uncorrected* article wrong on
      exactly the criteria this study scores. Three papers are affected, each with its correction now
      dropped and its parent still active:
      `A3H3NDHF` → `J9F7U6CX`, `AT7F9XWR` → `MPSTWIIE`, `JBUFJCLU` → `IT2B87LL`.
      Read the four notices, see whether any touch power or statistics, and decide whether the parent's
      extracted text should carry the correction appended, be re-fetched as a corrected version, or be
      judged as published. Record whichever rule is chosen — a reviewer will ask.
- [ ] **Find the original paper for `NBBD4EVE`.** It is the one dropped correction whose parent is *not*
      in the corpus: "Corrigendum: Analysis of cluster-randomized test-negative designs: cluster-level
      methods" (best title match against the active corpus scored only 73). Either the article was never
      fetched or it sits under a different title. Locate it, and if it belongs in the study, add it to
      Zotero and re-fetch — otherwise record why it is absent.

**Re-running `00_fetch_zotero.py --set validation` undoes the duplicate merge** — the 15 removed NHLBI
rows are gone from the manifest and their PDFs are moved aside, so `completed_ids()` no longer skips them
and they come back. Re-run `scripts/06_merge_validation_duplicates.py` afterwards; it is idempotent and
skips pairs already merged.

## Goal

Rate scientific papers on **power_analysis** and **data_analysis** correctness, after filtering the
corpus with **exclusion** and **inclusion** criteria. **1287 study papers** to classify; a separate
human-labeled validation set.

**The corpus is 1287 papers.** 2115 counted *collection placements*, not papers — 483 papers are filed
under two or more NIH institutes. Full reconciliation (2115 raw → 2113 paper-placements → 1494 unique)
is in `results/unvalidated_set_summary.tex`. Also excluded: `sample NCI-new` (104 papers, disjoint from
every other collection) and one non-article item (a `videoRecording`). The last 207 came off in the
cross-set duplicate check — papers already sitting in the validation set with a human label
(1494 → 1287).

**569 validation PDFs were fetched; 530 are active in the corpus and 523 carry one clean label.**
`FinalCollectionFor Publication` (NCI) held 232 and `Locked_26_01_08_337` (NHLBI) held 337. NCI's
ground truth is complete (`GroundTruthDataNCI01.xlsx`, 232 rows). NHLBI's arrived in two disjoint
files that together covered all 337: `crt_review_table_112.tex` (159 papers taken to full
extraction) and `NHLBI_exclusions_178.csv` (178 rejected before extraction). The remaining 23 tex
entries were cited but never judged and will not be — dropped by
`scripts/09_drop_unreviewed_nhlbi.py`, not waited on. Of the 530 active papers, 7 are held for a
human rather than loaded blind: 6 institutional disagreements and 1 unresolved citation. Every
"500 / 350 / 150" figure in earlier drafts predates counting what is actually there.

All three label files are merged into `data/ground_truth.csv` by `scripts/07_build_ground_truth.py` — a
wide union of the three source schemas, one row per validation paper, 567 of 569 joined to a `paper_id`.
Source strings are preserved in `*_raw` columns beside their normalized forms. The sources and every
quirk found in them are documented in
[Ground Truth Raw/NOTES.md](Ground%20Truth%20Raw/NOTES.md).

The criteria have real nuance — many things, including rare events, can make a paper "incorrect power
analysis." The rubrics are built empirically from validation misses rather than written up front.

## Study design

Three decisions shape everything below.

**The corpus is gated, not classified wholesale.** Exclusion and inclusion run first, on all 1287. Only
survivors go to power_analysis and data_analysis. A paper proceeds only if exclusion says *keep* **and**
inclusion says *include* — either one dropping it is enough to drop it.

**Power/data correctness is only meaningful for papers that pass the gate.** A dropped paper gets no
power_analysis or data_analysis row at all — not a null, not an "N/A" decision, no row. This applies to
the validation set too: build the power/data rubrics only on validation papers that pass the gate, and
compute their accuracy over that subset. Scoring a paper the study would have thrown out measures
nothing.

This is **not** the flat `2115 x 4 = 8460` figure that earlier drafts used — wrong on both counts, the
paper count and the gating. The real shape is two sequential batch jobs:

```
job 1:  1287 x 2 (exclusion, inclusion)      = 2574 calls
        + Opus review of low-confidence gate calls
job 2:  <survivors> x 2 (power, data)        = 2 x however many survive
```

Survivor count is unknown until job 1 finishes; it determines job 2's size and cost.

**The gate gets a second pass, the other tasks get one too — but the gate's matters more.** There are no
human labels for the 1287, so a paper's fate rests on the model's own exclusion/inclusion call, and a
false exclusion is unrecoverable: the paper never reaches power/data analysis and silently leaves the
study. Low-confidence gate calls go to Opus **before** gating, not after.

**30% of the labeled papers are held out.** Rubrics are built and iterated on the build split; the
confidence threshold is tuned on that same split. The holdout is touched **once**, at the very end, with
the final production config (Sonnet + Opus second pass). That single number is the honest accuracy
estimate — everything measured on the build split is optimistic, because the rubric was written to fix
those exact papers.

The same holdout is used for all four tasks. Splitting per-task would leak: a paper studied while
building the exclusion rubric is no longer unseen when scoring data_analysis.

**The split is assigned once, by `db.assign_split()`, and refuses to re-run.** It hashes
`seed + paper_id`, so it depends on nothing but a paper's identity — not row order, not when it was
loaded, not how many labels existed at the time. Adding the NHLBI labels later and re-running leaves
every existing assignment untouched. Re-assigning takes an explicit `force`, because reshuffling after
seeing a disappointing holdout number is the easiest way to publish an inflated one.

## Decision schema

All four tasks return the same object via forced `tool_choice`, validated by pydantic
(`src/schemas.py`):

```python
{
  "decision":        "yes" | "no" | "undecidable",
  "reasoning":       str,    # why, in the model's own words
  "rubric_evidence": str,    # which rubric rule(s) drove it, quoted or cited
  "confidence":      float,  # 0-1
}
```

| task | `yes` means | `no` means |
|---|---|---|
| exclusion | exclude this paper | keep it |
| inclusion | include this paper | do not include |
| power_analysis | power analysis is correct | incorrect |
| data_analysis | data analysis is correct | incorrect |

**A paper that reports no power analysis at all is `no` (incorrect)** — absent and wrong collapse into
one label. Say this explicitly in `rubrics/power_analysis.md`; it is the most likely place for the model
to hedge.

**`undecidable` is an abstention, not a third category.** It means the evidence in the paper is
genuinely insufficient to call either way — not that the call is hard, and never a substitute for a
judgment the rubric already covers. "No power analysis reported" is `no`, not `undecidable`. The rubric
must say this outright, or the model will reach for `undecidable` whenever a case is merely difficult,
and the human queue fills with work that did not need a human.

Every `undecidable` goes to the human review queue. In the worst case a researcher looks at the paper
directly, which is the point: a model that cannot decide should say so rather than guess.

**`rubric_evidence` is separate from `reasoning` on purpose.** `reasoning` is the argument;
`rubric_evidence` is which rule it rests on. Keeping them apart makes the rubric loop mechanical — when
a paper is misjudged, you can see whether the rubric was misapplied, or was silent, or was wrong, and
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
   to happen regardless; it is the ~1287 per-paper round trips that the skip avoids.

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
   a `--set validation` run doesn't dredge up the testing set's old warnings. `--list-warnings` prints
   every warning on file, across every set and past run, without fetching anything. They do not block
   the paper — identity verification (step 1) is the net that catches a wrong pick.

   **Scope: the study papers live in one Zotero collection** — group `Glykos`, collection
   `Boring Task` (both are the literal names in Zotero). The labeled validation papers are **not**
   in it and arrive by a separate route (open question 1). The `--set` flag both tags the
   rows a run writes and picks the destination directory — `data/raw_pdfs/testing/` or
   `data/raw_pdfs/validation/` — since Zotero records nothing about the split; it is a property of which
   collection you point at. Those directories exist to make the split visible at a glance; the manifest's
   `set` column stays authoritative, and every other attribute (`verdict`, `folder`, `status`) is a
   manifest filter, never a directory.

   **Cross-set duplicate check, once both sets are fetched.** Testing and validation come from different
   Zotero groups, so the same physical paper can land in both with two different `paper_id`s —
   `paper_id` can't catch it. Cross-check `set=testing` vs `set=validation` manifest rows by normalized
   DOI/PMID/PMCID (PDF md5 as a fallback for records missing all three). If a paper appears in both:
   drop it from `testing`, keep it in `validation` — it already has a human label, so classifying it
   blind in the corpus wastes a call and risks a leaked-label sanity check.
   **Claude: surface any overlap found to the user for a decision before starting the rubric loop or any
   classification run — do not resolve it silently.**

1. **Verify identity** — DONE, `scripts/01_verify_identity.py` + `src/identity.py`. Light PyMuPDF
   extraction of the **first 2 pages only**, then rapidfuzz-compare title / first author / DOI against
   the Zotero metadata:

   **Measured on the corpus (2026-08-10): 2041 VERIFIED (98.9%), 3 WEAK, 18 MISMATCH, 1 unreadable.**
   Of the VERIFIED, 1989 passed on DOI and 52 on title+author (accepted manuscripts carry no DOI).
   Full per-signal detail in `results/identity_report.csv`; verdicts also land in the manifest's
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
   calibrate them on the validation set before trusting them on the 1287.

   `author_frac` needs **every** author surname, so it reads from `data/zotero_meta.jsonl` via
   `load_meta()` — the manifest only carries `first_author`.

   **`WEAK` papers get their identity checked once, on the exclusion task only** — not four times.
   Prepend the Zotero metadata to that one prompt and add `metadata_mismatch: bool` to the schema. A
   paper flagged there gets the `METADATA_MISMATCH` sentinel and never reaches the other three tasks.
   Doing it on every task would repeat the same check four times and mix an identity question into
   rubric-driven judgments, which the "never conflate tasks" rule exists to prevent.

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
   `results/extraction_report.csv`.

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

   Label columns map one-to-one onto the four tasks: `Reason excluded` → exclusion, `Review Category` →
   inclusion, `Power` → power_analysis, `Stats` → data_analysis. The 134/96 shape confirms the gate — only
   papers the humans kept carry power/stats labels, exactly as `expected_decision()` assumes.

5. **Rubrics** — four independent markdown files in `rubrics/`, versioned by git commit. Never merged,
   never cross-referenced.

6. **Rubric loop** — `src/rubric_builder.py`, one task at a time, using **Opus** via forced tool-use:
   load rubric -> sample <100 unreviewed papers **from the build split** -> judge -> compare to the SQLite label
   -> log every result -> on a miss, hand-write or have Opus propose (for review) a generalized rule or
   worked example, append it to that task's rubric, commit with the accuracy delta in the message.
   Opus is worth the cost here: one-time, low-volume, high-stakes, and it shapes the rubric Sonnet
   relies on for the cheap full run.

   **Option: run the rubric loop through the Claude Code CLI instead of the API, to spend subscription
   quota rather than API credits.** `claude -p "<prompt>" --output-format json` runs headless and
   authenticates off the subscription login. A small script walks `data/extracted_text/*.json`, pipes
   each paper's text in with the current rubric, and writes one response JSON per paper to a new
   directory for hand-inspection. Only for rubric refinement — the full run stays on the Batches API
   (see the standing rule). Two trade-offs to accept if we go this way: no forced `tool_choice`, so the
   prompt has to ask for JSON and the wrapper validates with pydantic and re-prompts on a parse failure;
   and one process per paper, so no prompt caching and it runs slower. Fine at <100 papers a round.

7. **Regression** — `src/evaluate.py` re-runs the current rubric against the whole build split, computes
   accuracy/precision/recall, appends to `results/rubric_accuracy_history.csv` with the commit hash.

   **Plateau = two consecutive rounds each improving accuracy by less than 1 percentage point.** Then
   stop and move to step 7. Track the `undecidable` rate alongside accuracy: a rate that climbs while
   accuracy holds means the rubric is teaching the model to abstain rather than to judge.

8. **Sonnet check** — once a rubric plateaus on Opus, re-run the build split with **Sonnet** and record that
   accuracy alongside. The rubric was shaped by Opus's reasoning; if Sonnet is materially worse, tighten
   the rubric for Sonnet before spending on the full run. Skipping this means discovering the gap after
   thousands of calls.

9. **Two-pass tuning** — `src/two_pass.py`: Sonnet everywhere, anything under the confidence threshold
   routes to Opus. Tune the threshold **on the build split**, once all four rubrics have plateaued and passed
   step 7.

10. **Gate run** — batch job 1: exclusion + inclusion across all 1287 (2574 calls), Opus second pass on
   low-confidence calls, then apply the gate (`keep AND include`). Record the survivor count and the
   drop reason per paper — this is a study result in its own right, not just plumbing.

11. **Analysis run** — batch job 2: power_analysis + data_analysis across the survivors only, same
    two-pass. Merge in SQLite/pandas and export.

12. **Holdout** — run the holdout once, end to end, with the exact production config. Report that number.

## Phase order

**Do not parallelize across tasks.** Take `exclusion` to a plateau before touching `inclusion`,
then `power_analysis`, then `data_analysis`.

- [x] Repo, `requirements.txt`, `.env`, git init
- [x] `src/pdf_extract.py` — two-stage: `extract_head_text()` for identity, `extract_pdf_text()` for the full pass
- [x] `src/zotero_fetch.py`, `scripts/00_fetch_zotero.py` — fetch + md5 check + manifest + metadata
- [x] Dry-run the fetch, confirm the collection tree resolves, then pull the study papers
- [x] Settle where the validation PDFs come from and fetch them with `--set validation` — 569 fetched
      (232 NCI + 337 NHLBI)
- [x] Cross-check testing vs validation for duplicate papers (DOI/PMID/PMCID); flag any overlap to the
      user before proceeding
- [x] Identity verification (`01_verify_identity.py`) — thresholds calibrated, verdicts in the manifest
- [x] Cross-set duplicate check — 207 testing papers also in validation; removed from testing
      (1494 → 1287), logged in `results/review/02_removed_testing_duplicates.csv`
- [x] **Decide the 15 NCI↔NHLBI duplicate pairs inside validation.** Resolved by
      `scripts/04_load_ground_truth.py`, not by a manual decision: 9 pairs agree on every label and are
      collapsed to one `validation_labels` row automatically; 6 disagree — sometimes completely (one
      pair has NCI calling both analyses correct and NHLBI calling both incorrect, for the same
      paper) — and both sides are held out, listed in `results/review/05_label_match_review.csv` for a
      human to adjudicate by reading the paper. Neither side is silently preferred.
- [x] Triage the 24 flagged papers with `scripts/03_review_mismatches.py` — 20 PDFs replaced, 4 marked
      fine, none dropped. Audit trail in `results/review/04_papers_reviewed_results.csv`
- [x] Rewrite `scripts/02_extract_pdfs.py` for two-stage extraction; extract `VERIFIED` (1856 papers,
      all by PyMuPDF, no OCR)
- [x] `src/db.py` — labels + append-only judgments schema, with the split guard
- [x] Load the ground truth into SQLite (`scripts/04_load_ground_truth.py`, rewritten to read
      `data/ground_truth.csv` rather than parse a spreadsheet itself) — 523 papers in
      `validation_labels`; `--assign-split` now hard-refuses while any active validation paper still
      lacks a label (`--allow-incomplete` overrides deliberately)
- [ ] **Resolve `(Patterson et al., 2022a)` / `(2022b)`** — only **one** real corpus paper is actually
      affected, not two: the two citations resolve to `IT2B87LL` (the article) and `JBUFJCLU`
      (`Correction to:` the same article, already `DROPPED` from the manifest). The join still can't
      choose between them because it reads `zotero_meta.jsonl`, which was never pruned when `JBUFJCLU`
      was dropped — not because there is a genuine second paper waiting on a label. Still blocked on
      the same policy question below: whether `Correction to:` notices belong in the corpus at all.
- [x] Merge every label file into `data/ground_truth.csv` (`scripts/07_build_ground_truth.py`) —
      569 rows, 567 joined to paper_ids; NCI 2×2 reproduces the published 20/11/5/60. Also fixed here:
      15 NHLBI citations were resolving to a paper_id `06_merge_validation_duplicates.py` had already
      retired (the join reads `zotero_meta.jsonl`, which the merge script never prunes) — now remapped
      to the surviving paper_id, logged in the `paper_id_note` column.
- [x] **The 23 unlabeled NHLBI papers are dropped, not chased.** `scripts/09_drop_unreviewed_nhlbi.py` —
      manifest verdict `DROPPED`, files moved to `data/removed_pdfs/nhlbi_unreviewed/`, logged in
      `results/review/09_nhlbi_unreviewed_dropped.csv`. Active validation corpus: 553 → 530.
- [ ] **Fix the batching scheme before `--assign-split`** — build/holdout sizes, whether to stratify on
      gate-survivor status, and the rubric-loop round size
- [x] Exclusion ledger (`scripts/05_build_exclusions.py`) — every departed paper with its reason and
      who decided; reconciles 2063 fetched → 1814 active
- [ ] `rubrics/exclusion.md` v0 — literally just "exclude if secondary analysis"
- [ ] Rubric loop on exclusion against the build split until plateau; Sonnet check
- [ ] Same for inclusion, then power_analysis, then data_analysis
- [ ] Tune the two-pass confidence threshold on the build split
- [ ] Gate run (job 1), record survivors
- [ ] Analysis run (job 2) on survivors
- [ ] Holdout run — report this number

## Exclusion ledger

**Every paper that leaves the corpus must be recoverable with its reason.** The methods section has to
account for the path from 2115 raw placements to whatever number is finally analysed, and right now that
evidence is scattered across five files that share no schema:

| Stage | Where it lives now | Papers |
|---|---|---|
| Collection placements → unique papers | `results/unvalidated_set_summary.tex` | 2115 → 1494 |
| Cross-set duplicates (kept in validation) | `results/review/02_removed_testing_duplicates.csv` | 207 |
| Wrong document / unreadable, dropped by hand | manifest `verdict=DROPPED` + `04_papers_reviewed_results.csv` | 2 so far |
| Correction notices | same route, `CORRECTION_NOTICE` in the review queue | 4 found |
| Validation internal duplicates | `results/review/03_validation_internal_duplicates.csv` | 15 pairs, undecided |
| Unjoinable labels | `results/review/05_label_match_review.csv` | 2 |
| Gate exclusions (model) | SQLite `judgments`, once the gate runs | unknown |

**Consolidate these into `results/exclusions.csv`**, one row per departed paper:
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
rubric_evidence, confidence, rubric_version, timestamp
```

**`judgment_index`** — how many times this paper has been judged on this task, including the row it sits
on. First ever judgment of `4XKQ7B2M` on `exclusion` is `1`; its Opus review is `2`; a re-run after the
next rubric edit is `3`, and so on. Counts across the whole project, not per run: rubric-building rounds
re-judge the same papers repeatedly, and the total is the number you want when asking how much scrutiny
a paper has already received.

`UNIQUE(paper_id, task, judgment_index)` — this is the real payoff. It makes a double-write physically
impossible, so an interrupted batch can be resumed by replaying it without risking duplicate judgments
silently inflating the accuracy math.

Useful slices:
- Passes within one rubric version: filter on `rubric_version`, then read `pass_name`.
- Papers the model keeps struggling with: `judgment_index` high while `decision` keeps flipping.
- Current answer for a paper: highest `judgment_index` for that `(paper_id, task)`.

`pass_name` is `primary` or `review`. Keeping both rows is what lets you ask why Opus overturned Sonnet,
which rubric rule each leaned on, and whether the disagreement clusters somewhere the rubric is weak.
Overwriting would destroy exactly the evidence that makes the second pass worth paying for.

`rubric_version` is the git commit hash of the rubric in force at the time, so any judgment can be
traced back to the exact rules that produced it.

## Manifest

`data/zotero_manifest.csv` — one row per Zotero record, tracked in git (PDFs are gitignored; this table
is the reproducible record of what was pulled):

```
paper_id, folder, folder_path, title, first_author, doi, pmid, pmcid, year, journal,
attachment_key, md5, status, detail, warning, verdict, verdict_reason, title_score,
set, fetched_at
```

Rows are **merged on `paper_id`**, never overwritten wholesale — the validation papers come from a
different source and share this file, so a study re-fetch must not delete them.

`verdict` / `verdict_reason` / `title_score` are filled by step 1
(`scripts/01_verify_identity.py`); the full per-signal detail behind them lives in
`results/identity_report.csv`. `set` is `testing` (the study papers to classify) or `validation` (the
human-labeled papers), set by the fetch's `--set` flag.

## Zotero metadata

`data/zotero_meta.jsonl` — one JSON object per record, written by the same fetch, merged on `paper_id`
the same way. Gitignored: derived data, re-creatable from Zotero, and large once abstracts are in it.

```json
{"paper_id": "4XKQ7B2M", "set": "testing",
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
watching, since these are what will join this corpus to the validation labels.

`zotero_item` is the escape hatch — volume, issue, pages, ISSN, URL, tags, itemType and anything else
Zotero holds stay recoverable without re-pulling the library. `zotero_version` is what would enable an
`If-Modified-Since-Version` re-sync later instead of a full re-pull.

## Open questions

**1. Where do the 500 validation papers and their PDFs come from?** They are *not* under *Boring Task*,
so the fetch script never sees them. Two things are unsettled: (a) where the PDFs live — another Zotero
collection/group, or a local folder; and (b) how `validation_labels.csv` keys them — almost certainly
DOI or PMCID, not a Zotero item key. If they come from Zotero, the same fetch code points at a different
collection and `paper_id` stays a Zotero key, joined to the labels by normalized DOI. If they come from
a folder, they need their own `paper_id` scheme and a metadata source for identity verification.
Blocks step 3.

Partially settled: the validation PDFs live in Zotero, but split across **two separate groups —
NCI and NHLBI — each with its own group ID and collection key**, not one shared collection like
*Boring Task*. `00_fetch_zotero.py` fetches one `--collection` (and its subtree) from one group per
run, so pulling the validation set needs **two runs**, one per group, both with `--set validation` so
they merge into the same manifest rows rather than overwriting each other. `.env`'s
`ZOTERO_LIBRARY_ID`/`ZOTERO_COLLECTION_KEY` will need to point at each group in turn (or the script
extended to accept a library ID override alongside `--collection`).

**Settled for the PDFs.** NCI: group `5573699`, collection `V3822KC9` ("FinalCollectionFor
Publication", flat, 232 papers, no subcollections), fetched 2026-08-10 with `--set validation`, zero
multi-attachment warnings. NHLBI: group `6363893`, fetched as `Locked_26_01_08_337`, **337 papers**.
569 validation PDFs are on disk and all 569 are VERIFIED.

**Still open: the NHLBI *labels*.** Only `GroundTruthDataNCI01.xlsx` has arrived. Until NHLBI's
equivalent lands, 337 of the 569 validation papers have PDFs but no human answer, so they can be
neither scored nor split. This is what blocks `--assign-split`.

**2. Do all validation papers carry labels for all four tasks?** **No — and by design.** Measured on
NCI01: of 232 rows, 136 carry an exclusion reason and nothing else, and 96 carry Power / Stats /
Review Category. That is the gate showing up in the ground truth exactly as intended — a paper the
humans excluded never got scored on power or stats — and `db.expected_decision()` returns `None` for
those, so they drop out of the denominator rather than counting as misses.

The consequence for the split is real though: a single 30% holdout drawn over *all* labeled papers
leaves only ~29 gate survivors to score power_analysis and data_analysis on, which is thin for a
headline accuracy number. Two options when the NHLBI labels arrive: stratify the split on
gate-survivor status so both tasks get a proportional holdout, or accept the wide interval and report
it. Decide before calling `--assign-split`, because it only runs once.

**3. Rubric updates on a miss: manual or model-assisted?** Manual = you read the miss and write the
rule. Model-assisted = feed the miss + current rubric to Opus and have it propose the edit. Faster, but
every proposed rule needs a spot-check before it is committed. Not yet decided.
