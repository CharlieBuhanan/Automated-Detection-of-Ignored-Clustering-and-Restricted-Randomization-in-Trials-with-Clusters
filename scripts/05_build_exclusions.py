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
    results/01_corpus_build/exclusions.csv   one row per excluded paper
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
from zotero_fetch import SET_HUMAN_LABELLED, SET_UNLABELLED

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
REVIEW_DIR = ROOT / "results" / "review"
LEDGER = ROOT / "results" / "01_corpus_build" / "exclusions.csv"

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
    """Unlabelled Set papers removed because the same paper sits in the Human Labelled Set."""
    rows = []
    for row in read_csv(REVIEW_DIR / "02_removed_us_duplicates.csv"):
        paper_id = row["removed_paper_id"]
        rows.append({
            "paper_id": paper_id,
            "set": SET_UNLABELLED,
            "stage": "cross_set_duplicate",
            "removed_from": "corpus",
            "reason": f"same paper as Human Labelled Set {row['matched_validation_paper_id']}, "
                      f"which already carries a human label",
            "evidence": f"matched on {row['matched_on']}"
                        + (", PDF bytes identical" if row.get("pdf_bytes_identical") == "True" else ""),
            "decided_by": BY_RULE,
            "decided_at": "",
            "source_record": "results/review/02_removed_us_duplicates.csv",
            "title": titles.get(paper_id, row.get("title", "")),
        })
    return rows


def merged_validation_duplicates() -> list[dict]:
    """Human Labelled Set rows folded into their NCI twin.

    Not an exclusion in the usual sense -- the paper is still in the study, it
    just has one row instead of two. It belongs here anyway: without it the
    reconciliation loses 15 papers between "fetched" and "in the manifest" with
    nothing to explain where they went.
    """
    rows = []
    for row in read_csv(REVIEW_DIR / "06_merged_hls_duplicates.csv"):
        rows.append({
            "paper_id": row["removed_paper_id"],
            "set": SET_HUMAN_LABELLED,
            "stage": "validation_internal_duplicate",
            "removed_from": "corpus",
            "reason": f"same paper as {row['kept_paper_id']}, fetched from both the "
                      f"{row['kept_group']} and {row['removed_group']} Zotero groups; "
                      f"merged into one row",
            "evidence": f"matched on {row['matched_on']}"
                        + (", PDF bytes identical" if row.get("pdf_bytes_identical") == "True"
                           else ", different PDF bytes"),
            "decided_by": BY_RULE,
            "decided_at": row.get("merged_at", ""),
            "source_record": "results/review/06_merged_hls_duplicates.csv",
            "title": row["title"],
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
        # NHLBI_UNREVIEWED papers are DROPPED too, but nhlbi_unreviewed_drops()
        # below reads their own dedicated log and writes a specific reason --
        # counting them here as well would double them in the ledger, and the
        # generic "dropped during hand review" fallback would misdescribe them
        # (nobody reviewed a mismatched PDF; the paper was simply never judged).
        if row.get("verdict") != "DROPPED" or row.get("verdict_reason") not in ("", "MANUAL_DROPPED"):
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


def nhlbi_unreviewed_drops(titles: dict) -> list[dict]:
    """Papers cited in the NHLBI extraction table but dropped before review.

    scripts/09_drop_unreviewed_nhlbi.py's own log, not the generic
    04_papers_reviewed_results.csv trail manual_drops() reads -- these papers
    never went through the mismatch-review GUI, so joining against that log
    would find nothing and fall back to a description that does not apply.
    """
    rows = []
    for row in read_csv(REVIEW_DIR / "09_nhlbi_unreviewed_dropped.csv"):
        paper_id = row["paper_id"]
        rows.append({
            "paper_id": paper_id,
            "set": SET_HUMAN_LABELLED,
            "stage": "nhlbi_unreviewed",
            "removed_from": "corpus",
            "reason": row["reason"],
            "evidence": f"cited as entry {row['source_row']} ({row['citation_raw']!r}) "
                        f"in crt_review_table_112.tex with every field blank",
            "decided_by": BY_HUMAN,
            "decided_at": row.get("dropped_at", ""),
            "source_record": "results/review/09_nhlbi_unreviewed_dropped.csv",
            "title": titles.get(paper_id, ""),
        })
    return rows


def nonjudgeable_exclusion_drops(titles: dict) -> list[dict]:
    """HLS papers whose exclusion reason the promptbook forbids the model to use.

    protocol_paper and duplicate_group_random_drop are cross-paper judgments, so
    a model judging each paper alone can never reproduce them. Scoring against
    them would charge the model for obeying its own rules; they leave the scored
    set instead. See scripts/10_drop_nonjudgeable_exclusions.py.
    """
    log = REVIEW_DIR / "10_nonjudgeable_exclusions_dropped.csv"
    if not log.exists():
        return []
    rows = []
    for row in read_csv(log):
        paper_id = row["paper_id"]
        rows.append({
            "paper_id": paper_id,
            "set": SET_HUMAN_LABELLED,
            "stage": "nonjudgeable_exclusion",
            "removed_from": "corpus",
            "reason": row["reason"],
            "evidence": f"human exclusion_reason={row['exclusion_reason']!r} "
                        f"({row.get('source_institute', '')})",
            "decided_by": BY_HUMAN,
            "decided_at": row.get("dropped_at", ""),
            "source_record": "results/review/10_nonjudgeable_exclusions_dropped.csv",
            "title": titles.get(paper_id, ""),
        })
    return rows


def unjoinable_labels(titles: dict) -> list[dict]:
    """Citations that never resolved to a paper_id at all.

    Unlike an institutional disagreement, these do not know which paper is
    meant -- the citation itself could not be matched. Institutional
    disagreements are handled separately by institutional_disagreement_drops()
    below: scripts/12_drop_institutional_disagreements.py fully drops those
    papers from the corpus now (DC37), so listing them here too would double
    them in the ledger under two different `removed_from` values for the same
    underlying fact.
    """
    rows = []
    for row in read_csv(REVIEW_DIR / "05_label_match_review.csv"):
        if row["problem"].startswith("institutional"):
            continue
        rows.append({
            "paper_id": row.get("paper_id", ""),
            "set": SET_HUMAN_LABELLED,
            "stage": "label_unjoinable",
            "removed_from": "validation_labels",
            "reason": row["problem"],
            "evidence": (f"citation {row['citation_raw']!r}"
                        + (f"; cite_key {row['cite_key']!r}" if row.get("cite_key") else "")
                        + (f"; best match score {row['match_score']}" if row.get("match_score") else "")),
            "decided_by": BY_RULE,
            "decided_at": "",
            "source_record": "results/review/05_label_match_review.csv",
            "title": titles.get(row.get("paper_id", ""), ""),
        })
    return rows


def institutional_disagreement_drops(titles: dict) -> list[dict]:
    """HLS papers dropped because NCI and NHLBI disagreed and neither is preferred.

    scripts/12_drop_institutional_disagreements.py's own log, not the review
    file directly -- that script physically drops the paper from the manifest,
    same as nhlbi_unreviewed_drops() and nonjudgeable_exclusion_drops() do for
    their own categories.
    """
    log = REVIEW_DIR / "12_institutional_disagreements_dropped.csv"
    if not log.exists():
        return []
    rows = []
    for row in read_csv(log):
        paper_id = row["paper_id"]
        rows.append({
            "paper_id": paper_id,
            "set": SET_HUMAN_LABELLED,
            "stage": "institutional_disagreement",
            "removed_from": "corpus",
            "reason": row["reason"],
            "evidence": f"NCI: {row.get('nci_answer', '')}; NHLBI: {row.get('nhlbi_answer', '')}",
            "decided_by": BY_HUMAN,
            "decided_at": row.get("dropped_at", ""),
            "source_record": "results/review/12_institutional_disagreements_dropped.csv",
            "title": titles.get(paper_id, ""),
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
              + merged_validation_duplicates()
              + manual_drops(manifest)
              + nhlbi_unreviewed_drops(titles)
              + nonjudgeable_exclusion_drops(titles)
              + institutional_disagreement_drops(titles)
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
    print("        results/01_corpus_build/unvalidated_set_summary.tex and must be cited separately.")

    pending = read_csv(REVIEW_DIR / "03_hls_internal_duplicates.csv")
    if pending:
        print(f"\n  PENDING: {len(pending)} HLS rows ({len(pending)//2} pairs) are flagged as")
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
