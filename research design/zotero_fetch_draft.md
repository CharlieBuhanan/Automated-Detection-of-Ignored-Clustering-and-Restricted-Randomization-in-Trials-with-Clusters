# Zotero fetch + metadata verification — design draft

Pseudocode only. Nothing here is implemented yet.

Goal: pull every record under Glykos ▸ *Boring Task* ▸ `<NIH institute>`, download its
attached full-text PDF, land it where extraction expects it, and **prove the PDF is
actually the paper Zotero claims it is** before it enters the corpus.

---

## 0. Key decisions

**`paper_id` = the Zotero item key** (8-char, e.g. `4XKQ7B2M`). Always present, always
unique, stable across edits. DOI/PMCID are *not* reliable as primary IDs (missing on
some records, formatting varies) — they get stored as metadata instead. This supersedes
the earlier "name files by PMCID" idea.

**Verification is deterministic Python, not a model call.** Comparing title/authors/DOI
is exact-ish string work — doing it in code is free, reproducible, and auditable,
whereas 2,615 verification LLM calls cost money and can hallucinate agreement. The
model gets a *second* net (§5) for cases code marks ambiguous.

**One PDF pool, not two folders.** `validation` vs `full_set` is recorded as a column in
the manifest rather than by duplicating files into separate directories — the Zotero
tree is organized by institute, which is orthogonal to the validation split.

---

## 1. Connect, resolve the collection tree

```
load .env -> api_key, library_id, library_type, root_collection_name

zot = Zotero(library_id, "group", api_key)        # pyzotero wraps API v3 paging/backoff

all_collections = zot.all_collections()            # flat list w/ key, name, parentCollection
root = find(all_collections, name == "Boring Task")
    if not found -> ABORT, print available collection names   # fail loud, don't guess
institutes = [c for c in all_collections if c.parentCollection == root.key]

log "found {len(institutes)} institute subcollections: {names}"
```

Notes:
- `zot.everything(...)` / pyzotero's iterators handle the 100-item page cap and the
  `Backoff` / `Retry-After` headers. Hand-rolled `requests` loops usually forget these.
- Record `Last-Modified-Version` from the response headers -> `manifest_meta.json`.
  Enables `If-Modified-Since-Version` re-syncs later instead of a full re-pull.

## 2. Walk items, pick the PDF attachment

```
for institute in institutes:
    items = zot.everything(zot.collection_items_top(institute.key))

    for item in items:
        if item.itemType in {"note", "attachment"}: continue      # top/ should exclude,
                                                                  # belt and braces

        meta = {
            paper_id:        item.key,
            zotero_version:  item.version,
            institute:       institute.name,
            title:           item.title,
            authors:         [c for c in item.creators if c.creatorType == "author"],
            doi:             normalize_doi(item.DOI or scrape_from(item.extra)),
            pmid / pmcid:    parse_from(item.extra),      # Zotero stashes these in Extra
            year:            parse_year(item.date),
            journal:         item.publicationTitle,
        }

        children = zot.children(item.key)
        pdfs = [c for c in children if c.contentType == "application/pdf"]

        if not pdfs:
            record(meta, status = PDF_MISSING, detail = "no PDF attachment on record")
            continue

        att = prefer(pdfs, linkMode order: imported_file > imported_url > linked_url)
        if att.linkMode == "linked_file":
            # linked files live only on the original machine, not Zotero storage
            record(meta, status = PDF_MISSING, detail = "linked_file not in cloud storage")
            continue
```

## 3. Download + integrity check

```
        dest = data/raw_pdfs/all/{paper_id}.pdf

        if dest exists and md5(dest) == att.md5:
            skip download            # resumable; safe to re-run the whole script
        else:
            bytes = zot.file(att.key)              # GET /groups/{gid}/items/{key}/file
            if md5(bytes) != att.md5:
                record(meta, status = DOWNLOAD_CORRUPT); continue
            if not bytes.startswith(b"%PDF"):
                record(meta, status = PDF_UNREADABLE, detail="not a PDF"); continue
            write dest
```

Integrity (md5) and identity (§4) are separate failures: md5 catches a truncated
transfer, §4 catches *the wrong paper filed under the right record* — the one that
would silently corrupt labels.

## 4. Identity verification (runs at extraction time)

Reuses the cached text from `pdf_extract.py`, checking only the **first ~2 pages**
(front matter) plus the last page (DOIs sometimes only appear in the footer).

```
norm(s) = lowercase, strip accents, collapse whitespace, drop punctuation,
          fix ligatures (fi/fl), de-hyphenate line breaks

signals:
  doi_hit     = normalized DOI appears as substring in norm(text)
                  (also regex-scan text for 10.\d{4,9}/\S+ to catch a *different* DOI)
  title_score = rapidfuzz.token_set_ratio(norm(title), norm(first_page))
                  + retry with all whitespace removed (titles wrap across lines)
  author_frac = fraction of author surnames found in norm(first_page)
  year_hit, journal_hit = weak corroborating signals
```

Verdict:

| verdict | rule | action |
|---|---|---|
| `VERIFIED` | `doi_hit` **or** (`title_score >= 90` and first-author surname present) | enters corpus |
| `WEAK` | `title_score` 75–89, or authors match but title doesn't | enters corpus, flagged; model double-checks (§5) |
| `MISMATCH` | no `doi_hit`, `title_score < 75`, `author_frac < 0.5` | **blocked**, needs a human |
| `PDF_UNREADABLE` | extracted text < ~500 chars after all fallbacks | blocked (likely scan; try OCR) |

A *conflicting* DOI found in the text (valid DOI pattern, ≠ the Zotero DOI) is a hard
`MISMATCH` regardless of title score — that's the signature of the wrong PDF attached.

Thresholds are guesses. Calibrate them on the 500 validation papers, where a
mismatch is cheap to eyeball, before trusting them on the 2,115.

## 5. How failures reach you

Verification result is written into the cached JSON per paper:

```
{ paper_id, text, ...,
  "zotero_meta":  {title, authors, doi, institute, ...},
  "verification": {verdict, title_score, doi_hit, author_frac, checked_at} }
```

Then, in the classification pipeline:

- **`VERIFIED`** -> classify normally.
- **`MISMATCH` / `PDF_MISSING` / `PDF_UNREADABLE`** -> **short-circuit, no API call.**
  Write a row with the sentinel as its decision so it surfaces in results instead of
  vanishing:
  ```
  [[CORPUS_ERROR: PDF_MISSING | paper_id=4XKQ7B2M | institute=NCI | doi=10.1001/... ]]
  [[CORPUS_ERROR: METADATA_MISMATCH | paper_id=7QP2LM4X | title_score=41 | doi_hit=false ]]
  ```
  One line, machine-parseable, greppable out of `results/` — and the paper is excluded
  from accuracy math rather than scored as a miss.
- **`WEAK`** -> this is where the model checks. Prepend the Zotero metadata to the
  prompt and add `metadata_mismatch: bool` to the existing tool schema alongside
  `{decision, reasoning, confidence}`. Instruct it to confirm the text is that paper
  *first*, and set the flag instead of deciding if it isn't. Any paper the model flags
  gets the same `METADATA_MISMATCH` sentinel.

## 6. Manifest

`data/zotero_manifest.csv` — one row per Zotero record, tracked in git (PDFs are
gitignored; this table is the reproducible record of what was pulled):

```
paper_id, institute, title, first_author, doi, pmid, pmcid, year, journal,
attachment_key, md5, status, verdict, title_score, set, fetched_at
```

`set` (`validation` | `full_set`) is filled by joining `validation_labels.csv` on
`paper_id` — see the open question below.

## 7. Run order

```
python scripts/00_fetch_zotero.py                  # §1-3, writes manifest + PDFs
python scripts/00_fetch_zotero.py --verify-only     # re-run §4 after threshold tuning
python scripts/01_extract_pdfs.py                   # existing; now also runs §4
```

`00_fetch_zotero.py` must be idempotent — md5 skip in §3 means a re-run costs almost
nothing and repairs a partial pull.

---

## Open question

**How do the 500 validation papers get identified?** The Zotero tree is split by NIH
institute, which says nothing about the validation split. Options: a Zotero tag, a
separate collection, or `validation_labels.csv` already keys the 500 by DOI/PMCID
(in which case the manifest join needs a DOI-based fallback, since `paper_id` is a
Zotero key the labels file won't contain). This determines how `set` gets populated
and is worth settling before the fetch script is written.
