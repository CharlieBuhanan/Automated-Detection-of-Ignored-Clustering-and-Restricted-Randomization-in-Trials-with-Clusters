"""Drop HLS papers whose label a reviewer has judged wrong, pending expert re-review.

WHY
    DC50. A label two trained reviewers produced is not something we quietly edit:
    correcting it in place would make the labels partly *our* opinion rather than
    theirs, which DC46 commits the write-up to not claiming. But scoring against a
    label the reviewers themselves now say is wrong reproduces DC37's problem --
    a number computed against an answer nobody stands behind.

    So the paper leaves the scored set the same way the institutional
    disagreements did: moved, logged, and reversible. Keith and Deb adjudicate the
    pile after 2026-09-02; whatever they decide, `16_reapply_drops.py` and the log
    below are enough to restore or re-score any row here.

    TWO KINDS OF MEMBER, AND THE ADJUDICATOR NEEDS TO TELL THEM APART
    (a) A label a *reviewer read and rejected* -- Cattamanchi. Strongest case.
    (b) A label contradicted by a *criterion the reviewers themselves ruled on*,
        where nobody has re-read the row -- the 5 analyzed stepped wedges.

    (b) was originally excluded from this pile: DC51 kept those 5 in the scored
    set as accepted misses, on the reasoning that reporting real human
    disagreement beats curating it away. **Reversed 2026-08-27 (DC52.)** The
    reasoning held while E3 was contested; once Deb ruled E3 ON (DC48), NHLBI's
    own 9 stepped-wedge exclusions contradict these 5 keeps, so scoring against
    them is DC37's problem exactly -- a number computed against an answer nobody
    stands behind. Dropping is reversible and loses no data; keeping them baked a
    -0.9pp build / -1.4pp holdout floor into every exclusion figure in the study.

    `judged_by` says which kind each row is. Do not flatten that in the meeting.

MEMBERS
    One dict per paper in PILE below. Adding a member is a one-line edit; say who
    judged it wrong and what is wrong with it, because that sentence is what the
    adjudicator reads first.

OUTPUTS
    data/zotero_manifest.csv                          rows marked DROPPED
    results/review/18_expert_review_dropped.csv       what left, and why
    data/removed_pdfs/expert_review/                  the moved PDFs
    data/removed_pdfs/expert_review/extracted_text/   the moved cached text

AFTER RUNNING
    python scripts/07_build_ground_truth.py
    python scripts/04_load_ground_truth.py --allow-split-prune
    python scripts/05_build_exclusions.py --check

    `--allow-split-prune` is required and is the point: these papers carry a split,
    so removing them shrinks it. The split is never re-cut (DC47) -- a re-cut would
    reshuffle every round and make all of them incomparable.
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
LOG = ROOT / "results" / "review" / "18_expert_review_dropped.csv"
MOVED_PDF_DIR = ROOT / "data" / "removed_pdfs" / "expert_review"
MOVED_TEXT_DIR = MOVED_PDF_DIR / "extracted_text"
PDF_DIR = set_dir(ROOT, SET_HUMAN_LABELLED)
CACHE_DIR = ROOT / "data" / "extracted_text"

VERDICT_REASON = "EXPERT_REVIEW_PENDING"

PILE = [
    {
        "paper_id": "XHFTHUCG",
        "citation": "Cattamanchi et al. 2021",
        "judged_by": "Deb, 2026-08-27",
        "what_is_wrong":
            "Restricted randomization present (stratified) and not accounted for: data_done is "
            "'adjusted poisson regression accounting for clinic', which handles clustering only. "
            "The row's own data_should says 'Account for restricted rand. and clustering', so the "
            "label contradicts itself -- and ~40 papers of exactly this shape were scored no. "
            "Scored data_correct=yes anyway.",
    },
]

# The 5 stepped-wedge papers NHLBI kept and fully scored, while excluding 9 other
# papers for `stepped_wedge_design`. Same reason for all five, so it is written
# once rather than copy-pasted into five near-identical strings that would drift.
STEPPED_WEDGE_WRONG = (
    "Analyzed stepped-wedge trial, labelled KEEP. NHLBI excluded 9 other papers for "
    "stepped_wedge_design and kept these 5, so the label set contradicts itself. Deb ruled "
    "2026-08-27 that stepped wedge IS an exclusion (DC48) -- she settled the CRITERION and has "
    "NOT re-read this row, which is what the adjudication is for. Under E3 the promptbook "
    "excludes it while the label keeps it, so it is unscoreable either way (DC52 reverses DC51)."
)

PILE += [
    {"paper_id": pid, "citation": citation,
     "judged_by": "criterion (Deb's DC48 ruling, 2026-08-27) -- row not individually re-read",
     "what_is_wrong": STEPPED_WEDGE_WRONG}
    for pid, citation in [
        ("3JVAWNIE", "Bernabe-Ortiz et al. 2020"),
        ("TT7PIVLD", "Ciccone et al."),
        # Douin is also one of Deb.md's 7 restricted-randomization rows -- two
        # independent reasons to look at it, one meeting.
        ("7NYXSVAI", "Douin et al. 2025"),
        ("QMLU4TM8", "Courtright et al."),
        ("8H9BUEWH", "Fiscella et al."),
    ]
]

LOG_COLUMNS = ["dropped_at", "paper_id", "citation", "judged_by", "what_is_wrong",
               "pdf_moved_to", "extracted_text_moved_to", "reason"]

REASON = ("A reviewer has judged this paper's label wrong (see what_is_wrong). Dropped rather "
          "than corrected in place, because editing a label would make it our opinion rather "
          "than the reviewers' (DC46/DC50). Pending expert re-review by Keith and Deb after "
          "2026-09-02; restorable.")

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report only, change nothing")
    args = parser.parse_args()

    manifest = read_csv(MANIFEST)
    by_id = {r["paper_id"]: r for r in manifest}

    plan, already, missing = [], [], []
    for entry in PILE:
        row = by_id.get(entry["paper_id"])
        if row is None:
            missing.append(entry)
        elif row.get("verdict") == "DROPPED":
            already.append((entry, row))
        else:
            plan.append((entry, row))

    print(f"{'='*74}\nEXPERT-REVIEW DROP PLAN\n{'='*74}")
    print(f"  {len(plan)} to drop, {len(already)} already dropped, {len(missing)} not in manifest")
    for entry, row in plan:
        print(f"\n  {entry['paper_id']}  {entry['citation']}")
        print(f"    judged by : {entry['judged_by']}")
        print(f"    title     : {row['title'][:60]}")
        print(f"    wrong     : {entry['what_is_wrong'][:100]}...")
    for entry, row in already:
        print(f"  = {entry['paper_id']}  already DROPPED ({row.get('verdict_reason')})")
    for entry in missing:
        print(f"  !! {entry['paper_id']} not in the manifest -- skipping")

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
    for entry, row in plan:
        paper_id = entry["paper_id"]
        row["verdict"] = "DROPPED"
        row["verdict_reason"] = VERDICT_REASON

        moved = {}
        for key, src, dest_dir in [
                ("pdf_moved_to", PDF_DIR / f"{paper_id}.pdf", MOVED_PDF_DIR),
                ("extracted_text_moved_to", CACHE_DIR / f"{paper_id}.json", MOVED_TEXT_DIR)]:
            if src.exists():
                dest = dest_dir / src.name
                src.rename(dest)
                moved[key] = str(dest.relative_to(ROOT))
            else:
                moved[key] = ""

        log_rows.append({"dropped_at": now, **{k: entry[k] for k in
                         ("paper_id", "citation", "judged_by", "what_is_wrong")},
                         **moved, "reason": REASON})

    with MANIFEST.open("w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        w.writeheader(); w.writerows(manifest)

    # Complete-record log, same reasoning as scripts 10 and 12: a re-run must not
    # erase earlier drops just because it skips papers already DROPPED.
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
    print("\n  Next:")
    print("    python scripts/07_build_ground_truth.py")
    print("    python scripts/04_load_ground_truth.py --allow-split-prune")
    print("    python scripts/05_build_exclusions.py --check")


if __name__ == "__main__":
    main()
