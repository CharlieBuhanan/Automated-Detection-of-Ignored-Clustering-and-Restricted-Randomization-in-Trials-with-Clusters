"""Consolidate every paper that left the corpus into one ledger.

HOW TO RUN
    python scripts/05_build_exclusions.py           # rebuild the ledger
    python scripts/05_build_exclusions.py --check   # report only, write nothing

WHY THIS EXISTS
    The methods section has to account for the path from 2115 raw collection
    placements down to whatever number is finally analysed. That evidence is
    currently spread across five files that share no schema, so answering
    "why is this paper not in the study?" means knowing which file to open.

    This reads all of them and writes one row per departed paper. It is
    regenerated from source every run, never hand-edited -- a ledger someone
    has to remember to update is a ledger that is wrong by the time it matters.

    `decided_by` is the column that matters most to a reader: a deterministic
    rule, a human's judgment, and a model's call carry very different weight in
    a methods section, and conflating them is a fair criticism to invite.

OUTPUTS
    results/exclusions.csv   one row per excluded paper
    Terminal                 reconciliation from fetched down to active
"""

import argparse
import csv
import io
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from identity import looks_like_correction

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
REVIEW_DIR = ROOT / "results" / "review"
LEDGER = ROOT / "results" / "exclusions.csv"

COLUMNS = [
    "paper_id", "set", "stage", "removed_from", "reason", "evidence",
    "decided_by", "decided_at", "source_record", "title",
]

# Who or what made the call. Kept to three values on purpose -- see the module
# docstring for why the distinction is load-bearing.
BY_RULE = "rule"      # deterministic code, no judgment involved
BY_HUMAN = "human"    # someone looked at the PDF and decided
BY_MODEL = "model"    # Claude's classification (once the gate has run)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def read_csv(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def cross_set_duplicates(titles: dict) -> list[dict]:
    """Testing papers removed because the same paper sits in validation."""
    rows = []
    for row in read_csv(REVIEW_DIR / "02_removed_testing_duplicates.csv"):
        paper_id = row["removed_paper_id"]
        rows.append({
            "paper_id": paper_id,
            "set": "testing",
            "stage": "cross_set_duplicate",
            "removed_from": "corpus",
            "reason": f"same paper as validation {row['matched_validation_paper_id']}, "
                      f"which already carries a human label",
            "evidence": f"matched on {row['matched_on']}"
                        + (", PDF bytes identical" if row.get("pdf_bytes_identical") == "True" else ""),
            "decided_by": BY_RULE,
            "decided_at": "",
            "source_record": "results/review/02_removed_testing_duplicates.csv",
            "title": titles.get(paper_id, row.get("title", "")),
        })
    return rows


def manual_drops(manifest: list[dict]) -> list[dict]:
    """Papers a human dropped in the review GUI.

    The manifest holds the verdict; the review log holds the reason and the
    timestamp. Joining them is what turns "DROPPED" into something quotable.
    """
    decisions = {}
    for row in read_csv(REVIEW_DIR / "04_papers_reviewed_results.csv"):
        # Append-only log: the last row for a paper is its current decision.
        decisions[row["paper_id"]] = row

    queue = {r["paper_id"]: r for r in read_csv(REVIEW_DIR / "01_papers_to_review.csv")}

    rows = []
    for row in manifest:
        if row.get("verdict") != "DROPPED":
            continue
        paper_id = row["paper_id"]
        decision = decisions.get(paper_id, {})
        flagged = queue.get(paper_id, {})
        note = (decision.get("notes") or "").strip()

        # The queue category records how a paper was *found*, which is not
        # always why it *left*. Both papers dropped so far were queued as
        # THIN_TEXT -- by character count, before title screening existed --
        # but they are a Corrigendum and an Erratum, and that is the reason a
        # methods section has to state. Re-test the title so the ledger says
        # why rather than how.
        is_correction = looks_like_correction(row["title"])
        stage = ("correction_notice" if is_correction
                 else (flagged.get("category") or "manual_drop").lower())
        default_reason = ("title announces a correction/erratum/retraction, not a study"
                          if is_correction else
                          flagged.get("finding") or "dropped during hand review")

        rows.append({
            "paper_id": paper_id,
            "set": row["set"],
            "stage": stage,
            "removed_from": "corpus",
            "reason": note or default_reason,
            "evidence": f"flagged as {flagged.get('category', 'n/a')}; "
                        f"verdict_reason={row.get('verdict_reason', '')}",
            "decided_by": BY_HUMAN,
            "decided_at": decision.get("reviewed_at", ""),
            "source_record": "results/review/04_papers_reviewed_results.csv",
            "title": row["title"],
        })
    return rows


def blocked_at_fetch(manifest: list[dict]) -> list[dict]:
    """Papers that never produced a usable PDF, so they never entered."""
    rows = []
    for row in manifest:
        if row.get("status") == "OK":
            continue
        rows.append({
            "paper_id": row["paper_id"],
            "set": row["set"],
            "stage": row["status"].lower(),
            "removed_from": "corpus",
            "reason": row.get("detail") or row["status"],
            "evidence": f"status={row['status']}",
            "decided_by": BY_RULE,
            "decided_at": "",
            "source_record": "data/zotero_manifest.csv",
            "title": row["title"],
        })
    return rows


def unjoinable_labels(titles: dict) -> list[dict]:
    """Human labels that could not be tied to a paper.

    These do not remove a paper from the corpus -- the paper is still there and
    still gets classified. What is lost is the ground truth for it, which
    shrinks the validation denominator, so it belongs in the ledger with
    `removed_from` saying exactly what was lost.
    """
    rows = []
    for row in read_csv(REVIEW_DIR / "05_label_match_review.csv"):
        rows.append({
            "paper_id": "",   # by definition unknown -- that is the problem
            "set": "validation",
            "stage": "label_unjoinable",
            "removed_from": "validation_labels",
            "reason": row["problem"],
            "evidence": f"citation {row['citation_raw']!r}; "
                        f"candidates: {row.get('candidates') or 'none'}",
            "decided_by": BY_RULE,
            "decided_at": "",
            "source_record": "results/review/05_label_match_review.csv",
            "title": row.get("candidate_titles", ""),
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Report only, write nothing")
    args = parser.parse_args()

    manifest = read_csv(MANIFEST)
    if not manifest:
        sys.exit(f"No manifest at {MANIFEST}. Run scripts/00_fetch_zotero.py first.")
    titles = {r["paper_id"]: r["title"] for r in manifest}

    ledger = (blocked_at_fetch(manifest)
              + cross_set_duplicates(titles)
              + manual_drops(manifest)
              + unjoinable_labels(titles))

    # Two different kinds of removal, and conflating them makes the arithmetic
    # wrong. Cross-set duplicates were deleted from the manifest outright, so
    # they are not among its rows and must be added back to recover the fetched
    # total. A dropped paper keeps its row and is subtracted from it.
    manifest_ids = {r["paper_id"] for r in manifest}
    from_corpus = [r for r in ledger if r["removed_from"] == "corpus"]
    delisted = [r for r in from_corpus if r["paper_id"] not in manifest_ids]
    still_listed = [r for r in from_corpus if r["paper_id"] in manifest_ids]
    active = [r for r in manifest if r.get("verdict") != "DROPPED" and r.get("status") == "OK"]

    print(f"{'='*70}\nEXCLUSIONS ({len(ledger)} records)\n{'='*70}")
    for stage, n in Counter(r["stage"] for r in ledger).most_common():
        by = ", ".join(sorted({r["decided_by"] for r in ledger if r["stage"] == stage}))
        print(f"  {stage:24} {n:5}   ({by})")

    print(f"\n{'='*70}\nRECONCILIATION\n{'='*70}")
    print(f"  fetched from Zotero              {len(manifest) + len(delisted):5}")
    for stage, n in Counter(r["stage"] for r in delisted).most_common():
        print(f"    - {stage:28} {n:5}   (removed from the manifest)")
    print(f"  = rows in the manifest now       {len(manifest):5}")
    for stage, n in Counter(r["stage"] for r in still_listed).most_common():
        print(f"    - {stage:28} {n:5}   (kept as a row, verdict=DROPPED)")
    print(f"  = active corpus                  {len(active):5}")
    for set_name, n in sorted(Counter(r["set"] for r in active).items()):
        print(f"        {set_name:26} {n:5}")

    if len(manifest) - len(still_listed) != len(active):
        print("\n  !! These do not reconcile. A paper is DROPPED or non-OK without a ledger row,")
        print("     or a ledger row names a paper that is still active.")

    # Papers that left before the manifest existed cannot be enumerated here:
    # the 2115 -> 1494 reduction happened over Zotero collection placements,
    # not over rows this pipeline ever wrote. Say so rather than let a reader
    # assume the ledger is the whole story.
    print("\n  NOTE: the 2115 collection placements -> 1494 unique papers reduction predates")
    print("        the manifest and is not enumerable per-paper here. It is documented in")
    print("        results/unvalidated_set_summary.tex and must be cited separately.")

    pending = read_csv(REVIEW_DIR / "03_validation_internal_duplicates.csv")
    if pending:
        print(f"\n  PENDING: {len(pending)} validation rows ({len(pending)//2} pairs) are flagged as")
        print("           internal duplicates and not yet decided; none are excluded yet.")

    if args.check:
        print("\n--check: nothing written.")
        return

    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ledger)
    print(f"\nledger -> {LEDGER}")


if __name__ == "__main__":
    main()
