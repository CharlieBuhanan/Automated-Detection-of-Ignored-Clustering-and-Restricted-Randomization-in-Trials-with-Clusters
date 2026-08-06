"""Pull the corpus out of Zotero into data/raw_pdfs/<set>/.

Fetches every record in the configured collection and all of its
subcollections, at any depth.

Usage:
    python scripts/00_fetch_zotero.py                                    # the testing corpus
    python scripts/00_fetch_zotero.py --collection ABCD1234 --set validation
    python scripts/00_fetch_zotero.py --dry-run                          # show the tree, download nothing

--set tags the rows it writes: "testing" (papers to classify) or "validation"
(papers with human labels). Zotero has no idea which is which, so it comes from
whichever collection you point at.

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
    collect_items,
    connect,
    fetch_records,
    resolve_subtree,
)

ROOT = Path(__file__).resolve().parent.parent


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


def main():
    """Walk the configured collection subtree, fetch every record's PDF with
    an md5 check, and merge the results into data/zotero_manifest.csv."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", help="Collection key or name to walk (overrides .env)")
    parser.add_argument(
        "--set",
        choices=[SET_TESTING, SET_VALIDATION],
        default=SET_TESTING,
        help="Which half of the corpus this collection holds (default: testing)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show the collection tree and record count without downloading")
    args = parser.parse_args()

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

    try:
        subtree = resolve_subtree(zot, root)
    except CollectionNotFound as exc:
        sys.exit(str(exc))

    print(f"{len(subtree)} collection(s) in scope:")
    for collection in subtree:
        print(f"  {collection['path']}  ({collection['meta'].get('numItems', '?')} items)")

    # Walked before downloading so the progress bar has a true total, and so
    # a paper filed in two collections is fetched once rather than twice.
    records = collect_items(zot, subtree)
    print(f"\n{len(records)} unique record(s)")

    if args.dry_run:
        return

    # One directory per set, so the split is visible in the file tree. The
    # manifest's `set` column stays authoritative -- it is what tells later
    # steps which directory to look in.
    pdf_dir = ROOT / "data" / "raw_pdfs" / args.set
    with tqdm(total=len(records), desc=f"Fetching ({args.set})") as progress:
        rows = fetch_records(zot, records, pdf_dir, set_name=args.set, progress=progress)

    manifest_path = ROOT / "data" / "zotero_manifest.csv"
    write_manifest(rows, manifest_path)

    counts = Counter(r["status"] for r in rows)
    print(f"\n{len(rows)} record(s) -> {manifest_path}")
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
