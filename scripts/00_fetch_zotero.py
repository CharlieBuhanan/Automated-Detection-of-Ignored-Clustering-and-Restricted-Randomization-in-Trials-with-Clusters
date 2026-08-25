"""Pull the corpus out of Zotero into data/raw_pdfs/<set>/.

Fetches every record in the configured collection and all of its
subcollections, at any depth.

Usage:
    python scripts/00_fetch_zotero.py                                    # the testing corpus
    python scripts/00_fetch_zotero.py --collection ABCD1234 --set validation
    python scripts/00_fetch_zotero.py --dry-run                          # show the tree, download nothing
    python scripts/00_fetch_zotero.py --list-warnings                    # print every warning on file, fetch nothing

--set tags the rows it writes: "testing" (papers to classify) or "validation"
(papers with human labels). Zotero has no idea which is which, so it comes from
whichever collection you point at.

The end-of-run summary (status counts, identifier coverage, warnings, failures)
covers only the records *this run* touched, not the whole manifest -- a
`--set validation` run no longer re-prints the testing set's old warnings.
`--list-warnings` is the way to see every warning ever recorded, across both
sets, on demand.

Requires in .env:
    ZOTERO_API_KEY          your Zotero API key
    ZOTERO_LIBRARY_ID       the group's numeric ID
    ZOTERO_COLLECTION_KEY   the collection to walk (8-char key; a name also works)
    ZOTERO_LIBRARY_TYPE     optional, default "group"

Idempotent: attachments already on disk with a matching md5 are skipped, so a
re-run is cheap and repairs a partial pull.
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from zotero_fetch import (
    MANIFEST_COLUMNS,
    SET_TESTING,
    SET_VALIDATION,
    STATUS_OK,
    CollectionNotFound,
    build_meta_records,
    collect_items,
    completed_ids,
    connect,
    iter_fetch_records,
    resolve_subtree,
)

ROOT = Path(__file__).resolve().parent.parent

# Rows written to the manifest between checkpoints. Rewriting a 1500-row CSV
# is trivial next to one HTTP request per paper, so this is cheap insurance
# against losing the whole run's bookkeeping to a crash at 95%.
CHECKPOINT_EVERY = 50


def load_manifest(path: Path) -> dict:
    """Read the manifest CSV back as {paper_id: row}. Empty if absent."""
    path = Path(path)
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["paper_id"]: row for row in csv.DictReader(handle)}


def write_manifest(rows: list[dict], path: Path) -> None:
    """Merge rows into the manifest CSV, keyed on paper_id.

    Merged rather than overwritten so this script never deletes rows it did
    not fetch -- the validation papers come from a different source and will
    share this file. Existing rows for the same paper_id are replaced, so a
    re-fetch still refreshes its own data.

    One row per record, successes and failures alike. PDFs are gitignored, so
    this table is the tracked, reproducible record of the corpus.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    merged = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            for existing in csv.DictReader(handle):
                merged[existing["paper_id"]] = existing
    for row in rows:
        merged[row["paper_id"]] = row

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(merged.values())


def write_meta_jsonl(meta_records: list[dict], path: Path) -> None:
    """Merge full Zotero metadata into data/zotero_meta.jsonl, keyed on paper_id.

    Same merge rule as the manifest, for the same reason: a `--set validation`
    run must not erase the rows a `--set testing` run wrote.

    This is the complete record -- including every author and Zotero's raw
    item -- where the manifest CSV is only the scannable summary.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    merged = {}
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    existing = json.loads(line)
                    merged[existing["paper_id"]] = existing
    for record in meta_records:
        merged[record["paper_id"]] = record

    with path.open("w", encoding="utf-8") as handle:
        for record in merged.values():
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    """Walk the configured collection subtree, fetch every record's PDF with
    an md5 check, and merge the results into data/zotero_manifest.csv and
    data/zotero_meta.jsonl."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", help="Collection key or name to walk (overrides .env)")
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        help="Collection name or key to skip, with everything under it. Repeatable. Defaults to ZOTERO_EXCLUDE_COLLECTIONS in .env (comma-separated).",
    )
    parser.add_argument(
        "--set",
        choices=[SET_TESTING, SET_VALIDATION],
        default=SET_TESTING,
        help="Which half of the corpus this collection holds (default: testing)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show the collection tree and record count without downloading")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-check every paper against Zotero, including ones already fetched. Without this, a paper whose manifest row is OK and whose PDF matches its md5 is skipped -- so a PDF swapped in Zotero after the first fetch is not noticed until you pass this.",
    )
    parser.add_argument(
        "--list-warnings",
        action="store_true",
        help="Print every warning recorded in the manifest (any set, any past run) and exit. No Zotero connection or .env needed.",
    )
    parser.add_argument(
        "--refetch-manual",
        action="store_true",
        help="Also re-fetch papers whose PDF a human replaced or cleared in scripts/03_review_mismatches.py. Off by default, because Zotero still holds the PDF the review rejected -- this would undo that work.",
    )
    args = parser.parse_args()

    if args.list_warnings:
        manifest_path = ROOT / "data" / "zotero_manifest.csv"
        rows = list(load_manifest(manifest_path).values())
        warned = [r for r in rows if r.get("warning")]
        if not warned:
            print(f"No warnings recorded in {manifest_path}")
            return
        print(f"{len(warned)} record(s) with a warning in {manifest_path}:")
        for row in warned:
            print(f"  {row['paper_id']} [{row.get('set', '?')}/{row['folder']}] {row['warning']}")
        return

    load_dotenv(ROOT / ".env")
    api_key = os.getenv("ZOTERO_API_KEY")
    library_id = os.getenv("ZOTERO_LIBRARY_ID")
    root = args.collection or os.getenv("ZOTERO_COLLECTION_KEY")
    if not api_key or not library_id:
        sys.exit("ZOTERO_API_KEY and ZOTERO_LIBRARY_ID must be set in .env")
    if not root:
        sys.exit("Set ZOTERO_COLLECTION_KEY in .env, or pass --collection")

    zot = connect(
        library_id,
        api_key,
        library_type=os.getenv("ZOTERO_LIBRARY_TYPE", "group"),
    )

    excluded = args.exclude
    if excluded is None:
        raw = os.getenv("ZOTERO_EXCLUDE_COLLECTIONS", "")
        excluded = [name.strip() for name in raw.split(",") if name.strip()]

    try:
        subtree = resolve_subtree(zot, root, exclude=excluded)
    except CollectionNotFound as exc:
        sys.exit(str(exc))

    if excluded:
        print(f"excluding: {', '.join(excluded)}")
    print(f"{len(subtree)} collection(s) in scope:")
    placements = 0
    for collection in subtree:
        n = collection["meta"].get("numItems", 0)
        placements += n
        print(f"  {collection['path']}  ({n} items)")

    # Walked before downloading so the progress bar has a true total, and so
    # a paper filed in two collections is fetched once rather than twice.
    records, skipped = collect_items(zot, subtree)

    # Placements minus unique records is the co-filing count. Printed because
    # a paper under two institutes is one paper, and counting placements is an
    # easy way to overstate the size of the corpus.
    print(f"\n{len(records)} unique paper(s) from {placements} collection placement(s)")
    multi = sum(1 for r in records.values() if len(r["folders"]) > 1)
    if multi:
        print(f"  {multi} paper(s) filed under more than one collection")

    if skipped:
        print(f"\nWARNING: {len(skipped)} non-paper item(s) skipped (not journalArticle):")
        for paper_id, item_type, title, folder in skipped:
            print(f"  {paper_id} [{folder}] {item_type}: {title[:70]}")

    if args.dry_run:
        return

    # One directory per set, so the split is visible in the file tree. The
    # manifest's `set` column stays authoritative -- it is what tells later
    # steps which directory to look in.
    pdf_dir = ROOT / "data" / "raw_pdfs" / args.set
    manifest_path = ROOT / "data" / "zotero_manifest.csv"
    meta_path = ROOT / "data" / "zotero_meta.jsonl"

    # Metadata needs no network -- collect_items already has everything. Write
    # it before the first download so no PDF ever sits on disk without a record
    # of what it is.
    write_meta_jsonl(build_meta_records(records, set_name=args.set), meta_path)
    print(f"{len(records)} record(s) of full metadata -> {meta_path}")

    existing = load_manifest(manifest_path)
    # Intersected with this run's records because the manifest and the PDF
    # directory are shared: NCI and NHLBI both land in raw_pdfs/validation/, so
    # an unintersected count reports the *other* group's papers as "skipping"
    # even though none of them are in this collection.
    skip_ids = set() if args.refresh else completed_ids(existing, pdf_dir) & set(records)

    # Papers a human adjudicated in scripts/03_review_mismatches.py are never
    # re-fetched, even under --refresh. Zotero still holds the PDF that was
    # rejected, so re-downloading would silently undo the review -- and that
    # work is far more expensive to recreate than a skipped HTTP request.
    manual = {
        pid for pid, row in existing.items()
        if row.get("verdict_reason", "").startswith("MANUAL_") and pid in records
    }
    if manual and not args.refetch_manual:
        skip_ids |= manual
        print(f"{len(manual)} manually reviewed paper(s) protected from re-fetch "
              f"(--refetch-manual to override)")

    if skip_ids:
        print(f"{len(skip_ids)} of {len(records)} already fetched, skipping (--refresh to re-check)")

    # Checkpointed so an interrupt or a crash still leaves a usable manifest.
    # write_manifest merges on paper_id, so a partial write is valid and the
    # next one just updates those rows.
    rows = []
    try:
        with tqdm(total=len(records), desc=f"Fetching ({args.set})") as progress:
            for row in iter_fetch_records(
                zot, records, pdf_dir,
                set_name=args.set, skip_ids=skip_ids, progress=progress,
            ):
                rows.append(row)
                if len(rows) % CHECKPOINT_EVERY == 0:
                    write_manifest(rows, manifest_path)
    finally:
        write_manifest(rows, manifest_path)

    # `rows` here is only what this run actually processed -- iter_fetch_records
    # never yields a row for a skip_ids paper, so a skipped, already-good record
    # doesn't get re-reported. That's what keeps this summary scoped to the
    # current --set/--collection instead of dredging up the other set's history.
    total_in_manifest = len(load_manifest(manifest_path))

    if not rows:
        print(f"\nNo new or re-checked records this run (all already up to date). "
              f"{total_in_manifest} record(s) total -> {manifest_path}")
        print("(--list-warnings to see every warning on file, across all runs and sets)")
        return

    counts = Counter(r["status"] for r in rows)
    print(f"\n{len(rows)} record(s) fetched/re-checked this run "
          f"({total_in_manifest} total in manifest) -> {manifest_path}")

    # Zotero has no PMID/PMCID field -- these are scraped out of Extra, the
    # URL, or archiveID. Coverage is worth knowing now, because these are the
    # identifiers that will join this corpus to the validation labels.
    for field in ("doi", "pmid", "pmcid"):
        have = sum(1 for r in rows if r[field])
        print(f"  {field}: {have}/{len(rows)} ({have / len(rows):.0%})" if rows else f"  {field}: 0")
    for status, count in counts.most_common():
        print(f"  {status}: {count}")

    # Records where more than one PDF was attached: the script picked one,
    # but which is the actual paper needs a human eye.
    warned = [r for r in rows if r.get("warning")]
    if warned:
        print(f"\nWARNING: {len(warned)} record(s) had multiple PDF attachments:")
        for row in warned:
            print(f"  {row['paper_id']} [{row['folder']}] {row['warning']}")

    # Anything without a usable PDF needs a human before the corpus is
    # complete -- list it now rather than discovering the gap at classification.
    failures = [r for r in rows if r["status"] != STATUS_OK]
    if failures:
        print(f"\n{len(failures)} record(s) need attention:")
        for row in failures:
            print(f"  {row['paper_id']} [{row['folder']}] {row['status']}: {row['detail']}")
            print(f"    {row['title'][:90]}")


if __name__ == "__main__":
    main()
