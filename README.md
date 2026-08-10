# Scripts

- **`scripts/00_fetch_zotero.py`** — pulls the corpus from Zotero into `data/raw_pdfs/<set>/`, writing `data/zotero_manifest.csv` (scannable summary, tracked in git) and `data/zotero_meta.jsonl` (full per-paper metadata — every author, abstract, raw Zotero item; gitignored). `--help` for flags; `--list-warnings` prints every multi-PDF-attachment warning on file (any set, any past run) without fetching anything — the normal end-of-run summary only covers the records that run touched. Status: `testing` set (1,494 papers) and the ignore02/NCI half of `validation` (232 papers) fetched; ignoreNHLBI still pending.
- **`scripts/01_verify_identity.py`** — checks each PDF really is the paper Zotero claims (PLAN.md step 1). Reads the first 2 pages, compares to Zotero metadata, assigns `VERIFIED`/`WEAK`/`MISMATCH`/`PDF_UNREADABLE` into the manifest plus a full per-signal `results/identity_report.csv`. `--retry-attachments` additionally re-downloads a record's other PDFs and swaps in one that verifies. Current corpus: 2040 VERIFIED, 4 WEAK, 18 MISMATCH, 1 unreadable.
- **`scripts/02_extract_pdfs.py`** — **not ready**, refuses to run without `--run-anyway`. Full-text extraction for step 2; still needs rewriting to run only on verified papers.

# Library modules

- **`src/zotero_fetch.py`** — core Zotero walking/download/manifest logic behind `00_fetch_zotero.py`.
- **`src/pdf_extract.py`** — PDF → text. `extract_head_text()` grabs the first 2 pages for identity checks; `extract_and_cache()` does the full PyMuPDF → pdfplumber → OCR pass, cached to `data/extracted_text/<paper_id>.json`.
- **`src/identity.py`** — the identity rules: text normalization, DOI/title/author signals, and the verdict ladder. Pure functions, no I/O, so classification-time re-checks reuse the same logic.

See [PLAN.md](PLAN.md) for the roadmap and `.claude/CLAUDE.md` for project rules.
