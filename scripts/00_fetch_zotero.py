"""Pull the corpus out of Zotero into data/raw_pdfs/all/.

Usage:
    python scripts/00_fetch_zotero.py
    python scripts/00_fetch_zotero.py --institute NCI     # one subcollection
    python scripts/00_fetch_zotero.py --dry-run           # list records, download nothing

Requires in .env:
    ZOTERO_API_KEY, ZOTERO_LIBRARY_ID
    ZOTERO_LIBRARY_TYPE   (optional, default "group")
    ZOTERO_ROOT_COLLECTION (optional, default "Boring Task")

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
    ROOT_COLLECTION_NAME,
    STATUS_OK,
    CollectionNotFound,
    connect,
    fetch_collection,
    resolve_institutes,
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
    """Resolve the institute subcollections, fetch every record's PDF with an
    md5 check, and write data/zotero_manifest.csv."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--institute", help="Only fetch this institute subcollection")
    parser.add_argument("--dry-run", action="store_true", help="Resolve collections and count records without downloading")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    api_key = os.getenv("ZOTERO_API_KEY")
    library_id = os.getenv("ZOTERO_LIBRARY_ID")
    if not api_key or not library_id:
        sys.exit("ZOTERO_API_KEY and ZOTERO_LIBRARY_ID must be set in .env")

    zot = connect(
        library_id,
        api_key,
        library_type=os.getenv("ZOTERO_LIBRARY_TYPE", "group"),
    )
    root_name = os.getenv("ZOTERO_ROOT_COLLECTION", ROOT_COLLECTION_NAME)

    try:
        institutes = resolve_institutes(zot, root_name)
    except CollectionNotFound as exc:
        sys.exit(str(exc))

    if args.institute:
        institutes = [c for c in institutes if c["data"]["name"] == args.institute]
        if not institutes:
            sys.exit(f"No institute subcollection named {args.institute!r} under {root_name!r}")

    print(f"{root_name}: {len(institutes)} institute subcollection(s)")
    for c in institutes:
        print(f"  {c['data']['name']}: {c['meta'].get('numItems', '?')} items")

    if args.dry_run:
        return

    pdf_dir = ROOT / "data" / "raw_pdfs" / "all"
    total = sum(c["meta"].get("numItems", 0) for c in institutes)

    rows = []
    with tqdm(total=total, desc="Fetching") as progress:
        for institute in institutes:
            rows.extend(fetch_collection(zot, institute, pdf_dir, progress=progress))

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
            print(f"  {row['paper_id']} [{row['institute']}] {row['warning']}")

    # Anything without a usable PDF needs a human before the corpus is
    # complete -- list it now rather than discovering the gap at classification.
    failures = [r for r in rows if r["status"] != STATUS_OK]
    if failures:
        print(f"\n{len(failures)} record(s) need attention:")
        for row in failures:
            print(f"  {row['paper_id']} [{row['institute']}] {row['status']}: {row['detail']}")
            print(f"    {row['title'][:90]}")


if __name__ == "__main__":
    main()
