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

    Idempotent. **Run it after every `01_verify_identity.py` run**, always.

OUTPUTS
    data/zotero_manifest.csv    verdict/verdict_reason restored
"""

import argparse
import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from zotero_fetch import MANIFEST_COLUMNS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
REVIEW = ROOT / "results" / "review"

# Each drop log, and the verdict_reason its script writes. Kept in sync by hand
# with the VERDICT_REASON constant in each script -- if a new drop script is
# added and not listed here, its papers come back on the next identity re-run.
DROP_LOGS = [
    ("09_nhlbi_unreviewed_dropped.csv", "NHLBI_UNREVIEWED"),
    ("10_nonjudgeable_exclusions_dropped.csv", "NONJUDGEABLE_EXCLUSION"),
    ("12_institutional_disagreements_dropped.csv", "INSTITUTIONAL_DISAGREEMENT_UNRESOLVED"),
]

# The by-hand route (script 03) records its decisions in one shared log, with
# the verdict already in a column rather than implied by which file it is in.
MANUAL_LOG = "04_papers_reviewed_results.csv"

# What script 03 wrote for each decision, so the reason survives a rebuild.
MANUAL_REASONS = {"no_issue": "MANUAL_OK", "replaced": "MANUAL_REPLACED",
                  "dropped": "MANUAL_DROPPED"}

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def collect_decisions() -> dict[str, tuple[str, str]]:
    """{paper_id: (verdict, verdict_reason)} for every human decision on record.

    **Ordered by when the decision was made, not by which log it came from.**
    A paper can appear in both: `J2XGTHGE` was cleared by hand in script 03 as
    a legible PDF, then dropped weeks later by script 09 because NHLBI never
    reviewed it. Those answer different questions, and the later one is the
    live decision -- applying the manual log last would resurrect it.

    A `skipped` row carries no verdict and is ignored: it records that the
    reviewer moved on, not what they concluded.
    """
    dated: list[tuple[str, str, str, str]] = []
    for filename, reason in DROP_LOGS:
        for row in read_csv(REVIEW / filename):
            if row.get("paper_id"):
                dated.append((row.get("dropped_at", ""), row["paper_id"], "DROPPED", reason))
    for row in read_csv(REVIEW / MANUAL_LOG):
        verdict = row.get("new_verdict")
        if verdict and row.get("paper_id"):
            dated.append((row.get("reviewed_at", ""), row["paper_id"], verdict,
                          MANUAL_REASONS.get(row.get("decision", ""), "MANUAL_REVIEWED")))

    decisions = {}
    for _, paper_id, verdict, reason in sorted(dated, key=lambda d: d[0]):
        decisions[paper_id] = (verdict, reason)
    return decisions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report only, change nothing")
    args = parser.parse_args()

    decisions = collect_decisions()
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
