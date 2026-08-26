"""Drop HLS papers where NCI and NHLBI reached different answers, assumed unresolved.

WHY
    results/review/05_label_match_review.csv holds papers NCI and NHLBI both reviewed
    and disagreed on -- one pair is a complete flip (NCI: kept, both analyses correct;
    NHLBI: excluded). Neither side is preferred and the two are never averaged, so
    04_load_ground_truth.py already never loads a label for them.

    That left the papers themselves still active and unscored, silently shrinking the
    labelled denominator without saying so in the manifest. This script makes it
    explicit: assumed unresolved for now (per project decision, 2026-08-26), so the
    papers are fully DROPPED from the corpus like any other unrecoverable-label
    category -- not deleted, and easily reversible if Deb adjudicates them later.

    Nothing is deleted. Same mechanics as 09_drop_unreviewed_nhlbi.py / 10.

OUTPUTS
    data/zotero_manifest.csv                                    rows marked DROPPED
    results/review/12_institutional_disagreements_dropped.csv   what left, and why
    data/removed_pdfs/institutional_disagreements/              the moved PDFs
    data/removed_pdfs/institutional_disagreements/extracted_text/  the moved cached text

AFTER RUNNING
    Re-run 07_build_ground_truth.py, 04_load_ground_truth.py, 05_build_exclusions.py.
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
REVIEW = ROOT / "results" / "review" / "05_label_match_review.csv"
LOG = ROOT / "results" / "review" / "12_institutional_disagreements_dropped.csv"
MOVED_PDF_DIR = ROOT / "data" / "removed_pdfs" / "institutional_disagreements"
MOVED_TEXT_DIR = MOVED_PDF_DIR / "extracted_text"
PDF_DIR = set_dir(ROOT, SET_HUMAN_LABELLED)
CACHE_DIR = ROOT / "data" / "extracted_text"

VERDICT_REASON = "INSTITUTIONAL_DISAGREEMENT_UNRESOLVED"

LOG_COLUMNS = ["dropped_at", "paper_id", "nci_answer", "nhlbi_answer", "citation_raw",
               "pdf_moved_to", "extracted_text_moved_to", "reason"]

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report only, change nothing")
    args = parser.parse_args()

    if not REVIEW.exists():
        raise SystemExit(f"{REVIEW} not found. Run scripts/04_load_ground_truth.py first.")

    candidates = [r for r in read_csv(REVIEW) if r["problem"].startswith("institutional")]
    candidates = [r for r in candidates if r["paper_id"]]

    manifest = read_csv(MANIFEST)
    by_id = {r["paper_id"]: r for r in manifest}

    plan, already = [], []
    for row in candidates:
        m = by_id.get(row["paper_id"])
        if m is None:
            print(f"!! {row['paper_id']}: not in the manifest -- skipping")
            continue
        (already if m.get("verdict") == "DROPPED" else plan).append((row, m))

    print(f"{'='*74}\nDROP PLAN ({len(plan)} paper(s), {len(already)} already dropped)\n{'='*74}")
    for row, m in plan:
        print(f"  {row['paper_id']}  NCI: {row['nci_answer']:32}  NHLBI: {row['nhlbi_answer']:24}  {m['title'][:40]}")

    if not plan:
        print("\nNothing to do.")
        return
    if args.dry_run:
        print("\n--dry-run: manifest and files untouched.")
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    MOVED_PDF_DIR.mkdir(parents=True, exist_ok=True)
    MOVED_TEXT_DIR.mkdir(parents=True, exist_ok=True)

    log_rows = []
    for row, m in plan:
        paper_id = row["paper_id"]
        m["verdict"] = "DROPPED"
        m["verdict_reason"] = VERDICT_REASON

        moved = {}
        for key, src, dest_dir in [("pdf_moved_to", PDF_DIR / f"{paper_id}.pdf", MOVED_PDF_DIR),
                                   ("extracted_text_moved_to", CACHE_DIR / f"{paper_id}.json", MOVED_TEXT_DIR)]:
            if src.exists():
                dest = dest_dir / src.name
                src.rename(dest)
                moved[key] = str(dest.relative_to(ROOT))
            else:
                moved[key] = ""

        log_rows.append({
            "dropped_at": now, "paper_id": paper_id,
            "nci_answer": row["nci_answer"], "nhlbi_answer": row["nhlbi_answer"],
            "citation_raw": row.get("citation_raw", ""),
            **moved,
            "reason": "NCI and NHLBI reviewed this paper independently and reached different "
                      "answers; assumed unresolved (2026-08-26) rather than picking a side. "
                      "May be restored if adjudicated later.",
        })

    with MANIFEST.open("w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        w.writeheader(); w.writerows(manifest)

    # Complete-record log, same reasoning as script 10: a re-run must not erase
    # earlier drops just because it skips papers already DROPPED.
    LOG.parent.mkdir(parents=True, exist_ok=True)
    merged = {r["paper_id"]: r for r in (read_csv(LOG) if LOG.exists() else [])}
    merged.update({r["paper_id"]: r for r in log_rows})
    dropped_now = {r["paper_id"] for r in manifest if r.get("verdict_reason") == VERDICT_REASON}
    merged = {k: v for k, v in merged.items() if k in dropped_now}
    with LOG.open("w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=LOG_COLUMNS, extrasaction="ignore")
        w.writeheader(); w.writerows(merged.values())

    print(f"\n{'='*74}\nDONE\n{'='*74}")
    print(f"  {len(plan)} paper(s) marked verdict=DROPPED, verdict_reason={VERDICT_REASON}")
    print(f"  log -> {LOG.relative_to(ROOT)}")
    print("\n  Next: re-run 07_build_ground_truth.py, 04_load_ground_truth.py, 05_build_exclusions.py.")


if __name__ == "__main__":
    main()
