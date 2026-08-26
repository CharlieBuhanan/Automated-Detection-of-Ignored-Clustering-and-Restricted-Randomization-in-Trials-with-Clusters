"""Load the merged ground truth into SQLite and fix the build/holdout split (research design/PLAN.md step 4).

HOW TO RUN
    python scripts/04_load_ground_truth.py --dry-run          # report, write nothing
    python scripts/04_load_ground_truth.py                    # load into data/review.db
    python scripts/04_load_ground_truth.py --assign-split     # fix build/holdout, once

WHAT CHANGED
    This used to parse GroundTruthDataNCI01.xlsx itself -- citation parsing,
    author-position tie-breaking, the works. That join now lives in
    scripts/07_build_ground_truth.py, which reads every label source (currently
    three) and writes one merged, paper_id-resolved table to
    data/ground_truth.csv. This script's job shrank to what only it can do:
    collapsing that table into the one-row-per-paper `validation_labels` SQLite
    table, which is a real decision when two institutes reviewed the same
    paper, not a mechanical copy.

    Run `python scripts/07_build_ground_truth.py` first (or after any label file
    changes) to refresh data/ground_truth.csv before loading it here.

WHAT IT DOES
    Reads data/ground_truth.csv and, for each paper_id, decides what goes into
    validation_labels:

      one row for that paper_id           -> load it
      several rows, all agreeing          -> collapse to one, load it
      several rows that disagree          -> hold out BOTH, flag for a human
      no paper_id (citation never joined) -> hold out, flag for a human
      cited but never reviewed, still active  -> skip; not a label, not a problem
      cited but never reviewed, now dropped   -> skip; reported separately (see 09)

    The "several rows" case is real, not a corner case: 15 papers were fetched
    into both the NCI and NHLBI Zotero groups and independently reviewed by
    both institutes. 8 of the 15 pairs agree on every field. 7 do not --
    sometimes completely (one pair has NCI calling both analyses correct and
    NHLBI calling both incorrect, for the identical paper). Nothing is ever
    guessed here: a disagreement is not resolved by picking a side, because a
    wrong label silently corrupts every accuracy number computed after it. Both
    sides go to the review queue with each institute's answer spelled out, for
    a human to adjudicate by reading the paper.

    The exclusion gate is enforced here too, explicitly, rather than trusted
    from the source: any row with excluded=1 has power/stats/review_category
    forced to NULL regardless of what the source data says. This defends
    against exactly one known case -- tex entry 13 is marked "EXCLUDED but data
    preserved" and carries a full extraction despite being excluded -- and the
    project's hard rule is that an excluded paper gets no power/data row at
    all, not a stray one that happens to still be sitting in the source file.

OUTPUTS
    data/review.db                              validation_labels rows
    results/review/05_label_match_review.csv    rows needing a human, and why
    Terminal                                    reconciliation against the source
"""

import argparse
import collections
import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import db
from zotero_fetch import SET_HUMAN_LABELLED

ROOT = Path(__file__).resolve().parent.parent
GROUND_TRUTH = ROOT / "data" / "ground_truth.csv"
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
REVIEW = ROOT / "results" / "review" / "05_label_match_review.csv"

# The four fields that decide whether two institutes' reviews of the same
# paper actually agree. Design-extraction columns (cluster counts, ICC, ...)
# are NHLBI-only and never compared -- NCI has no opinion on them to disagree
# with.
LABEL_FIELDS = ("excluded", "exclusion_reason", "power_correct", "data_correct")

REVIEW_COLUMNS = ["problem", "paper_id", "source_file", "citation_raw",
                  "cite_key", "match_score", "nci_answer", "nhlbi_answer"]

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def read_ground_truth(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def describe(row: dict) -> str:
    """One-line human-readable summary of a row's label, for the review queue."""
    if row["excluded"] == "1":
        return f"excluded ({row['exclusion_reason'] or 'no reason recorded'})"
    bits = [f"power={row['power_correct'] or '?'}", f"data={row['data_correct'] or '?'}"]
    if row.get("review_category"):
        bits.append(f"category={row['review_category']}")
    return "kept, " + " ".join(bits)


def agrees(rows: list[dict]) -> bool:
    return len({tuple(r[f] for f in LABEL_FIELDS) for r in rows}) == 1


def collapse(rows: list[dict]) -> dict:
    """Multiple agreeing source rows for one paper -> one validation_labels row.

    Institute order is fixed (NCI first) purely for a deterministic
    source_file/matched_by string across re-runs -- the label values themselves
    are identical by construction, since this is only called after agrees().
    """
    rows = sorted(rows, key=lambda r: r["source_institute"] != "NCI")
    primary = rows[0]
    return {
        **primary,
        "source_file": "; ".join(dict.fromkeys(r["source_file"] for r in rows)),
        "citation_raw": " | ".join(dict.fromkeys(r["citation_raw"] for r in rows)),
        "matched_by": primary["matched_by"] + " (confirmed by both institutes)",
    }


def to_label_row(row: dict) -> dict:
    """ground_truth.csv row -> validation_labels insert dict.

    The gate is enforced here rather than trusted: power/stats/review_category
    are forced blank for any excluded paper, even if the source data carried a
    stray value (see tex entry 13 in the module docstring).
    """
    excluded = row["excluded"] == "1"
    score = row.get("match_score") or ""
    return {
        "paper_id": row["paper_id"],
        "source_file": row["source_file"],
        "citation_raw": row["citation_raw"],
        "exclusion_reason": row["exclusion_reason"] if excluded else None,
        "power": None if excluded else (row["power_correct"] or None),
        "stats": None if excluded else (row["data_correct"] or None),
        "review_category": None if excluded else (row.get("review_category") or None),
        "matched_by": row["matched_by"],
        "match_score": float(score) / 100 if score else None,
    }


def active_validation_paper_ids() -> set:
    """paper_ids the corpus currently expects a label for.

    The manifest's Human Labelled Set rows minus anything DROPPED -- not the raw label
    counts, which would double count the 15 NCI/NHLBI duplicate-pair papers
    that collapse to a single manifest row apiece.
    """
    with open(MANIFEST, encoding="utf-8") as handle:
        return {row["paper_id"] for row in csv.DictReader(handle)
                if row["set"] == SET_HUMAN_LABELLED and row["verdict"] != "DROPPED"}


def build(rows: list[dict], active: set) -> tuple[list[dict], list[dict], int, int]:
    """ground_truth.csv rows -> (label_rows, review_rows, pending, dropped).

    A `labeled == "0"` row (cited, never judged) means one of two different
    things depending on whether its paper is still in `active`: most are
    genuinely pending a future review, but scripts/09_drop_unreviewed_nhlbi.py
    formally drops some of them from the corpus, at which point they are not
    "not yet loaded" so much as "never going to be loaded" -- worth reporting
    separately so a shrinking `active` denominator doesn't read as a still-growing
    backlog.
    """
    unjoined = [r for r in rows if not r["paper_id"] and r["labeled"] == "1"]
    # A paper the manifest marks DROPPED is out of the corpus, so its label is
    # out of the scored set too -- otherwise a paper we deliberately removed
    # still sits in the accuracy denominator waiting to be counted as a miss.
    joined = [r for r in rows
              if r["paper_id"] and r["labeled"] == "1" and r["paper_id"] in active]
    unreviewed = [r for r in rows if r["labeled"] == "0"]
    pending = sum(1 for r in unreviewed if not r["paper_id"] or r["paper_id"] in active)
    dropped = len(unreviewed) - pending

    by_paper = collections.defaultdict(list)
    for row in joined:
        by_paper[row["paper_id"]].append(row)

    labels, review = [], []
    for paper_id, group in by_paper.items():
        if len(group) == 1 or agrees(group):
            labels.append(to_label_row(collapse(group) if len(group) > 1 else group[0]))
            continue
        by_inst = {r["source_institute"]: r for r in group}
        review.append({
            "problem": "institutional disagreement -- NCI and NHLBI reviewed this "
                       "paper independently and reached different answers",
            "paper_id": paper_id,
            "source_file": "; ".join(r["source_file"] for r in group),
            "citation_raw": "; ".join(r["citation_raw"] for r in group),
            "cite_key": "", "match_score": "",
            "nci_answer": describe(by_inst["NCI"]) if "NCI" in by_inst else "",
            "nhlbi_answer": describe(by_inst["NHLBI"]) if "NHLBI" in by_inst else "",
        })

    for row in unjoined:
        review.append({
            "problem": "citation did not resolve to a paper_id",
            "paper_id": "", "source_file": row["source_file"],
            "citation_raw": row["citation_raw"], "cite_key": row.get("cite_key", ""),
            "match_score": row.get("match_score", ""),
            "nci_answer": "", "nhlbi_answer": "",
        })

    return labels, review, pending, dropped


def write_review(rows: list[dict]) -> None:
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ground-truth", type=Path, default=GROUND_TRUTH,
                        help=f"merged label CSV to load (default: {GROUND_TRUTH.relative_to(ROOT)})")
    parser.add_argument("--dry-run", action="store_true", help="Report the load, write nothing")
    parser.add_argument("--assign-split", action="store_true",
                        help="Fix the build/holdout split after loading. Do this ONCE, when every label is in.")
    parser.add_argument("--holdout-frac", type=float, default=0.3)
    parser.add_argument("--force-split", action="store_true",
                        help="Re-assign an existing split. Only with a deliberate reason.")
    parser.add_argument("--allow-incomplete", action="store_true",
                        help="Allow --assign-split even while some active Human Labelled Set "
                             "papers still have no label. The split can only be fixed "
                             "once, so this is a deliberate override, not a default.")
    args = parser.parse_args()

    if not args.ground_truth.exists():
        raise SystemExit(f"{args.ground_truth} not found. Run "
                          f"scripts/07_build_ground_truth.py first.")

    rows = read_ground_truth(args.ground_truth)
    active = active_validation_paper_ids()
    labels, review, pending, dropped = build(rows, active)

    disagreements = sum(1 for r in review if r["problem"].startswith("institutional"))
    unresolved = len(review) - disagreements
    print(f"{args.ground_truth.relative_to(ROOT)}: {len(rows)} rows -> "
          f"{len(labels)} papers to load, {disagreements} institutional "
          f"disagreement(s), {unresolved} unresolved citation(s), "
          f"{pending} still pending review"
          + (f", {dropped} dropped from the corpus before review" if dropped else ""))

    covered = {r["paper_id"] for r in labels}
    missing = active - covered
    print(f"\ncorpus coverage: {len(covered)} of {len(active)} active HLS "
          f"papers will have a label ({len(missing)} still missing)")

    if review:
        write_review(review)
        print(f"\n{'='*70}\nNEEDS A HUMAN ({len(review)})\n{'='*70}")
        for row in review:
            print(f"  [{row['problem']}]")
            print(f"    {row['citation_raw']}")
            if row["nci_answer"] or row["nhlbi_answer"]:
                print(f"    NCI:   {row['nci_answer']}")
                print(f"    NHLBI: {row['nhlbi_answer']}")
        print(f"\n  -> {REVIEW.relative_to(ROOT)}")

    if args.dry_run:
        print("\n--dry-run: nothing written to the database.")
        return

    conn = db.connect()

    # This load is authoritative for anything not already locked into a split:
    # a paper this run decided to hold out (a newly found disagreement, a
    # citation that stopped resolving) must not leave a stale row behind from
    # an earlier run, or expected_decision() would keep scoring against an
    # answer this run explicitly refused to trust. A row that already carries
    # a split is never touched here -- assign_split() is the only thing
    # allowed to change what's in the holdout, and it can only run once.
    keep = {row["paper_id"] for row in labels}
    stale = [r["paper_id"] for r in conn.execute(
        "SELECT paper_id FROM validation_labels WHERE split IS NULL")
        if r["paper_id"] not in keep]
    if stale:
        conn.executemany("DELETE FROM validation_labels WHERE paper_id = ?",
                         [(p,) for p in stale])
        conn.commit()
        print(f"\npruned {len(stale)} stale row(s) no longer produced by this load "
              f"(and not already split): {', '.join(sorted(stale)[:10])}")

    db.insert_labels(conn, labels)
    print(f"\nloaded {len(labels)} label row(s) -> {db.DEFAULT_PATH}")

    if args.assign_split:
        if missing and not args.allow_incomplete:
            raise SystemExit(
                f"\n{len(missing)} of {len(active)} active HLS papers have no "
                f"label yet. Refusing to assign the split while incomplete -- it can "
                f"only be assigned once. Pass --allow-incomplete if you are "
                f"deliberately proceeding without them.\n"
                f"Missing: {', '.join(sorted(missing)[:10])}"
                f"{', ...' if len(missing) > 10 else ''}")
        counts = db.assign_split(conn, holdout_frac=args.holdout_frac, force=args.force_split)
        print(f"split fixed: {counts[db.SPLIT_BUILD]} build / {counts[db.SPLIT_HOLDOUT]} holdout")
        for stratum, split_counts in counts["strata"].items():
            print(f"  {stratum:10} {split_counts[db.SPLIT_BUILD]:4} build / "
                  f"{split_counts[db.SPLIT_HOLDOUT]:4} holdout")
    else:
        print("split not assigned. Run --assign-split once every label is loaded.")

    print("\nin the database now:")
    for key, value in db.label_counts(conn).items():
        print(f"  {key:22} {value}")


if __name__ == "__main__":
    main()
