"""Check every cached extraction for signs of a bad PDF parse (PLAN.md step 2b).

Offline and deterministic -- no API calls, no re-parsing. Reads
data/extracted_text/*.json and flags anything that looks like the extractor
produced text that is not the paper.

THE CHECKS, in the order a flag is reported. A paper can carry several.

    F1  MOJIBAKE       U+FFFD replacement chars, or the tell-tale UTF-8-read-as-
                       cp1252 sequences (Ã¢â‚¬, Ã©, â€œ). Encoding went wrong.
    F2  MULTI_ARTICLE  a second "Abstract" heading appearing AFTER the first
                       reference list -- i.e. article 1 ends and another begins.
                       Two papers bound into one PDF. Counting Abstract or
                       References twice is NOT enough: journals print "Abstract
                       (continued)" on page 2, use "abstract" as a verb ("to
                       abstract data"), and append supplementary reference
                       blocks. All three were false positives on this corpus.
    F3  NO_REFERENCES  no reference-list marker anywhere: no "References" or
                       "Bibliography" heading AND no "doi: 10." string. Every
                       real journal article has a reference list, so its total
                       absence means the extraction stopped early. Tested
                       against weaker rules first: "ends without a full stop"
                       flagged 257 papers, nearly all of which simply end on a
                       Wiley licence footer or a page number.
    F4  THIN_PER_PAGE  characters-per-page below 40% of the corpus median. A
                       page with almost no text is an image the extractor could
                       not read.
    F5  SHORT_VS_ABSTRACT  full text is shorter than 3x the Zotero abstract.
                       The "full text" is really a landing page or first page.
    F6  LOW_ALPHA      fewer than 60% of non-space chars are letters. Ligature
                       or font-encoding failure turns prose into symbol soup.
    F7  REPETITIVE     more than 30% of lines are exact duplicates. Running
                       headers/footers swamping the body.

OUTPUTS
    results/01_corpus_build/text_integrity_report.csv   one row per paper
    Terminal                                            counts per flag
"""

import argparse
import collections
import csv
import io
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from zotero_fetch import load_meta

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "extracted_text"
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
META = ROOT / "data" / "zotero_meta.jsonl"
REPORT = ROOT / "results" / "01_corpus_build" / "text_integrity_report.csv"

MOJIBAKE = re.compile(r"�|Ã¢â‚¬|Ã©|Ã¨|â€œ|â€\x9d|Ã\xad")
ABSTRACT_H = re.compile(r"^\s*abstract\b", re.I | re.M)
REFERENCES_H = re.compile(r"^\s*(references|bibliography|literature cited)\b", re.I | re.M)
SENTENCE_END = re.compile(r"[.!?)\"'\]0-9]\s*$")
REF_ANY = re.compile(r"\breferences\b|\bbibliography\b|doi:\s*10\.", re.I)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def active_papers() -> dict:
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        return {r["paper_id"]: r for r in csv.DictReader(handle) if r["verdict"] != "DROPPED"}


def scan(text: str, pages: int, abstract: str, median_cpp: float) -> list[str]:
    flags = []
    body = text.strip()
    nonspace = [c for c in body if not c.isspace()]

    if MOJIBAKE.search(body):
        flags.append("F1_MOJIBAKE")
    first_refs = REFERENCES_H.search(body)
    if first_refs and ABSTRACT_H.search(body, first_refs.end()):
        flags.append("F2_MULTI_ARTICLE")
    if body and not REF_ANY.search(body):
        flags.append("F3_NO_REFERENCES")
    if pages and median_cpp and (len(body) / pages) < 0.40 * median_cpp:
        flags.append("F4_THIN_PER_PAGE")
    if abstract and len(body) < 3 * len(abstract):
        flags.append("F5_SHORT_VS_ABSTRACT")
    if nonspace and sum(c.isalpha() for c in nonspace) / len(nonspace) < 0.60:
        flags.append("F6_LOW_ALPHA")
    lines = [l.strip() for l in body.splitlines() if len(l.strip()) > 15]
    if len(lines) > 50:
        dupes = len(lines) - len(set(lines))
        if dupes / len(lines) > 0.30:
            flags.append("F7_REPETITIVE")
    return flags


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", help="Print the flag counts for one flag's papers")
    args = parser.parse_args()

    manifest = active_papers()
    meta = load_meta(META)

    records = []
    for paper_id, row in manifest.items():
        cache = CACHE_DIR / f"{paper_id}.json"
        if not cache.exists():
            continue
        blob = json.loads(cache.read_text(encoding="utf-8"))
        text = blob.get("text", "")
        records.append({
            "paper_id": paper_id, "text": text,
            "pages": int(blob.get("page_count") or 0),
            "chars": len(text),
            "abstract": (meta.get(paper_id, {}) or {}).get("abstract", "") or "",
            "title": row.get("title", ""), "set": row.get("set", ""),
        })

    per_page = [r["chars"] / r["pages"] for r in records if r["pages"]]
    median_cpp = statistics.median(per_page) if per_page else 0
    print(f"{len(records)} cached extractions | median {median_cpp:,.0f} chars/page")

    rows, counter = [], collections.Counter()
    for r in records:
        flags = scan(r["text"], r["pages"], r["abstract"], median_cpp)
        for f in flags:
            counter[f] += 1
        rows.append({
            "paper_id": r["paper_id"], "set": r["set"], "flags": ";".join(flags),
            "n_flags": len(flags), "chars": r["chars"], "pages": r["pages"],
            "chars_per_page": round(r["chars"] / r["pages"]) if r["pages"] else 0,
            "abstract_chars": len(r["abstract"]), "title": r["title"][:90],
        })

    rows.sort(key=lambda x: (-x["n_flags"], x["paper_id"]))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    flagged = [r for r in rows if r["n_flags"]]
    print(f"\n{'='*70}\nFLAGGED: {len(flagged)} of {len(rows)} papers\n{'='*70}")
    for flag in ["F1_MOJIBAKE", "F2_MULTI_ARTICLE", "F3_NO_REFERENCES", "F4_THIN_PER_PAGE",
                 "F5_SHORT_VS_ABSTRACT", "F6_LOW_ALPHA", "F7_REPETITIVE"]:
        print(f"  {flag:22} {counter.get(flag, 0):>5}")

    if flagged:
        print(f"\n  papers carrying any flag:")
        for r in flagged[:40]:
            print(f"    {r['paper_id']}  {r['flags']:46} {r['chars_per_page']:>6} c/pg  {r['title'][:44]}")
    print(f"\nreport -> {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
