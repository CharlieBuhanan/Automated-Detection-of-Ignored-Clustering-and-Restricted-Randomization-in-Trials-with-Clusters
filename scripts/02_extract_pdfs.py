"""Extract the full text of every verified paper (research design/PLAN.md step 2).

HOW TO RUN
    python scripts/02_extract_pdfs.py                    # both sets
    python scripts/02_extract_pdfs.py --set human_labelled  # one set only
    python scripts/02_extract_pdfs.py --overwrite        # re-parse everything

WHAT IT DOES
    Reads data/zotero_manifest.csv, takes every row whose verdict is VERIFIED
    or WEAK, and caches that PDF's full text to
    data/extracted_text/<paper_id>.json.

    WEAK is included because a WEAK paper enters the corpus flagged and has its
    identity re-checked at classification time (research design/PLAN.md step 1). Extracting
    only VERIFIED would drop it from the study with no error and no trace.

    This is the second of two extraction stages. Step 1 read the first 2 pages
    of every fetched PDF to decide whether it is the paper Zotero claims; this
    step reads the whole document, and only for papers that passed. Driving it
    off the manifest rather than off a directory listing is what enforces that:
    a MISMATCH or DROPPED paper is still sitting in data/raw_pdfs/, and a glob
    would happily extract it.

    VERIFIED covers papers resolved by hand in step 3 too -- the review GUI
    writes their verdict back as VERIFIED (MANUAL_OK / MANUAL_REPLACED), so
    they are picked up here with no special case.

    Each PDF is parsed once, ever. A re-run reads the cache and re-parses
    nothing -- unless the PDF itself changed, which the cache detects by
    storing the md5 of the file it read. That is what makes the review loop
    work:

        02 flags a paper whose text came out too thin
          -> the paper is appended to results/review/01_papers_to_review.csv
          -> 03 opens the PDF, you Replace or Drop it
          -> 03 clears that paper's cached text
          -> 02 again, and only that paper is re-extracted

    Without the md5 check the last step would silently return text extracted
    from the file you just replaced.

OUTPUTS
    data/extracted_text/<paper_id>.json   full text + method/page/char counts
    results/01_corpus_build/extraction_report.csv  one row per paper, for diagnosis
    results/review/01_papers_to_review.csv  thin extractions, appended
    Terminal                              method counts, then anything thin

Text only. Tables linearize into label/value runs, which is what the
downstream classification prompt wants; figures survive only as whatever text
was drawn into them. See the plan file for the measurements behind that.
"""

import argparse
import csv
import io
import sys
from collections import Counter
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from identity import looks_like_correction
from pdf_extract import extract_and_cache
from zotero_fetch import SET_HUMAN_LABELLED, SET_UNLABELLED, set_dir

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
CACHE_DIR = ROOT / "data" / "extracted_text"
REPORT = ROOT / "results" / "01_corpus_build" / "extraction_report.csv"
REVIEW_LIST = ROOT / "results" / "review" / "01_papers_to_review.csv"

# Verdicts that enter the corpus. WEAK is included on purpose: research design/PLAN.md step 1
# says a WEAK paper enters flagged and has its identity re-checked at
# classification time, so skipping it here would drop it from the study
# silently -- no error, no review queue entry, just a paper that quietly stops
# existing. Everything else (MISMATCH, DROPPED, PDF_UNREADABLE) stays out.
EXTRACTABLE_VERDICTS = ("VERIFIED", "WEAK")

# Columns of the hand-review queue that scripts/03_review_mismatches.py reads.
# Extraction adds rows to the same queue identity verification fills, so a
# paper needing a human gets there by one route regardless of which stage
# noticed -- and one GUI resolves both.
REVIEW_COLUMNS = [
    "priority", "category", "paper_id", "set", "finding", "recommended_action",
    "verdict", "verdict_reason", "title_score", "doi", "pmid", "folder",
    "attachment_key", "title",
]

# 1 = the PDF is probably the wrong document, 3 = probably fine, so a paper
# that is plainly readable but does not belong in the study sits between them.
REVIEW_PRIORITY = "2"

# What to do about each kind of flag, shown in the review GUI.
RECOMMENDED_ACTION = {
    "CORRECTION_NOTICE": "Almost certainly Drop: a correction/erratum is not a study. "
                         "Open the PDF to confirm it is the notice and not the full article",
    "THIN_TEXT": "Open the PDF. If it is only a corrigendum/erratum/correction notice, "
                 "Drop it; if the full article exists in Zotero, Replace the PDF",
    "EXTRACTION_FAILED": "Open the PDF. If it will not render, Replace it from Zotero; "
                         "if no readable copy exists, Drop it",
}

REPORT_COLUMNS = [
    "paper_id", "set", "folder", "method", "page_count", "char_count",
    "chars_per_page", "flagged", "flag_reason", "errors", "title",
]

# A paper this thin is either a one-page abstract, a corrigendum, or a failed
# extraction -- all three want a human glance. Set from a read-only scan of the
# whole corpus, where the median paper holds 51,713 characters and exactly two
# fall below this line.
MIN_CHARS = 3000

# Windows terminals default to cp1252 and paper titles are full of en-dashes and
# accents; without this a print() of a real title crashes the run.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def read_manifest() -> list[dict]:
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def pdf_path_for(row: dict) -> Path:
    return set_dir(ROOT, row["set"]) / f"{row['paper_id']}.pdf"


def cache_path_for(paper_id: str) -> Path:
    return CACHE_DIR / f"{paper_id}.json"


def flag_for(record: dict, title: str) -> tuple[str, str]:
    """(category, reason) for a paper needing a human, or ("", "") if it is fine.

    The title check is not about extraction quality -- a correction notice
    extracts perfectly. It is here because this is the stage that owns the
    review queue, and because it catches what size alone cannot: AT7F9XWR is a
    correction notice running 5,513 characters, comfortably past any thinness
    threshold that does not also flag real short reports.
    """
    if record["method"] == "none":
        return "EXTRACTION_FAILED", "every extractor failed"
    if looks_like_correction(title):
        return "CORRECTION_NOTICE", "title announces a correction/erratum/retraction, not a study"
    if record["method"] == "ocr":
        return "THIN_TEXT", "no text layer; OCR used"
    if record["char_count"] < MIN_CHARS:
        return "THIN_TEXT", f"only {record['char_count']} characters"
    return "", ""


def extract_all(rows: list[dict], overwrite: bool) -> tuple[list[dict], list[dict]]:
    """Extract every row's PDF. Returns (report_rows, missing_rows)."""
    report_rows, missing = [], []

    for row in tqdm(rows, desc="Extracting"):
        pdf = pdf_path_for(row)
        if not pdf.exists():
            # A manifest row whose file is gone is a data problem to surface,
            # not an exception to die on partway through a 1,856-paper run.
            missing.append(row)
            continue

        # Whether the cache was actually reused, which is not the same as
        # whether a cache file existed: a stale entry exists and is still
        # re-parsed. Comparing the file's mtime across the call is the only
        # cheap way to ask extract_and_cache what it decided.
        cache_path = cache_path_for(row["paper_id"])
        before = cache_path.stat().st_mtime if cache_path.exists() else None
        record = extract_and_cache(pdf, CACHE_DIR, overwrite=overwrite)
        was_cached = before is not None and cache_path.stat().st_mtime == before
        pages = record.get("page_count") or 0

        category, reason = flag_for(record, row["title"])
        report_rows.append({
            "paper_id": row["paper_id"],
            "set": row["set"],
            "folder": row["folder"],
            "method": record["method"],
            "page_count": pages,
            "char_count": record["char_count"],
            "chars_per_page": round(record["char_count"] / pages) if pages else 0,
            "flagged": category,
            "flag_reason": reason,
            # Older cache entries predate this field; treat them as clean.
            "errors": "; ".join(record.get("errors") or []),
            "title": row["title"],
            "_cached": was_cached,
        })

    return report_rows, missing


def queue_for_review(flagged: list[dict], manifest_by_id: dict) -> list[dict]:
    """Add flagged papers to the hand-review queue. Returns the rows added.

    Appends rather than rewrites, and skips any paper already queued, so a
    paper that identity verification put there keeps its original finding and
    a paper already decided is not resurrected on every run.

    This is what closes the loop: a thin extraction is a question about the
    PDF ("is this the whole article, or just a correction notice?"), and the
    only tool that answers it is the review GUI. Leaving the flag in a report
    nobody opens meant hand-editing a CSV to act on it.
    """
    existing = {r["paper_id"] for r in read_csv(REVIEW_LIST)}
    additions = []

    for row in flagged:
        if row["paper_id"] in existing:
            continue
        manifest = manifest_by_id.get(row["paper_id"], {})
        additions.append({
            "priority": REVIEW_PRIORITY,
            "category": row["flagged"],
            "paper_id": row["paper_id"],
            "set": row["set"],
            "finding": f"{row['flag_reason']} "
                       f"({row['char_count']} chars over {row['page_count']} page(s); "
                       f"the corpus median is ~51,700)",
            "recommended_action": RECOMMENDED_ACTION.get(
                row["flagged"], "Open the PDF and decide"),
            "verdict": manifest.get("verdict", ""),
            "verdict_reason": manifest.get("verdict_reason", ""),
            "title_score": manifest.get("title_score", ""),
            "doi": manifest.get("doi", ""),
            "pmid": manifest.get("pmid", ""),
            "folder": manifest.get("folder", ""),
            "attachment_key": manifest.get("attachment_key", ""),
            "title": row["title"],
        })

    if not additions:
        return []

    REVIEW_LIST.parent.mkdir(parents=True, exist_ok=True)
    fresh = not REVIEW_LIST.exists() or REVIEW_LIST.stat().st_size == 0
    with REVIEW_LIST.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS, extrasaction="ignore")
        if fresh:
            writer.writeheader()
        writer.writerows(additions)
    return additions


def read_csv(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_report(report_rows: list[dict]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report_rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=[SET_UNLABELLED, SET_HUMAN_LABELLED],
                        help="Only extract one half of the corpus (default: both)")
    parser.add_argument("--overwrite", action="store_true",
                        help="Re-parse even papers already in the cache (e.g. after changing extraction logic)")
    args = parser.parse_args()

    manifest = read_manifest()
    rows = [r for r in manifest if r.get("verdict") in EXTRACTABLE_VERDICTS]
    if args.set:
        rows = [r for r in rows if r["set"] == args.set]
    if not rows:
        sys.exit("No VERIFIED or WEAK papers to extract. "
                 "Run scripts/01_verify_identity.py first.")

    # A verdict this script has never heard of means step 1 grew a new outcome
    # and nobody told step 2. Say so rather than silently extracting fewer
    # papers than the corpus contains.
    known = set(EXTRACTABLE_VERDICTS) | {"MISMATCH", "DROPPED", "PDF_UNREADABLE", "PDF_MISSING", ""}
    unknown = sorted({r.get("verdict", "") for r in manifest} - known)
    if unknown:
        sys.exit(f"Unknown verdict(s) in the manifest: {', '.join(unknown)}. "
                 f"Decide whether they should be extracted before running this.")

    weak = sum(1 for r in rows if r.get("verdict") == "WEAK")
    scope = args.set or "both sets"
    print(f"Extracting {len(rows)} paper(s) ({scope})"
          f"{f', {weak} of them WEAK' if weak else ''}"
          f"{' -- re-parsing all of them' if args.overwrite else ''}...\n")

    report_rows, missing = extract_all(rows, args.overwrite)
    write_report(report_rows)

    reused = sum(1 for r in report_rows if r["_cached"])
    methods = Counter(r["method"] for r in report_rows)
    total_chars = sum(r["char_count"] for r in report_rows)

    print(f"\n{'='*70}\nEXTRACTED ({len(report_rows)} papers)\n{'='*70}")
    for method, n in methods.most_common():
        print(f"  {method:12} {n:5}  ({n/len(report_rows):.1%})")
    print(f"\n  {reused} already cached, {len(report_rows) - reused} newly parsed")
    print(f"  {total_chars:,} characters total, "
          f"~{total_chars // max(len(report_rows), 1):,} per paper")

    if missing:
        print(f"\n{'='*70}\nNO PDF ON DISK ({len(missing)})\n{'='*70}")
        for row in missing:
            print(f"  {row['paper_id']} [{row['set']}] {row['title'][:80]}")
        print("  These are VERIFIED in the manifest but their file is gone -- "
              "re-fetch them or correct the manifest.")

    flagged = [r for r in report_rows if r["flagged"]]
    if flagged:
        print(f"\n{'='*70}\nWORTH A LOOK ({len(flagged)})\n{'='*70}")
        for r in sorted(flagged, key=lambda r: r["char_count"]):
            print(f"  {r['paper_id']} [{r['set']}] {r['flag_reason']}")
            print(f"      {r['title'][:95]}")

        added = queue_for_review(flagged, {r["paper_id"]: r for r in read_manifest()})
        if added:
            print(f"\n  {len(added)} added to the review queue "
                  f"({len(flagged) - len(added)} already there).")
            print(f"  Triage them with:  python scripts/03_review_mismatches.py")
            print(f"  Replacing a PDF there clears its cached text; re-run this "
                  f"script afterwards to extract the new file.")
        else:
            print(f"\n  All {len(flagged)} are already in the review queue.")

    print(f"\ncached text -> {CACHE_DIR}")
    print(f"report      -> {REPORT}")
    print(f"queue       -> {REVIEW_LIST}")


if __name__ == "__main__":
    main()
