"""Verify every fetched PDF is the paper Zotero says it is (research design/PLAN.md step 1).

HOW TO RUN
    python scripts/01_verify_identity.py                      # both sets, offline
    python scripts/01_verify_identity.py --set human_labelled # one set only
    python scripts/01_verify_identity.py --retry-attachments  # + repair stage (needs Zotero)
    python scripts/01_verify_identity.py --show MISMATCH      # list one verdict's papers

WHAT IT DOES
    Stage 1 (offline, always runs)
        Reads the first 2 pages of each PDF, compares them to that paper's
        Zotero metadata, and assigns VERIFIED / WEAK / MISMATCH /
        PDF_UNREADABLE. Rules and thresholds live in src/identity.py.

    Stage 2 (--retry-attachments, needs network)
        For any paper that did not come back VERIFIED *and* whose record has
        more than one PDF attached, downloads the other attachments and tests
        each. If one verifies, it replaces the current PDF and the manifest is
        corrected. This is what fixes a record where the supplement was picked
        instead of the article.

OUTPUTS
    data/zotero_manifest.csv    verdict, verdict_reason, title_score per paper
    results/identity_report.csv every signal per paper, for diagnosis
    Terminal                    verdict counts, then anything needing a human

Nothing is deleted and no paper is dropped here. MISMATCH papers stay in the
manifest with their verdict so they surface later instead of vanishing.
"""

import argparse
import csv
import io
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import identity
from pdf_extract import extract_head_text
from zotero_fetch import (
    MANIFEST_COLUMNS,
    SET_HUMAN_LABELLED,
    SET_UNLABELLED,
    STATUS_OK,
    _md5,
    connect,
    load_meta,
    select_pdf_attachment,
    set_dir,
)

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
META = ROOT / "data" / "zotero_meta.jsonl"
REPORT = ROOT / "results" / "identity_report.csv"

REPORT_COLUMNS = [
    "paper_id", "set", "folder", "verdict", "verdict_reason", "explanation",
    "title_score", "title_pos", "doi_hit", "admin_doc", "first_author_hit", "author_hits", "author_count",
    "author_frac", "year_hit", "journal_hit", "head_chars", "page_count",
    "other_dois", "attachment_key", "repaired_from", "title",
]

# Windows terminals default to cp1252 and paper titles are full of en-dashes and
# accents; without this a print() of a real title crashes the run.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def read_manifest() -> list[dict]:
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_manifest(rows: list[dict]) -> None:
    with MANIFEST.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def pdf_path_for(row: dict) -> Path:
    return set_dir(ROOT, row["set"]) / f"{row['paper_id']}.pdf"


def verify_one(pdf_path: Path, meta: dict) -> dict:
    """Extract front matter and score it. Returns the identity result plus page_count."""
    head, page_count, _method = extract_head_text(pdf_path)
    return {**identity.verify(head, meta), "page_count": page_count}


def run_verification(rows: list[dict], meta_by_id: dict) -> dict:
    """Stage 1: verify every row that has a PDF on disk. Returns {paper_id: result}."""
    results = {}
    for row in tqdm(rows, desc="Verifying"):
        paper_id = row["paper_id"]
        meta = meta_by_id.get(paper_id)
        pdf = pdf_path_for(row)

        if meta is None:
            results[paper_id] = {
                "verdict": identity.MISMATCH,
                "verdict_reason": "NO_METADATA",
                "explanation": "no row in zotero_meta.jsonl to compare against",
                "title_score": 0.0, "page_count": 0, "head_chars": 0,
            }
            continue

        if not pdf.exists():
            results[paper_id] = {
                "verdict": identity.PDF_UNREADABLE,
                "verdict_reason": identity.REASON_NO_TEXT,
                "explanation": f"no PDF on disk at {pdf.relative_to(ROOT)}",
                "title_score": 0.0, "page_count": 0, "head_chars": 0,
            }
            continue

        results[paper_id] = verify_one(pdf, meta)

    return results


def open_libraries(library_ids: list[str], api_key: str, library_type: str) -> list:
    """Zotero clients for every group the corpus spans.

    The manifest records which *collection* a paper came from but not which
    *group* -- and the corpus spans three (the study library plus NCI and
    NHLBI for the Human Labelled Set). Rather than guess, the repair stage probes each
    client until one recognizes the item key. Only failures reach this path,
    so the extra calls are few.
    """
    return [connect(lid, api_key, library_type=library_type) for lid in library_ids]


def find_children(clients: list, paper_id: str):
    """Attachments for an item, from whichever library holds it. None if absent."""
    for zot in clients:
        try:
            return zot, zot.children(paper_id)
        except Exception:
            continue
    return None, None


def retry_attachments(rows_needing: list[dict], meta_by_id: dict, clients: list) -> dict:
    """Stage 2: try a record's other PDF attachments, keep one that verifies.

    Only runs for papers that failed stage 1, and only touches disk when a
    replacement actually verifies -- a record whose alternatives are all wrong
    keeps the original file and its original verdict.
    """
    repairs = {}

    for row in tqdm(rows_needing, desc="Retrying attachments"):
        paper_id = row["paper_id"]
        meta = meta_by_id.get(paper_id)
        if meta is None:
            continue

        zot, children = find_children(clients, paper_id)
        if not children:
            continue

        pdfs = [c for c in children if c["data"].get("contentType") == "application/pdf"]
        alternatives = [p for p in pdfs if p["key"] != row.get("attachment_key")]
        if not alternatives:
            continue

        dest = pdf_path_for(row)
        # Candidates land beside the original under a temporary name, so a
        # download or parse failure can never leave the corpus holding a
        # half-written file in place of one that at least arrived intact.
        scratch = dest.with_suffix(".candidate")

        try:
            for attachment in alternatives:
                try:
                    payload = zot.file(attachment["key"])
                except Exception:
                    continue
                if not payload.startswith(b"%PDF"):
                    continue

                scratch.write_bytes(payload)
                try:
                    result = verify_one(scratch, meta)
                except Exception:
                    continue

                if result["verdict"] == identity.VERIFIED:
                    # Only now replace the original: a candidate that did not
                    # verify must not displace a file that at least arrived intact.
                    scratch.replace(dest)
                    repairs[paper_id] = {
                        **result,
                        "attachment_key": attachment["key"],
                        "md5": attachment["data"].get("md5", "") or _md5(payload),
                        "repaired_from": row.get("attachment_key", ""),
                    }
                    break
        finally:
            scratch.unlink(missing_ok=True)

    return repairs


def write_report(rows: list[dict], results: dict, repairs: dict) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            result = results.get(row["paper_id"], {})
            repair = repairs.get(row["paper_id"], {})
            other = result.get("other_dois") or []
            writer.writerow({
                **result,
                "paper_id": row["paper_id"],
                "set": row["set"],
                "folder": row["folder"],
                "title": row["title"],
                "attachment_key": repair.get("attachment_key", row.get("attachment_key", "")),
                "repaired_from": repair.get("repaired_from", ""),
                "other_dois": "; ".join(other[:3]),
            })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=[SET_UNLABELLED, SET_HUMAN_LABELLED],
                        help="Only verify one half of the corpus (default: both)")
    parser.add_argument("--retry-attachments", action="store_true",
                        help="For papers that fail, download the record's other PDF attachments and keep one that verifies. Needs Zotero access.")
    parser.add_argument("--library-id", action="append", default=None,
                        help="Zotero group ID to search during --retry-attachments. Repeatable; defaults to ZOTERO_LIBRARY_ID plus ZOTERO_EXTRA_LIBRARY_IDS in .env.")
    parser.add_argument("--show", metavar="VERDICT",
                        help="Print every paper with this verdict (VERIFIED/WEAK/MISMATCH/PDF_UNREADABLE) and exit.")
    args = parser.parse_args()

    all_rows = read_manifest()
    meta_by_id = load_meta(META)

    rows = [r for r in all_rows if r["status"] == STATUS_OK]
    if args.set:
        rows = [r for r in rows if r["set"] == args.set]
    if not rows:
        sys.exit("No fetched papers to verify. Run scripts/00_fetch_zotero.py first.")

    if args.show:
        for row in all_rows:
            if row.get("verdict") == args.show.upper():
                print(f"{row['paper_id']} [{row['set']}] {row.get('verdict_reason','')} "
                      f"score={row.get('title_score','')}\n    {row['title'][:100]}")
        return

    print(f"Verifying {len(rows)} paper(s) against Zotero metadata...\n")
    results = run_verification(rows, meta_by_id)

    repairs = {}
    if args.retry_attachments:
        needing = [r for r in rows if results[r["paper_id"]]["verdict"] != identity.VERIFIED]
        # A record with a single attachment has nothing to swap to.
        needing = [r for r in needing if r.get("warning")]
        if needing:
            load_dotenv(ROOT / ".env")
            api_key = os.getenv("ZOTERO_API_KEY")
            if not api_key:
                sys.exit("ZOTERO_API_KEY must be set in .env for --retry-attachments")
            library_ids = args.library_id or [
                lid.strip() for lid in
                [os.getenv("ZOTERO_LIBRARY_ID", "")] + os.getenv("ZOTERO_EXTRA_LIBRARY_IDS", "").split(",")
                if lid.strip()
            ]
            print(f"\n{len(needing)} unverified paper(s) have multiple PDF attachments; "
                  f"trying alternatives across {len(library_ids)} librar(ies)...")
            clients = open_libraries(library_ids, api_key, os.getenv("ZOTERO_LIBRARY_TYPE", "group"))
            repairs = retry_attachments(needing, meta_by_id, clients)
            results.update({pid: r for pid, r in repairs.items()})
            print(f"repaired {len(repairs)} paper(s) by swapping in a different attachment")
        else:
            print("\nNothing to retry: every unverified paper has only one PDF attachment.")

    # Write verdicts back to the manifest, leaving rows this run did not touch
    # (the other --set, or unfetched papers) exactly as they were.
    for row in all_rows:
        result = results.get(row["paper_id"])
        if not result:
            continue
        row["verdict"] = result["verdict"]
        row["verdict_reason"] = result["verdict_reason"]
        row["title_score"] = result.get("title_score", "")
        repair = repairs.get(row["paper_id"])
        if repair:
            row["attachment_key"] = repair["attachment_key"]
            row["md5"] = repair["md5"]
    write_manifest(all_rows)
    write_report(rows, results, repairs)

    counts = Counter(r["verdict"] for r in results.values())
    print(f"\n{'='*70}\nVERDICTS ({len(results)} papers)\n{'='*70}")
    for verdict in (identity.VERIFIED, identity.WEAK, identity.MISMATCH, identity.PDF_UNREADABLE):
        n = counts.get(verdict, 0)
        print(f"  {verdict:16} {n:5}  ({n/len(results):.1%})")

    reasons = Counter(r["verdict_reason"] for r in results.values())
    print("\nwhy:")
    for reason, n in reasons.most_common():
        print(f"  {reason:22} {n:5}")

    blocked = [(pid, r) for pid, r in results.items()
               if r["verdict"] in (identity.MISMATCH, identity.PDF_UNREADABLE)]
    if blocked:
        print(f"\n{'='*70}\nNEEDS A HUMAN ({len(blocked)})\n{'='*70}")
        titles = {r["paper_id"]: r["title"] for r in rows}
        for pid, result in sorted(blocked, key=lambda x: x[1]["verdict"]):
            print(f"  {pid} [{result['verdict']}] {result['explanation']}")
            print(f"      {titles.get(pid, '')[:95]}")

    print(f"\nmanifest -> {MANIFEST}")
    print(f"full signal report -> {REPORT}")
    if counts.get(identity.WEAK):
        print(f"\n{counts[identity.WEAK]} WEAK paper(s) enter the corpus flagged; "
              f"see them with --show WEAK")


if __name__ == "__main__":
    main()
