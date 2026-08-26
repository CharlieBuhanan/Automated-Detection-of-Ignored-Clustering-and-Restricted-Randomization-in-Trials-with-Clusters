"""Restore US papers whose HLS twin was dropped after the cross-set removal (DC42).

WHY
    207 Unlabelled Set papers were removed because an identical Human Labelled Set
    copy already carried a human answer (DC2), so classifying them blind would waste
    a call and risk a leaked-label sanity check.

    That reason is conditional on the HLS copy surviving. 23 of those copies have
    since been dropped themselves -- coin-flip exclusions (E17), NHLBI papers never
    reviewed, institutional disagreements, one protocol paper -- and for those the US
    twin is no longer a duplicate of anything. Leaving it out would drop the paper
    from the study entirely rather than moving it between sets, which is the one
    outcome the exclusion ledger exists to prevent.

    Run scripts/13_check_hls_clean.py first. Every further HLS drop creates more
    candidates, so restoring before the HLS is closed leaves the corpus in a state
    no single script explains.

WHY A ZOTERO ROUND TRIP
    The removal pruned data/zotero_meta.jsonl, so first_author, the full author list
    and attachment_key are not recoverable from local files -- and author_frac needs
    every surname. The 23 items are fetched by key rather than by walking the
    collection: the walk would resurrect all 207, which is exactly wrong.

    The archived PDFs in data/removed_pdfs/us_cross_set_duplicates/ are kept, not
    moved. The fresh download is what gets verified against Zotero's md5; the
    archived copy stays as the record of what was originally removed, and a
    mismatch between the two is reported rather than silently overwritten.

OUTPUTS
    data/zotero_manifest.csv                  23 rows merged back in
    data/zotero_meta.jsonl                    their full metadata restored
    data/raw_pdfs/Unlabelled Set/             their PDFs re-downloaded
    results/review/15_dc42_restored.csv       what came back, and why

AFTER RUNNING
    scripts/01_verify_identity.py   -- restored rows have no verdict yet
    scripts/02_extract_pdfs.py      -- nothing is cached for them
    scripts/11_scan_text_integrity.py
    scripts/05_build_exclusions.py  -- the ledger count changes
    scripts/14_check_us_clean.py    -- U9 should now pass
"""

import argparse
import csv
import io
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import db  # noqa: E402
from zotero_fetch import (  # noqa: E402
    SET_UNLABELLED,
    build_meta_records,
    collect_items_by_key,
    connect,
    iter_fetch_records,
    set_dir,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from importlib import import_module  # noqa: E402

_fetch = import_module("00_fetch_zotero")
load_manifest, write_manifest, write_meta_jsonl = (
    _fetch.load_manifest, _fetch.write_manifest, _fetch.write_meta_jsonl)

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
META = ROOT / "data" / "zotero_meta.jsonl"
REMOVED_LOG = ROOT / "results" / "review" / "02_removed_us_duplicates.csv"
EXCLUSIONS = ROOT / "results" / "01_corpus_build" / "exclusions.csv"
LOG = ROOT / "results" / "review" / "15_dc42_restored.csv"
ARCHIVE = ROOT / "data" / "removed_pdfs" / "us_cross_set_duplicates"
PDF_DIR = set_dir(ROOT, SET_UNLABELLED)

# The collection root every Unlabelled Set paper sits under. The removal log
# records the institute folder but not the path to it, and one round trip per
# collection to re-derive the names is not worth it for a constant.
ROOT_COLLECTION = "Boring Task"

# The group the Unlabelled Set was fetched from ("Glykos"). Hardcoded because
# .env's ZOTERO_LIBRARY_ID points at whichever group was fetched last -- the two
# HLS groups came after the US, so reading it here fetches from the wrong
# library and every item key 404s. Override with --library-id.
US_LIBRARY_ID = "6586218"

LOG_COLUMNS = ["restored_at", "paper_id", "twin_paper_id", "twin_drop_reason",
               "matched_on", "folder", "status", "md5_matches_archive", "title"]

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def find_candidates() -> list[dict]:
    """Removed US papers whose HLS twin no longer carries a label.

    The label table is the authority, not the manifest: a twin can be gone from
    the manifest (merged internal duplicate) while its label survives on the
    paper it was merged into, and that twin's US copy must stay removed.
    """
    conn = sqlite3.connect(f"file:{db.DEFAULT_PATH}?mode=ro", uri=True)
    labelled = {r[0] for r in conn.execute("SELECT paper_id FROM validation_labels")}
    conn.close()
    return [r for r in read_csv(REMOVED_LOG)
            if r["matched_validation_paper_id"] not in labelled]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report only, change nothing")
    parser.add_argument("--library-id", default=US_LIBRARY_ID,
                        help="Zotero group holding the Unlabelled Set (default: %(default)s). "
                             ".env points at whichever group was fetched last, which is "
                             "usually one of the HLS groups, so this does not read it.")
    args = parser.parse_args()

    candidates = find_candidates()
    if not candidates:
        print("Nothing to restore: every removed US paper's twin still carries a label.")
        return

    manifest = load_manifest(MANIFEST)
    already = [r for r in candidates if r["removed_paper_id"] in manifest]
    todo = [r for r in candidates if r["removed_paper_id"] not in manifest]

    reasons = {r["paper_id"]: r["reason"] for r in read_csv(EXCLUSIONS)}

    print(f"{len(candidates)} restore candidate(s); {len(already)} already in the manifest, "
          f"{len(todo)} to fetch.")
    for row in todo:
        twin = row["matched_validation_paper_id"]
        print(f"  {row['removed_paper_id']}  <- twin {twin}  {reasons.get(twin, '?')[:60]}")

    if args.dry_run:
        print("\n--dry-run: nothing fetched, nothing written.")
        return
    if not todo:
        print("\nNothing to fetch.")
        return

    load_dotenv(ROOT / ".env")
    zot = connect(args.library_id, os.environ["ZOTERO_API_KEY"],
                  os.environ.get("ZOTERO_LIBRARY_TYPE", "group"))

    # The removal log kept the institute folder(s); rebuild the path around it
    # rather than walking the collection to re-derive names.
    folders = {}
    for row in todo:
        names = [f.strip() for f in (row["nih_institute_folder"] or "").split(";") if f.strip()]
        folders[row["removed_paper_id"]] = (
            names, [f"{ROOT_COLLECTION} / {name}" for name in names])

    paper_ids = [r["removed_paper_id"] for r in todo]
    print(f"\nfetching {len(paper_ids)} item(s) by key...")
    records, skipped = collect_items_by_key(zot, paper_ids, folders=folders)
    for paper_id, item_type, title, _ in skipped:
        print(f"  !! {paper_id} is a {item_type}, not a paper -- skipped: {title[:60]}")

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    with tqdm(total=len(records), unit="paper") as progress:
        rows = list(iter_fetch_records(zot, records, PDF_DIR,
                                       set_name=SET_UNLABELLED, progress=progress))

    write_manifest(rows, MANIFEST)
    write_meta_jsonl(build_meta_records(records, set_name=SET_UNLABELLED), META)

    # A fresh download that does not match the archived copy means the Zotero
    # attachment changed since the removal. Reported, never resolved silently --
    # the archive is the evidence of what was originally taken out.
    by_id = {r["removed_paper_id"]: r for r in todo}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log_rows, drifted = [], []
    for row in rows:
        source = by_id[row["paper_id"]]
        archived = source.get("removed_md5", "")
        matches = "" if not archived else str(row.get("md5", "") == archived).lower()
        if matches == "false":
            drifted.append(row["paper_id"])
        twin = source["matched_validation_paper_id"]
        log_rows.append({
            "restored_at": now, "paper_id": row["paper_id"], "twin_paper_id": twin,
            "twin_drop_reason": reasons.get(twin, ""), "matched_on": source["matched_on"],
            "folder": row.get("folder", ""), "status": row.get("status", ""),
            "md5_matches_archive": matches, "title": row.get("title", ""),
        })

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_COLUMNS)
        writer.writeheader()
        writer.writerows(log_rows)

    ok = sum(1 for r in rows if r.get("status") == "OK")
    print(f"\nrestored {ok}/{len(rows)} to the manifest -> {LOG.relative_to(ROOT)}")
    if drifted:
        print(f"!! {len(drifted)} PDF(s) differ from the archived copy "
              f"(Zotero attachment changed since removal): {', '.join(drifted)}")
    if not ARCHIVE.exists():
        print(f"note: {ARCHIVE.relative_to(ROOT)} is missing; archived copies were not checked")

    print("\nnext: 01_verify_identity.py -> 02_extract_pdfs.py -> 11_scan_text_integrity.py "
          "-> 05_build_exclusions.py -> 14_check_us_clean.py")


if __name__ == "__main__":
    main()
