"""Merge the NCI/NHLBI duplicate pairs inside the validation set into one row.

HOW TO RUN
    python scripts/06_merge_validation_duplicates.py --dry-run   # report only
    python scripts/06_merge_validation_duplicates.py             # do the merge

WHAT IT DOES
    The validation set was fetched from two Zotero groups, NCI and NHLBI, and
    15 papers sit in both. They arrived with different item keys, so paper_id
    cannot see that they are the same paper -- only the shared DOI/PMID can.

    Left alone each pair would be counted twice in every accuracy denominator,
    and worse, the two halves could land on opposite sides of the build/holdout
    split, putting the same paper in both.

    So each pair collapses to ONE manifest row:
      - the NCI row is kept, with its paper_id, PDF and attachment
      - its folder columns are rewritten to say the paper belongs to both
      - the NHLBI row is removed from the manifest
      - the NHLBI PDF is moved aside (never deleted) and its cached text dropped

    The NCI side is kept because the ground-truth labels that exist today are
    NCI's and are matched against papers in that collection. Keeping the other
    half would mean re-joining every label.

OUTPUTS
    data/zotero_manifest.csv                             15 rows fewer
    results/review/06_merged_validation_duplicates.csv   what merged into what
    data/removed_pdfs/hls_internal_duplicates/           the moved PDFs
"""

import argparse
import csv
import io
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from zotero_fetch import MANIFEST_COLUMNS, SET_HUMAN_LABELLED, set_dir

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
DUPLICATES = ROOT / "results" / "review" / "03_validation_internal_duplicates.csv"
LOG = ROOT / "results" / "review" / "06_merged_validation_duplicates.csv"
MOVED_DIR = ROOT / "data" / "removed_pdfs" / "hls_internal_duplicates"
CACHE_DIR = ROOT / "data" / "extracted_text"

# Written into `folder` and `folder_path` on a merged row. The point is that a
# reader scanning the manifest can tell at a glance that this row is not a
# plain NCI paper -- it stands for a paper both institutes filed.
MERGED_FOLDER = "Both NCI and NHLBI"
MERGED_FOLDER_PATH = "Both HLS Institutes"

KEEP_GROUP = "NCI"

LOG_COLUMNS = [
    "merged_at", "pair_id", "kept_paper_id", "removed_paper_id", "kept_group",
    "removed_group", "matched_on", "pdf_bytes_identical", "doi", "pmid", "title",
]

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def read_csv(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report only, change nothing")
    args = parser.parse_args()

    manifest = read_csv(MANIFEST)
    by_id = {r["paper_id"]: r for r in manifest}

    pairs = defaultdict(list)
    for row in read_csv(DUPLICATES):
        pairs[row["pair_id"]].append(row)

    if not pairs:
        sys.exit(f"No pairs in {DUPLICATES}.")

    plan, problems = [], []
    for pair_id, members in sorted(pairs.items()):
        if len(members) != 2:
            problems.append(f"{pair_id}: {len(members)} members, expected 2")
            continue
        keep = next((m for m in members if m["zotero_group"] == KEEP_GROUP), None)
        drop = next((m for m in members if m["zotero_group"] != KEEP_GROUP), None)
        if keep is None or drop is None:
            problems.append(f"{pair_id}: could not tell the two groups apart")
            continue
        # Already merged by an earlier run -- skip rather than move a PDF twice.
        if drop["paper_id"] not in by_id:
            continue
        if keep["paper_id"] not in by_id:
            problems.append(f"{pair_id}: kept paper {keep['paper_id']} is not in the manifest")
            continue
        plan.append((pair_id, keep, drop))

    if problems:
        print("PROBLEMS:")
        for line in problems:
            print(f"  {line}")
        print()

    print(f"{'='*74}\nMERGE PLAN ({len(plan)} pair(s))\n{'='*74}")
    for pair_id, keep, drop in plan:
        same = "identical" if drop["pdf_bytes_identical"] == "True" else "different bytes"
        print(f"  {pair_id}  keep {keep['paper_id']} (NCI)  <-  drop {drop['paper_id']} (NHLBI)  [{same}]")
        print(f"          {keep['title'][:84]}")

    if not plan:
        print("\nNothing to do -- already merged.")
        return
    if args.dry_run:
        print(f"\n--dry-run: manifest untouched ({len(manifest)} rows).")
        return

    removed_ids = {drop["paper_id"] for _, _, drop in plan}
    kept_ids = {keep["paper_id"] for _, keep, _ in plan}

    for row in manifest:
        if row["paper_id"] in kept_ids:
            row["folder"] = MERGED_FOLDER
            row["folder_path"] = MERGED_FOLDER_PATH
    merged_manifest = [r for r in manifest if r["paper_id"] not in removed_ids]

    MOVED_DIR.mkdir(parents=True, exist_ok=True)
    moved = 0
    for _pair_id, _keep, drop in plan:
        pdf = set_dir(ROOT, SET_HUMAN_LABELLED) / f"{drop['paper_id']}.pdf"
        if pdf.exists():
            shutil.move(str(pdf), str(MOVED_DIR / pdf.name))
            moved += 1
        # The kept row's text stands for the pair now; the other copy would
        # otherwise sit in the cache with no manifest row pointing at it.
        cached = CACHE_DIR / f"{drop['paper_id']}.json"
        cached.unlink(missing_ok=True)

    with MANIFEST.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(merged_manifest)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for pair_id, keep, drop in plan:
            writer.writerow({
                "merged_at": now, "pair_id": pair_id,
                "kept_paper_id": keep["paper_id"], "removed_paper_id": drop["paper_id"],
                "kept_group": keep["zotero_group"], "removed_group": drop["zotero_group"],
                "matched_on": "doi/pmid", "pdf_bytes_identical": drop["pdf_bytes_identical"],
                "doi": keep["doi"], "pmid": keep["pmid"], "title": keep["title"],
            })

    print(f"\n{'='*74}\nDONE\n{'='*74}")
    print(f"  manifest {len(manifest)} -> {len(merged_manifest)} rows")
    print(f"  {len(kept_ids)} row(s) marked '{MERGED_FOLDER}' / '{MERGED_FOLDER_PATH}'")
    print(f"  {moved} PDF(s) moved to {MOVED_DIR.relative_to(ROOT)}")
    print(f"  log -> {LOG}")


if __name__ == "__main__":
    main()
