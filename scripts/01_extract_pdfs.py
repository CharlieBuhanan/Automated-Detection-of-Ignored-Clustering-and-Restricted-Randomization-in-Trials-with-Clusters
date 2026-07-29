"""Extract text for every PDF in a raw_pdfs subfolder, caching results.

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
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["validation", "full_set"], required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    pdf_dir = ROOT / "data" / "raw_pdfs" / args.set
    cache_dir = ROOT / "data" / "extracted_text"

    pdf_paths = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_paths:
        print(f"No PDFs found in {pdf_dir}")
        return

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
