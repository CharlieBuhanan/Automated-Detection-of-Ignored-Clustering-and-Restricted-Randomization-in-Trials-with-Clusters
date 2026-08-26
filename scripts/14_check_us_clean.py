"""Closure checklist for the Unlabelled Set: is the corpus ready to classify?

WHY
    The HLS closes on labels; the US closes on *inputs*. There is no human answer
    to reconcile against here, so every test asks the same question a different
    way: is there exactly one readable, correct, non-duplicated document behind
    every paper we are about to spend a call on?

    A paper that fails one of these does not produce a wrong answer -- it produces
    a confident answer about the wrong document, which is worse, because nothing
    downstream can tell the difference.

    Run this before the gate run (PLAN.md step 10), and again after the DC42
    restore, since restoring papers reopens U1/U2/U5.

    Read-only. Writes nothing, changes nothing, drops nothing.

USAGE
    python scripts/14_check_us_clean.py           # checklist + detail
    python scripts/14_check_us_clean.py --quiet   # just the PASS/FAIL lines
"""

import argparse
import csv
import io
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import db  # noqa: E402
import identity  # noqa: E402
from zotero_fetch import SET_UNLABELLED, SET_HUMAN_LABELLED, set_dir  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
CACHE_DIR = ROOT / "data" / "extracted_text"
REVIEW_DIR = ROOT / "results" / "review"
EXCLUSIONS = ROOT / "results" / "01_corpus_build" / "exclusions.csv"
PDF_DIR = set_dir(ROOT, SET_UNLABELLED)

# PLAN.md step 2: the only two genuinely short documents in the corpus were both
# correction notices. Anything under this is a stub, not an article.
MIN_TEXT_CHARS = 3000

# The count PLAN.md and the methods section both cite. If this moves, one of
# them is now wrong -- which is the point of asserting it.
EXPECTED_ACTIVE_US = 1306

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class Checklist:
    """Collects PASS/FAIL lines so the whole list runs before anything exits."""

    def __init__(self, quiet: bool = False):
        self.results: list[tuple[str, str, bool, str]] = []
        self.quiet = quiet

    def check(self, tag: str, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((tag, name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {tag}  {name}")
        if detail and (not ok or not self.quiet):
            for line in detail.splitlines():
                print(f"         {line}")
        return ok

    @property
    def failed(self) -> list[tuple[str, str, bool, str]]:
        return [r for r in self.results if not r[2]]


def sample(items, n: int = 8) -> str:
    items = sorted(items)
    return f"{', '.join(items[:n])}{', ...' if len(items) > n else ''}"


def identifier_index(rows: list[dict]) -> dict[tuple[str, str], set[str]]:
    """Map every (field, normalized value) to the paper_ids carrying it."""
    index: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        for field in ("doi", "pmid", "pmcid", "md5"):
            value = (row.get(field) or "").strip().lower()
            if value:
                index[(field, value)].add(row["paper_id"])
    return index


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress the detail line under a passing check")
    args = parser.parse_args()

    manifest = read_csv(MANIFEST)
    us = [r for r in manifest if r["set"] == SET_UNLABELLED]
    active = [r for r in us if r["verdict"] != "DROPPED"]
    active_ids = {r["paper_id"] for r in active}
    manifest_ids = {r["paper_id"] for r in manifest}

    hls_active = [r for r in manifest
                  if r["set"] == SET_HUMAN_LABELLED and r["verdict"] != "DROPPED"]

    print("=" * 70)
    print(f"UNLABELLED SET CLOSURE CHECKLIST   {len(us)} rows, {len(active)} active")
    print("=" * 70)

    cl = Checklist(args.quiet)

    # -- U1 ---------------------------------------------------------------
    # No cached text means the paper cannot be classified at all; a call would
    # be spent on an empty prompt.
    missing_text, thin_text = [], []
    for paper_id in sorted(active_ids):
        path = CACHE_DIR / f"{paper_id}.json"
        if not path.exists():
            missing_text.append(paper_id)
        elif len(path.read_text(encoding="utf-8", errors="replace")) < MIN_TEXT_CHARS:
            thin_text.append(paper_id)
    cl.check("U1", "every active US paper has cached text above the stub threshold",
             not missing_text and not thin_text,
             (f"no cached text ({len(missing_text)}): {sample(missing_text)}\n"
              f"under {MIN_TEXT_CHARS} chars ({len(thin_text)}): {sample(thin_text)}"
              if missing_text or thin_text else f"{len(active_ids)} cached, none thin"))

    # -- U2 ---------------------------------------------------------------
    # Anything not VERIFIED is an open identity question, and PLAN.md step 1
    # says those are blocked before any API call.
    bad_verdict = Counter(r["verdict"] for r in active if r["verdict"] != "VERIFIED")
    cl.check("U2", "no active US paper carries an unresolved verdict",
             not bad_verdict,
             f"{dict(bad_verdict)}" if bad_verdict else f"all {len(active)} VERIFIED")

    # -- U3 ---------------------------------------------------------------
    # The review queue is append-only; a row with no decision is undone work.
    queue = [r for r in read_csv(REVIEW_DIR / "01_papers_to_review.csv")
             if r["set"] == SET_UNLABELLED]
    reviewed = {r["paper_id"] for r in read_csv(REVIEW_DIR / "04_papers_reviewed_results.csv")}
    undecided = {r["paper_id"] for r in queue} - reviewed
    cl.check("U3", "every US paper in the review queue has a recorded decision",
             not undecided,
             (f"undecided: {sample(undecided)}" if undecided
              else f"{len(queue)} queued, all decided"))

    # -- U4 ---------------------------------------------------------------
    # The integrity scan found 4 genuinely wrong documents that identity
    # verification could not catch. Three had the correct PDF swapped in and one
    # was dropped, so the flag file is a record of what was *found*, not what is
    # outstanding -- a flagged paper is only a problem if no decision followed.
    resolved = {r["paper_id"] for r in read_csv(REVIEW_DIR / "04_papers_reviewed_results.csv")
                if r.get("decision") in ("replaced", "dropped")}
    flagged = ({r["paper_id"] for r in read_csv(REVIEW_DIR / "11_text_integrity_flagged.csv")
                if r.get("set") == SET_UNLABELLED} & active_ids) - resolved
    cl.check("U4", "every text-integrity flag on an active US paper is resolved",
             not flagged,
             (f"flagged, active, and undecided: {sample(flagged)}" if flagged
              else "no unresolved flags (re-run scripts/11 to refresh)"))

    # -- U5 ---------------------------------------------------------------
    # A correction notice passes identity verification -- the PDF really is the
    # document Zotero names. It is still not a study.
    notices = {r["paper_id"] for r in active
               if identity.looks_like_correction(r.get("title") or "")}
    cl.check("U5", "no active US paper is a correction/erratum notice",
             not notices,
             (f"still active: {sample(notices)}" if notices
              else "no anchored correction title among active rows"))

    # -- U6 ---------------------------------------------------------------
    # A duplicate inside the US spends two calls on one paper and double-counts
    # it in the survivor count, which is a reported study result.
    collisions = {k: v for k, v in identifier_index(active).items() if len(v) > 1}
    cl.check("U6", "no two active US papers share a DOI, PMID, PMCID, or PDF md5",
             not collisions,
             ("\n".join(f"{f}={v}: {sorted(ids)}" for (f, v), ids in list(collisions.items())[:8])
              if collisions else f"{len(active)} rows, no identifier collides"))

    # -- U7 ---------------------------------------------------------------
    # DC2: a paper sitting in both sets gets classified blind in the corpus
    # while a human answer for it already exists.
    hls_index = identifier_index(hls_active)
    overlap = {}
    for row in active:
        hit = next((k for k in identifier_index([row]) if k in hls_index), None)
        if hit:
            overlap[row["paper_id"]] = hit
    cl.check("U7", "no active US paper is also active in the HLS",
             not overlap,
             ("\n".join(f"{p}: matches HLS on {f}={v}" for p, (f, v) in list(overlap.items())[:8])
              if overlap else f"checked {len(active)} US against {len(hls_active)} HLS rows"))

    # -- U8 ---------------------------------------------------------------
    # Cross-set duplicates were removed from the manifest, not marked DROPPED.
    # One that came back *unrecorded* means a re-fetch undid the removal
    # (PLAN.md's warning); one restored under DC42 came back on purpose.
    removed = read_csv(REVIEW_DIR / "02_removed_us_duplicates.csv")
    restored = {r["paper_id"] for r in read_csv(REVIEW_DIR / "15_dc42_restored.csv")}
    resurrected = ({r["removed_paper_id"] for r in removed} & manifest_ids) - restored
    cl.check("U8", "no removed cross-set duplicate has reappeared unrecorded",
             not resurrected,
             (f"back in the manifest with no restore record: {sample(resurrected)}"
              if resurrected
              else f"{len(removed) - len(restored)} still removed, {len(restored)} restored (DC42)"))

    # -- U9 ---------------------------------------------------------------
    # DC42. This is the check that is *supposed* to fail until the restore
    # sweep runs -- it is the actionable one, not a hygiene assertion.
    conn = sqlite3.connect(f"file:{db.DEFAULT_PATH}?mode=ro", uri=True)
    labelled = {r[0] for r in conn.execute("SELECT paper_id FROM validation_labels")}
    conn.close()
    # A paper already back in the manifest has been restored; only one still
    # absent is an outstanding candidate.
    orphaned = [r for r in removed
                if r["matched_validation_paper_id"] not in labelled
                and r["removed_paper_id"] not in manifest_ids]
    cl.check("U9", "no US paper is still removed for a twin that lost its label (DC42)",
             not orphaned,
             (f"{len(orphaned)} restore candidate(s): "
              f"{sample(r['removed_paper_id'] for r in orphaned)}\n"
              f"run scripts/15_restore_dc42_duplicates.py, then re-run this checklist"
              if orphaned
              else f"{len(restored)} restored; the other {len(removed) - len(restored)} "
                   f"removals still justified"))

    # -- U10 --------------------------------------------------------------
    # The ledger is what the methods section cites. Disagreement with the
    # manifest means one of the two is lying about the corpus size.
    ledger = read_csv(EXCLUSIONS)
    ledger_us = {r["paper_id"] for r in ledger if r["set"] == SET_UNLABELLED}
    both = ledger_us & active_ids
    cl.check("U10", "no US paper is both in the exclusion ledger and active",
             not both,
             (f"in the ledger yet active: {sample(both)}" if both
              else f"{len(ledger_us)} US exclusions, none active"))

    # -- U11 --------------------------------------------------------------
    # A PDF with no manifest row is opaque (files are named by item key); a
    # manifest row with no PDF cannot be re-extracted if the cache is cleared.
    on_disk = {p.stem for p in PDF_DIR.glob("*.pdf")} if PDF_DIR.exists() else set()
    orphan_pdfs = on_disk - {r["paper_id"] for r in us}
    missing_pdfs = active_ids - on_disk
    cl.check("U11", "every active US paper has a PDF, and no PDF is orphaned",
             not orphan_pdfs and not missing_pdfs,
             (f"PDF with no manifest row ({len(orphan_pdfs)}): {sample(orphan_pdfs)}\n"
              f"active row with no PDF ({len(missing_pdfs)}): {sample(missing_pdfs)}"
              if orphan_pdfs or missing_pdfs else f"{len(on_disk)} PDFs, all accounted for"))

    # -- U12 --------------------------------------------------------------
    # Assert the published number rather than trusting it. A silent drift here
    # is a methods-section error nobody catches until review.
    cl.check("U12", f"the active US count is the documented {EXPECTED_ACTIVE_US}",
             len(active) == EXPECTED_ACTIVE_US,
             (f"manifest says {len(active)}; PLAN.md and the methods section say "
              f"{EXPECTED_ACTIVE_US}. Update both, or find the missing papers."
              if len(active) != EXPECTED_ACTIVE_US else f"{len(active)} active"))

    # -- verdict ----------------------------------------------------------
    print()
    if cl.failed:
        print(f"{len(cl.failed)} of {len(cl.results)} checks FAILED -- the US is not "
              "ready for the gate run.")
        for tag, name, _, _ in cl.failed:
            print(f"  {tag}  {name}")
    else:
        print(f"All {len(cl.results)} checks passed. The US is ready for the gate run "
              "(PLAN.md step 10).")

    return 1 if cl.failed else 0


if __name__ == "__main__":
    sys.exit(main())
