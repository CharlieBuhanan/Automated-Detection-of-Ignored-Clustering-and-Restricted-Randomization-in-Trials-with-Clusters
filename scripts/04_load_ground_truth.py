"""NOT READY -- waiting on the rest of the ground truth. Do not build on this.

Only GroundTruthDataNCI01.xlsx exists so far, covering 232 of the 569
validation papers. This script works on that file, and the 230 rows it loaded
into data/review.db are a provisional load meant for inspection, not a base to
build on -- expect to discard and reload once the remaining label files arrive.

What could still change when they do:
  - SOURCE_FOLDERS needs an entry per new file, and the mapping is guessed
    from filename prefixes
  - **SOURCE_FOLDERS no longer covers every validation paper.** The 15
    NCI/NHLBI duplicate pairs were merged into single rows carrying
    folder="Both NCI and NHLBI", which matches neither entry, so those 15
    papers currently fall out of BOTH candidate pools and their labels would
    fail to join. The folder filter has to accept the merged marker for both
    files before this script is run again.
  - the "Combined" sheet name and the four column headers are NCI's; another
    institute may name or split them differently
  - the citation format is assumed to be APA author-year, which held for
    232/232 NCI rows but is not guaranteed elsewhere
  - the build/holdout split is deliberately NOT assigned yet

Read the rest of this docstring as a description of intent, not of finished work.

---

Load the human labels into SQLite and join them to paper_ids (PLAN.md step 4).

HOW TO RUN
    python scripts/04_load_ground_truth.py --dry-run      # report, write nothing
    python scripts/04_load_ground_truth.py                # load into data/review.db
    python scripts/04_load_ground_truth.py --assign-split # fix build/holdout, once

WHAT IT DOES
    Reads every GroundTruth*.xlsx it can find, parses each row's citation, and
    works out which corpus paper it refers to.

    The join is the hard part. The labels identify papers the way a reference
    list does -- "83. (Hershman, Bansal, Barlow, et al., 2023)" -- with no DOI,
    no PMID, and no Zotero key. So the citation is parsed back into (first
    author surname, year) and matched against the Zotero metadata:

      1. first author + year unique in the folder      -> matched
      2. two papers share both, but the citation lists
         extra authors (APA adds them until the cite is
         unique) -> compare them by author *position*  -> matched
      3. anything left, including "2022a"/"2022b"      -> review queue

    Measured on GroundTruthDataNCI01.xlsx: 216 by rule 1, 14 by rule 2, 2 to
    review. Nothing is ever guessed -- a wrong label is worse than a missing
    one, because it silently corrupts every accuracy number computed after it.

OUTPUTS
    data/review.db                              validation_labels rows
    results/review/05_label_match_review.csv    citations needing a human
    Terminal                                    reconciliation against the source
"""

import argparse
import collections
import csv
import io
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import db
from identity import normalize
from zotero_fetch import load_meta

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
META = ROOT / "data" / "zotero_meta.jsonl"
REVIEW = ROOT / "results" / "review" / "05_label_match_review.csv"

# Where a label file's papers live in the corpus. The spreadsheets are named
# per institute and each covers one Zotero collection, so the folder is what
# scopes the search -- matching "Lee 2022" against all 1,856 papers instead of
# the 232 in its own collection would invent ambiguity that does not exist.
SOURCE_FOLDERS = {
    "GroundTruthDataNCI": "FinalCollectionFor Publication",
    "GroundTruthDataNHLBI": "Locked_26_01_08_337",
}

REVIEW_COLUMNS = [
    "source_file", "citation_raw", "first_author", "year", "problem",
    "candidates", "candidate_titles",
]

# "83. (Hershman, Bansal, Barlow, et al., 2023)" and "(Smith & Jones, 2019)"
CITE = re.compile(r"^\s*(?:\d+\.)?\s*\((.+?),\s*(\d{4})([a-z]?)\)\s*$")
# "R. E. Lee" -> "Lee". Initials appear only when two first authors share a
# surname, which is precisely when the surname alone is not enough.
INITIALS = re.compile(r"^(?:[A-Z]\.\s*)+")

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def parse_citation(raw: str) -> tuple[str, list[str], str, str] | None:
    """"12. (Harry, Asche, et al., 2022)" -> ("Harry", ["Asche"], "2022", "").

    The trailing letter of "2022a" is returned separately: it means the labeller
    had two papers this citation could not tell apart, so it is a signal to stop
    rather than a part of the year.
    """
    match = CITE.match(str(raw))
    if not match:
        return None
    names = re.sub(r"\bet\s+al\.?", "", match.group(1))
    parts = [INITIALS.sub("", p.strip()).strip() for p in re.split(r"[,&]", names) if p.strip()]
    if not parts:
        return None
    return parts[0], parts[1:], match.group(2), match.group(3)


def author_index(paper_ids: list[str], meta: dict) -> dict:
    """(normalized first-author surname, year) -> [paper_id, ...]"""
    index = collections.defaultdict(list)
    for paper_id in paper_ids:
        record = meta.get(paper_id, {})
        authors = record.get("authors") or [""]
        index[(normalize(authors[0]), str(record.get("year") or ""))].append(paper_id)
    return index


def positional_score(paper_id: str, extra: list[str], meta: dict) -> int:
    """How many disambiguating surnames sit at the author position APA implies.

    APA extends a citation one author at a time until it is unique, so the
    names after the first are the 2nd, 3rd, ... authors in order. Checking
    position rather than mere membership is what separates two papers by the
    same research group, where every name appears on both.
    """
    authors = [normalize(a) for a in (meta.get(paper_id, {}).get("authors") or [])]
    return sum(1 for i, name in enumerate(extra)
               if i + 1 < len(authors) and authors[i + 1] == normalize(name))


def match_one(parsed, index, meta) -> tuple[str | None, str, str]:
    """Resolve one citation. Returns (paper_id or None, matched_by, problem)."""
    first, extra, year, suffix = parsed
    candidates = index.get((normalize(first), year), [])

    if suffix:
        # "2022a" means the labeller themselves could not distinguish two
        # papers by author and year. Neither can we.
        return None, "", f"ambiguous citation suffix '{year}{suffix}'"
    if not candidates:
        return None, "", "no paper with this first author and year"
    if len(candidates) == 1:
        return candidates[0], "first_author_year", ""

    scored = sorted(((positional_score(p, extra, meta), p) for p in candidates), reverse=True)
    if len(scored) > 1 and scored[0][0] > scored[1][0]:
        return scored[0][1], "author_position", ""
    return None, "", f"{len(candidates)} papers share this first author and year"


def folder_for(path: Path) -> str | None:
    for prefix, folder in SOURCE_FOLDERS.items():
        if path.stem.startswith(prefix):
            return folder
    return None


def load_file(path: Path, manifest_rows: list[dict], meta: dict):
    """Parse and join one label file. Returns (label_rows, review_rows)."""
    folder = folder_for(path)
    if folder is None:
        raise SystemExit(
            f"{path.name}: no folder mapping. Add its prefix to SOURCE_FOLDERS "
            f"(known: {', '.join(SOURCE_FOLDERS)}).")

    paper_ids = [r["paper_id"] for r in manifest_rows
                 if r["set"] == "validation" and r["folder"] == folder]
    if not paper_ids:
        raise SystemExit(f"{path.name}: no validation papers in folder {folder!r}.")

    frame = pd.read_excel(path, sheet_name="Combined")
    index = author_index(paper_ids, meta)

    labels, review = [], []
    for _, row in frame.iterrows():
        raw = str(row["Citation"]).strip()
        if not raw or raw.lower() == "nan":
            continue

        parsed = parse_citation(raw)
        if parsed is None:
            review.append({"source_file": path.name, "citation_raw": raw,
                           "first_author": "", "year": "",
                           "problem": "could not parse the citation",
                           "candidates": "", "candidate_titles": ""})
            continue

        paper_id, matched_by, problem = match_one(parsed, index, meta)
        first, _extra, year, suffix = parsed

        if paper_id is None:
            candidates = index.get((normalize(first), year), [])
            review.append({
                "source_file": path.name, "citation_raw": raw,
                "first_author": first, "year": f"{year}{suffix}", "problem": problem,
                "candidates": "; ".join(candidates),
                "candidate_titles": " | ".join(
                    (meta.get(c, {}).get("title") or "")[:70] for c in candidates),
            })
            continue

        labels.append({
            "paper_id": paper_id,
            "source_file": path.name,
            "citation_raw": raw,
            "exclusion_reason": clean(row.get("Reason excluded")),
            "power": clean(row.get("Power")),
            "stats": clean(row.get("Stats")),
            "review_category": clean(row.get("Review Category")),
            "matched_by": matched_by,
            "match_score": 1.0 if matched_by == "first_author_year" else 0.9,
        })

    return labels, review


def clean(value) -> str | None:
    """Spreadsheet cell -> stripped string, or None for blank/NaN.

    A blank matters here: no exclusion reason means the paper was kept, and no
    Power/Stats value means it never reached that task. Storing "" and NULL
    interchangeably would erase that distinction.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def write_review(rows: list[dict]) -> None:
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def find_label_files(explicit: list[str] | None) -> list[Path]:
    if explicit:
        return [Path(p) for p in explicit]
    found = sorted(ROOT.glob("GroundTruth*.xlsx")) + sorted((ROOT / "data" / "labels").glob("GroundTruth*.xlsx"))
    if not found:
        raise SystemExit("No GroundTruth*.xlsx found in the repo root or data/labels/.")
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", nargs="*", help="Label .xlsx files (default: GroundTruth*.xlsx)")
    parser.add_argument("--dry-run", action="store_true", help="Report the join, write nothing")
    parser.add_argument("--assign-split", action="store_true",
                        help="Fix the build/holdout split after loading. Do this ONCE, when every label file is in.")
    parser.add_argument("--holdout-frac", type=float, default=0.3)
    parser.add_argument("--force-split", action="store_true",
                        help="Re-assign an existing split. Only with a deliberate reason.")
    args = parser.parse_args()

    manifest_rows = list(csv.DictReader(MANIFEST.open(newline="", encoding="utf-8")))
    meta = load_meta(META)
    files = find_label_files(args.labels)

    all_labels, all_review = [], []
    for path in files:
        labels, review = load_file(path, manifest_rows, meta)
        all_labels.extend(labels)
        all_review.extend(review)

        folder = folder_for(path)
        in_corpus = sum(1 for r in manifest_rows
                        if r["set"] == "validation" and r["folder"] == folder)
        print(f"{path.name}: {len(labels) + len(review)} citations -> "
              f"{len(labels)} matched, {len(review)} to review "
              f"({in_corpus} papers in that collection)")

    by_method = collections.Counter(r["matched_by"] for r in all_labels)
    print(f"\n{'='*70}\nJOIN ({len(all_labels)} matched, {len(all_review)} unresolved)\n{'='*70}")
    for method, n in by_method.most_common():
        print(f"  {method:22} {n:5}")

    collisions = [pid for pid, n in collections.Counter(
        r["paper_id"] for r in all_labels).items() if n > 1]
    if collisions:
        print(f"\n!! {len(collisions)} paper(s) claimed by more than one citation: "
              f"{collisions[:5]}\n   Resolve these before loading -- one of the labels is wrong.")

    labelled = collections.Counter()
    for row in all_labels:
        for field in ("exclusion_reason", "power", "stats", "review_category"):
            if row[field]:
                labelled[field] += 1
    print("\nlabel coverage:")
    for field, n in labelled.most_common():
        print(f"  {field:22} {n:5}")

    if all_review:
        write_review(all_review)
        print(f"\n{'='*70}\nNEEDS A HUMAN ({len(all_review)})\n{'='*70}")
        for row in all_review:
            print(f"  {row['citation_raw']}  --  {row['problem']}")
            if row["candidates"]:
                print(f"      {row['candidates']}")
                print(f"      {row['candidate_titles']}")
        print(f"\n  -> {REVIEW}")
        print("     Fill in the right paper_id by hand, then re-run.")

    if args.dry_run:
        print("\n--dry-run: nothing written to the database.")
        return
    if collisions:
        raise SystemExit("\nRefusing to load while two citations claim the same paper.")

    conn = db.connect()
    db.insert_labels(conn, all_labels)
    print(f"\nloaded {len(all_labels)} label row(s) -> {db.DEFAULT_PATH}")

    if args.assign_split:
        counts = db.assign_split(conn, holdout_frac=args.holdout_frac, force=args.force_split)
        print(f"split fixed: {counts[db.SPLIT_BUILD]} build / {counts[db.SPLIT_HOLDOUT]} holdout")
    else:
        print("split not assigned. Run --assign-split once every label file is loaded.")

    print("\nin the database now:")
    for key, value in db.label_counts(conn).items():
        print(f"  {key:22} {value}")


if __name__ == "__main__":
    main()
