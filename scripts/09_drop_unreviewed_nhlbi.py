"""Drop NHLBI papers that are cited in the review table but will never be reviewed.

HOW TO RUN
    python scripts/09_drop_unreviewed_nhlbi.py --dry-run   # report only
    python scripts/09_drop_unreviewed_nhlbi.py             # do the drop

WHAT IT DOES
    23 papers appear in crt_review_table_112.tex as a `% Entry N` citation with
    every data field blank -- the reviewer logged that the paper exists but
    never judged it. Ground Truth Raw/NOTES.md called these "genuinely
    undecided" while more of the review might still land. That review will not
    resume, so they are decided now: dropped from the corpus, the same way a
    wrong-PDF or correction-notice paper leaves.

    The source is data/ground_truth.csv, filtered to
    source_institute == "NHLBI" and labeled == "0" -- so a newer
    crt_review_table_NNN.tex that reintroduces the same pattern (cited, never
    judged) is picked up the same way without editing this file.

    Nothing is deleted. Both the PDF and its cached extracted text are moved
    to data/removed_pdfs/nhlbi_unreviewed/, mirroring how 03_review_mismatches.py
    and 06_merge_validation_duplicates.py handle every other drop -- except
    those two delete the cached text once a paper leaves; this one does not,
    because the full text is exactly what a later review would need if the
    NHLBI team ever does reach these papers.

    The manifest verdict becomes DROPPED with verdict_reason=NHLBI_UNREVIEWED,
    a code distinct from 03's MANUAL_DROPPED so 05_build_exclusions.py can tell
    the two reasons apart in the ledger rather than describing this as "dropped
    during hand review", which it was not.

OUTPUTS
    data/zotero_manifest.csv                          23 rows marked DROPPED
    results/review/09_nhlbi_unreviewed_dropped.csv     what was dropped, and why
    data/removed_pdfs/nhlbi_unreviewed/                the moved PDFs
    data/removed_pdfs/nhlbi_unreviewed/extracted_text/ the moved cached text

AFTER RUNNING
    Re-run scripts/07_build_ground_truth.py and scripts/04_load_ground_truth.py
    so their coverage numbers reflect the smaller active corpus, then
    scripts/05_build_exclusions.py to fold this into the ledger.
"""

import argparse
import csv
import io
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from zotero_fetch import MANIFEST_COLUMNS, SET_HUMAN_LABELLED, set_dir

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
GROUND_TRUTH = ROOT / "data" / "ground_truth.csv"
LOG = ROOT / "results" / "review" / "09_nhlbi_unreviewed_dropped.csv"
MOVED_PDF_DIR = ROOT / "data" / "removed_pdfs" / "nhlbi_unreviewed"
MOVED_TEXT_DIR = MOVED_PDF_DIR / "extracted_text"
PDF_DIR = set_dir(ROOT, SET_HUMAN_LABELLED)
CACHE_DIR = ROOT / "data" / "extracted_text"

VERDICT_REASON = "NHLBI_UNREVIEWED"

LOG_COLUMNS = ["dropped_at", "paper_id", "source_row", "citation_raw", "cite_key",
               "pdf_moved_to", "extracted_text_moved_to", "reason"]

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report only, change nothing")
    args = parser.parse_args()

    if not GROUND_TRUTH.exists():
        raise SystemExit(f"{GROUND_TRUTH} not found. Run scripts/07_build_ground_truth.py first.")

    candidates = [r for r in read_csv(GROUND_TRUTH)
                  if r["source_institute"] == "NHLBI" and r["labeled"] == "0"]
    missing_id = [r for r in candidates if not r["paper_id"]]
    if missing_id:
        print(f"!! {len(missing_id)} unreviewed citation(s) have no paper_id yet -- "
              f"skipping, they cannot be dropped by paper_id:")
        for r in missing_id:
            print(f"    entry {r['source_row']}: {r['citation_raw']}")
    candidates = [r for r in candidates if r["paper_id"]]

    manifest = read_csv(MANIFEST)
    by_id = {r["paper_id"]: r for r in manifest}

    plan, already_dropped = [], []
    for row in candidates:
        manifest_row = by_id.get(row["paper_id"])
        if manifest_row is None:
            print(f"!! {row['paper_id']}: not in the manifest at all -- skipping")
            continue
        if manifest_row.get("verdict") == "DROPPED":
            already_dropped.append(row["paper_id"])
            continue
        plan.append((row, manifest_row))

    print(f"{'='*74}\nDROP PLAN ({len(plan)} paper(s), {len(already_dropped)} already dropped)\n{'='*74}")
    for row, manifest_row in plan:
        print(f"  {row['paper_id']}  entry {row['source_row']:>3}  {row['citation_raw']:30}  "
              f"{manifest_row['title'][:60]}")

    if not plan:
        print("\nNothing to do.")
        return
    if args.dry_run:
        print(f"\n--dry-run: manifest and files untouched ({len(manifest)} manifest rows).")
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    MOVED_PDF_DIR.mkdir(parents=True, exist_ok=True)
    MOVED_TEXT_DIR.mkdir(parents=True, exist_ok=True)

    log_rows = []
    for row, manifest_row in plan:
        paper_id = row["paper_id"]
        manifest_row["verdict"] = "DROPPED"
        manifest_row["verdict_reason"] = VERDICT_REASON

        pdf_dest = ""
        pdf_src = PDF_DIR / f"{paper_id}.pdf"
        if pdf_src.exists():
            dest = MOVED_PDF_DIR / pdf_src.name
            pdf_src.rename(dest)
            pdf_dest = str(dest.relative_to(ROOT))

        text_dest = ""
        text_src = CACHE_DIR / f"{paper_id}.json"
        if text_src.exists():
            dest = MOVED_TEXT_DIR / text_src.name
            text_src.rename(dest)
            text_dest = str(dest.relative_to(ROOT))

        log_rows.append({
            "dropped_at": now, "paper_id": paper_id, "source_row": row["source_row"],
            "citation_raw": row["citation_raw"], "cite_key": row.get("cite_key", ""),
            "pdf_moved_to": pdf_dest, "extracted_text_moved_to": text_dest,
            "reason": "cited in the NHLBI extraction table but never reviewed; "
                      "the institute's review will not resume for outstanding papers",
        })

    with MANIFEST.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(manifest)

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(log_rows)

    print(f"\n{'='*74}\nDONE\n{'='*74}")
    print(f"  {len(plan)} paper(s) marked verdict=DROPPED, verdict_reason={VERDICT_REASON}")
    print(f"  PDFs moved to {MOVED_PDF_DIR.relative_to(ROOT)}")
    print(f"  extracted text moved to {MOVED_TEXT_DIR.relative_to(ROOT)}")
    print(f"  log -> {LOG.relative_to(ROOT)}")
    print(f"\n  Next: re-run 07_build_ground_truth.py, 04_load_ground_truth.py, "
          f"then 05_build_exclusions.py.")


if __name__ == "__main__":
    main()
