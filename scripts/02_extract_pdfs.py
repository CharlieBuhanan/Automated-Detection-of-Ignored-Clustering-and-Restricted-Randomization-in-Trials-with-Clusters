"""NOT READY -- DO NOT RUN. This is not yet the next step after 00_fetch_zotero.py.

Two things are stale:
  1. --set still offers "full_set"; the fetch now writes "testing".
  2. It does a single full extraction of every PDF. The plan (PLAN.md steps 1-2)
     calls for two stages: a light 2-page pass for identity verification, then
     full extraction only for papers that come back VERIFIED or resolved WEAK.

Running it as-is would extract unverified PDFs, which is exactly what step 1
exists to prevent. Rewrite it before use.

---

Extract text for every PDF in a raw_pdfs subfolder, caching results.

Usage:
    python scripts/01_extract_pdfs.py --set validation
    python scripts/01_extract_pdfs.py --set full_set
"""

import argparse
import sys
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from pdf_extract import extract_and_cache

ROOT = Path(__file__).resolve().parent.parent


def main():
    """Extract every PDF under data/raw_pdfs/<set>/, caching each result to
    data/extracted_text/<paper_id>.json (skipping ones already cached unless
    --overwrite is passed), then print any papers whose extraction looks
    weak enough to warrant a manual check."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["validation", "full_set"], required=True)
    parser.add_argument("--overwrite", action="store_true", help="Re-extract even if a cached JSON already exists")
    parser.add_argument("--run-anyway", action="store_true", help="Bypass the not-ready guard (see the module docstring)")
    args = parser.parse_args()

    # A comment alone would not stop an accidental run; this does.
    if not args.run_anyway:
        sys.exit(
            "01_extract_pdfs.py is NOT READY -- see the notes at the top of this file.\n"
            "It predates two-stage extraction and would extract unverified PDFs.\n"
            "Pass --run-anyway if you really mean to."
        )

    pdf_dir = ROOT / "data" / "raw_pdfs" / args.set
    cache_dir = ROOT / "data" / "extracted_text"

    pdf_paths = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_paths:
        print(f"No PDFs found in {pdf_dir}")
        return

    # Papers that needed OCR (i.e. no text layer) or still came back thin
    # after all fallbacks -- worth a human glance before trusting the text.
    flagged = []
    for pdf_path in tqdm(pdf_paths, desc=f"Extracting ({args.set})"):
        record = extract_and_cache(pdf_path, cache_dir, overwrite=args.overwrite)
        if record["method"] == "ocr" or record["char_count"] < 500:
            flagged.append((record["paper_id"], record["method"], record["char_count"]))

    print(f"\nDone: {len(pdf_paths)} PDFs processed, cached to {cache_dir}")
    if flagged:
        print(f"\n{len(flagged)} paper(s) worth a manual look (OCR used or very little text extracted):")
        for paper_id, method, char_count in flagged:
            print(f"  {paper_id}: method={method}, chars={char_count}")


if __name__ == "__main__":
    main()
