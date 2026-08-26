"""Re-apply every recorded human decision to the manifest's verdict column.

WHY
    `01_verify_identity.py` rewrites `verdict` for every row it scores, and it
    scores every row in the manifest. It only knows what the identity ladder can
    see in a PDF, so a re-run silently undoes two kinds of decision a human
    already made:

      a drop (scripts 09/10/12, or by hand in script 03) keeps its manifest row
      (DC20: DROPPED is a verdict, not a deletion) but its PDF has been moved
      aside -- so the re-run finds no file, writes PDF_UNREADABLE, and the drop
      disappears. A dropped paper whose PDF was never moved comes back VERIFIED,
      which is worse: it silently re-enters the active corpus.

      a WEAK paper cleared by hand in script 03 scores WEAK again on the same
      evidence, because the thing that resolved it was a human looking at the
      PDF, and that is not written in the file.

    This restores both from the logs, which are the authoritative record
    precisely so a rebuild like this is always possible. It is the practical
    proof of DC20 -- nothing is unrecoverable when a downstream script
    overwrites the manifest.

    **Script 01 no longer causes this.** It now skips papers with a recorded
    decision (`src/review_log.py`), so the damage above cannot recur through the
    normal path. This script stays for the two cases that remain: repairing a
    manifest damaged before that guard existed, and undoing a deliberate
    `--rescore-decided` run. Run it after `01_verify_identity.py --rescore-decided`,
    and any time `14_check_us_clean.py` reports a verdict that should be DROPPED.

    Idempotent, and safe to run at any time -- on a healthy manifest it reports
    "already applied" and writes nothing.

OUTPUTS
    data/zotero_manifest.csv    verdict/verdict_reason restored
"""

import argparse
import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from review_log import collect_decisions  # noqa: E402
from zotero_fetch import MANIFEST_COLUMNS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
REVIEW = ROOT / "results" / "review"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report only, change nothing")
    args = parser.parse_args()

    decisions = collect_decisions(REVIEW)
    rows = read_csv(MANIFEST)
    by_id = {r["paper_id"]: r for r in rows}

    restored, already, absent = [], [], []
    for paper_id, (verdict, reason) in decisions.items():
        row = by_id.get(paper_id)
        if row is None:
            absent.append(paper_id)
        elif row.get("verdict") == verdict:
            already.append(paper_id)
        else:
            restored.append((paper_id, row.get("verdict", ""), verdict, reason))
            if not args.dry_run:
                row["verdict"] = verdict
                row["verdict_reason"] = reason

    print(f"{len(decisions)} decision(s) on record: {len(already)} already applied, "
          f"{len(restored)} to restore, {len(absent)} not in the manifest.")
    for paper_id, was, verdict, reason in restored:
        print(f"  {paper_id}  {was or '(blank)'} -> {verdict}  ({reason})")
    if absent:
        # Cross-set and internal duplicates were removed from the manifest
        # entirely rather than marked, so their absence here is correct.
        print(f"  not in the manifest (removed, not marked): {', '.join(sorted(absent))}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return
    if not restored:
        print("\nManifest already consistent; nothing written.")
        return

    with MANIFEST.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nmanifest -> {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
