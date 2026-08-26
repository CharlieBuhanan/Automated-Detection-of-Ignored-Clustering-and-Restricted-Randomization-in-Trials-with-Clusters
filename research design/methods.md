# Methods — steps taken so far

Working notes for the manuscript's methods section. Each step is kept to one or two short
bullets; the full rationale for every decision is in [PLAN.md](PLAN.md).

**1. Corpus assembly**
- Walked Zotero collection tree; downloaded 1,856 PDFs.
- Verified every download against Zotero's own md5.

**2. Deduplication**
- Removed 207 study papers already in the Human Labelled Set.
- Corpus fell from 1,494 to 1,287 papers.

**3. Identity verification**
- Compared each PDF's first two pages to Zotero metadata.
- 98.9% verified; 24 flagged, including 12 grant documents.

**4. Manual PDF triage**
- Reviewed all 24 flagged papers in a desktop GUI.
- Replaced 20 wrong PDFs; confirmed 4 correct.

**5. Full-text extraction**
- PyMuPDF extracted all 1,856 papers; no OCR needed.
- Cached as JSON, invalidated by source PDF md5.

**6. Correction-notice screening**
- Title-anchored rule flags errata, corrigenda, retractions.
- Four found; excluded before classification.

**7. Ground truth loading** *(incomplete — 23 NHLBI labels pending)*
- Merged NCI and NHLBI labels into one table.
- Joined 567 of 569 rows to papers.

**8. Human Labelled Set duplicate merge**
- Merged 15 NCI/NHLBI pairs into one row.
- Folder marked "Both Validation Institutes"; NHLBI copy removed.

**9. Exclusion ledger**
- Every removed paper logged with reason and decider.
- Reconciles 2,063 fetched to 1,854 active.

## Exclusion rules (current)

- Duplicate across sets
- Correction/erratum notice
- Wrong PDF attached
- PDF unreadable/scanned
- Manual review drop

*Title score: best of fuzzy token-set ratio and whitespace-stripped partial ratio, 0-100.*

## Triggers for human review

- Title score under 85
- High score, no author
- Zero authors matched
- Under 3,000 characters
- No text layer
- Grant document detected
- Correction notice title
- Ambiguous citation match
- No citation match
- Human Labelled Set internal duplicate

## Still to do

- Verify extracted text integrity before any classification.
- Load remaining labels, then fix build/holdout split.
- Write four promptbooks; iterate against the build split.
- Run the gate, then the analysis, then the holdout.
