"""Drop HLS papers whose exclusion reason the model is not allowed to reproduce.

WHY
    Two of the human exclusion reasons are cross-paper judgments, not properties
    of the paper in hand:

      protocol_paper              (9)  excluded because its outcomes paper exists
      duplicate_group_random_drop (34) excluded by a coin flip among same-group papers

    The promptbook forbids both (E12, E17): the model judges each paper on its own
    text, so it will never produce these answers. Scoring against them would count
    a correct, by-design decision as a miss. They leave the scored set instead.

    Nothing is deleted. Same mechanics as 09_drop_unreviewed_nhlbi.py.

OUTPUTS
    data/zotero_manifest.csv                             rows marked DROPPED
    results/review/10_nonjudgeable_exclusions_dropped.csv what left, and why
    data/removed_pdfs/nonjudgeable_exclusions/           the moved PDFs
    data/removed_pdfs/nonjudgeable_exclusions/extracted_text/  the moved cached text

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
GROUND_TRUTH = ROOT / "data" / "ground_truth.csv"
LOG = ROOT / "results" / "review" / "10_nonjudgeable_exclusions_dropped.csv"
MOVED_PDF_DIR = ROOT / "data" / "removed_pdfs" / "nonjudgeable_exclusions"
MOVED_TEXT_DIR = MOVED_PDF_DIR / "extracted_text"
PDF_DIR = set_dir(ROOT, SET_HUMAN_LABELLED)
CACHE_DIR = ROOT / "data" / "extracted_text"

VERDICT_REASON = "NONJUDGEABLE_EXCLUSION"

# reason -> why the model can never reproduce it, recorded per row.
TARGETS = {
    "protocol_paper":
        "excluded because the trial's outcomes paper exists elsewhere in the set -- "
        "a cross-paper judgment; promptbook E12 forbids it, the model judges the paper alone",
    "duplicate_group_random_drop":
        "excluded by a random coin flip among same-first-author papers (Ignore02 `randuni`) -- "
        "unreproducible from text; promptbook E17 forbids it",
}

LOG_COLUMNS = ["dropped_at", "paper_id", "exclusion_reason", "source_institute", "source_row",
               "citation_raw", "pdf_moved_to", "extracted_text_moved_to", "reason"]

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

    candidates = [r for r in read_csv(GROUND_TRUTH) if r["exclusion_reason"] in TARGETS]
    missing_id = [r for r in candidates if not r["paper_id"]]
    for r in missing_id:
        print(f"!! no paper_id, cannot drop: entry {r['source_row']} {r['citation_raw']}")
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
    counts = {}
    for row, m in plan:
        counts[row["exclusion_reason"]] = counts.get(row["exclusion_reason"], 0) + 1
        print(f"  {row['paper_id']}  {row['exclusion_reason']:28}  {m['title'][:52]}")
    print("\n  by reason:", counts)

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
            "exclusion_reason": row["exclusion_reason"],
            "source_institute": row.get("source_institute", ""),
            "source_row": row.get("source_row", ""),
            "citation_raw": row.get("citation_raw", ""),
            **moved,
            "reason": TARGETS[row["exclusion_reason"]],
        })

    with MANIFEST.open("w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        w.writeheader(); w.writerows(manifest)

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=LOG_COLUMNS, extrasaction="ignore")
        w.writeheader(); w.writerows(log_rows)

    print(f"\n{'='*74}\nDONE\n{'='*74}")
    print(f"  {len(plan)} paper(s) marked verdict=DROPPED, verdict_reason={VERDICT_REASON}")
    print(f"  log -> {LOG.relative_to(ROOT)}")
    print("\n  Next: re-run 07_build_ground_truth.py, 04_load_ground_truth.py, 05_build_exclusions.py.")


if __name__ == "__main__":
    main()
