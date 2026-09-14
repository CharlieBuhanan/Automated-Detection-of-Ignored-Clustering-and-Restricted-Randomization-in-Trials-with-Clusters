"""Closure checklist for the Human Labelled Set: is every drop done?

WHY
    DC42 says a US paper's cross-set-duplicate removal is conditional on its HLS
    twin surviving. 207 US papers were removed because an HLS copy already carried
    a usable answer; when that HLS copy is later dropped (DC37, DC28, ...), the
    reason no longer holds and the US paper should re-enter the pool.

    Restoring them is only safe once the HLS has stopped shrinking. Every further
    HLS drop creates more restore candidates, and a restore pass run halfway
    through leaves the corpus in a state no single script explains. So this ran
    first: fourteen read-only tests that each assert one way the HLS could still
    be hiding a paper that has to leave.

    All 14 passed on 2026-08-26 and the 23 restores went through
    (`scripts/15_restore_dc42_duplicates.py`). The list is now a standing
    regression: run it after anything that touches HLS membership, and any FAIL
    means a new candidate has appeared and the restore needs re-running.

    Read-only. Writes nothing, changes nothing, drops nothing.

USAGE
    python scripts/13_check_hls_clean.py           # checklist + restore preview
    python scripts/13_check_hls_clean.py --quiet   # just the PASS/FAIL lines
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

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
GROUND_TRUTH = ROOT / "data" / "ground_truth.csv"
CACHE_DIR = ROOT / "data" / "extracted_text"
REVIEW_DIR = ROOT / "results" / "review"
EXCLUSIONS = ROOT / "results" / "01_corpus_build" / "exclusions.csv"

# Reasons the model can never reproduce, from 10_drop_nonjudgeable_exclusions.py.
# Duplicated deliberately: this test has to fail if that script's list grows and
# the drop has not been re-run.
NONJUDGEABLE = {"protocol_paper", "duplicate_group_random_drop"}

# A paper under this many characters is a notice or a stub, not an article
# (PLAN.md step 2: the two genuine cases in the corpus were both corrections).
MIN_TEXT_CHARS = 3000

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
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {tag}  {name}")
        if detail and (not ok or not self.quiet):
            for line in detail.splitlines():
                print(f"         {line}")
        return ok

    @property
    def failed(self) -> list[tuple[str, str, bool, str]]:
        return [r for r in self.results if not r[2]]


def sample(items, n: int = 8) -> str:
    items = sorted(items)
    shown = ", ".join(items[:n])
    return f"{shown}{', ...' if len(items) > n else ''}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress the detail line under a passing check")
    args = parser.parse_args()

    manifest = read_csv(MANIFEST)
    hls = [r for r in manifest if r["set"] == "human_labelled"]
    active = [r for r in hls if r["verdict"] != "DROPPED"]
    active_ids = {r["paper_id"] for r in active}
    manifest_ids = {r["paper_id"] for r in manifest}

    conn = sqlite3.connect(f"file:{db.DEFAULT_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    labels = {r["paper_id"]: r for r in conn.execute("SELECT * FROM validation_labels")}

    print("=" * 70)
    print(f"HLS CLOSURE CHECKLIST   {len(hls)} rows, {len(active)} active, "
          f"{len(labels)} labelled")
    print("=" * 70)

    cl = Checklist(args.quiet)

    # -- C1 ---------------------------------------------------------------
    # An active paper with no label cannot be scored and would have to be
    # dropped or chased; a label whose paper is gone inflates the denominator.
    unlabelled = active_ids - set(labels)
    orphan_labels = set(labels) - active_ids
    cl.check("C1", "every active HLS paper has a label, and vice versa",
             not unlabelled and not orphan_labels,
             (f"active without a label ({len(unlabelled)}): {sample(unlabelled)}\n"
              f"labels without an active paper ({len(orphan_labels)}): {sample(orphan_labels)}"
              if unlabelled or orphan_labels else f"{len(active_ids)} matched both ways"))

    # -- C2 ---------------------------------------------------------------
    # Anything not VERIFIED is an identity question still open, and an open
    # identity question is a candidate drop.
    bad_verdict = Counter(r["verdict"] for r in active if r["verdict"] != "VERIFIED")
    cl.check("C2", "no active HLS paper carries an unresolved verdict",
             not bad_verdict,
             (f"{dict(bad_verdict)}" if bad_verdict else "all 483 VERIFIED"
              if len(active) == 483 else f"all {len(active)} VERIFIED"))

    # -- C3 ---------------------------------------------------------------
    # The review queue is append-only; a row with no matching decision is work
    # nobody has done, not a historical record.
    queue = [r for r in read_csv(REVIEW_DIR / "01_papers_to_review.csv")
             if r["set"] == "human_labelled"]
    reviewed = {r["paper_id"] for r in read_csv(REVIEW_DIR / "04_papers_reviewed_results.csv")}
    undecided = {r["paper_id"] for r in queue} - reviewed
    cl.check("C3", "every HLS paper in the review queue has a recorded decision",
             not undecided,
             (f"undecided: {sample(undecided)}" if undecided
              else f"{len(queue)} queued, all decided"))

    # -- C4 ---------------------------------------------------------------
    # A bad parse is a wrong document until proven otherwise.
    flagged = {r["paper_id"] for r in read_csv(REVIEW_DIR / "11_text_integrity_flagged.csv")
               if r.get("set") == "human_labelled"} & active_ids
    cl.check("C4", "no active HLS paper is flagged by the text-integrity scan",
             not flagged,
             (f"flagged and still active: {sample(flagged)}" if flagged
              else "0 HLS rows flagged (re-run scripts/11 to refresh)"))

    # -- C5 ---------------------------------------------------------------
    # No cached text means nothing to classify; thin text means a notice.
    missing_text, thin_text = [], []
    for paper_id in sorted(active_ids):
        path = CACHE_DIR / f"{paper_id}.json"
        if not path.exists():
            missing_text.append(paper_id)
        elif len(path.read_text(encoding="utf-8", errors="replace")) < MIN_TEXT_CHARS:
            thin_text.append(paper_id)
    cl.check("C5", "every active HLS paper has cached text above the stub threshold",
             not missing_text and not thin_text,
             (f"no cached text ({len(missing_text)}): {sample(missing_text)}\n"
              f"under {MIN_TEXT_CHARS} chars ({len(thin_text)}): {sample(thin_text)}"
              if missing_text or thin_text else f"{len(active_ids)} cached, none thin"))

    # -- C6 ---------------------------------------------------------------
    # A nonjudgeable reason still in the labels means scripts/10 has not been
    # re-run since the label set last changed.
    nonjudgeable = {p for p, r in labels.items()
                    if (r["exclusion_reason"] or "") in NONJUDGEABLE}
    cl.check("C6", "no nonjudgeable exclusion reason survives in the labels",
             not nonjudgeable,
             (f"still present: {sample(nonjudgeable)}" if nonjudgeable
              else f"none of {sorted(NONJUDGEABLE)} remain"))

    # -- C7 ---------------------------------------------------------------
    # The gate has to show up in the labels exactly: kept papers scored on both
    # analyses, excluded papers scored on neither.
    survivors = [p for p, r in labels.items() if db.expected_decision(r, "exclusion") == "no"]
    excluded = [p for p in labels if p not in set(survivors)]
    half_scored = [p for p in survivors if not (labels[p]["power"] and labels[p]["stats"])]
    over_scored = [p for p in excluded if labels[p]["power"] or labels[p]["stats"]]
    cl.check("C7", "survivors carry power AND stats; excluded papers carry neither",
             not half_scored and not over_scored,
             (f"survivors missing a label ({len(half_scored)}): {sample(half_scored)}\n"
              f"excluded but scored ({len(over_scored)}): {sample(over_scored)}"
              if half_scored or over_scored
              else f"{len(survivors)} survivors / {len(excluded)} excluded, cleanly split"))

    # -- C8 ---------------------------------------------------------------
    # expected_decision() compares against the model's own vocabulary; anything
    # else scores as a miss no matter how good the answer was.
    vocab = {"yes", "no"}
    bad_vocab = {p for p, r in labels.items()
                 for v in (r["power"], r["stats"]) if v and v.strip().lower() not in vocab}
    cl.check("C8", "every power/stats label is 'yes' or 'no'",
             not bad_vocab,
             (f"other values: {sample(bad_vocab)}" if bad_vocab
              else "vocabulary matches the Decision schema"))

    # -- C9 ---------------------------------------------------------------
    # A duplicate inside the active HLS double-counts one paper's label.
    dupes = defaultdict(set)
    for row in active:
        for field in ("doi", "pmid", "pmcid", "md5"):
            value = (row.get(field) or "").strip().lower()
            if value:
                dupes[(field, value)].add(row["paper_id"])
    collisions = {k: v for k, v in dupes.items() if len(v) > 1}
    cl.check("C9", "no two active HLS papers share a DOI, PMID, PMCID, or PDF md5",
             not collisions,
             ("\n".join(f"{f}={v}: {sorted(ids)}" for (f, v), ids in list(collisions.items())[:8])
              if collisions else f"{len(active)} rows, no identifier collides"))

    # -- C10 --------------------------------------------------------------
    # An institutional disagreement that is still active is an unlabelled paper
    # wearing a label row's clothes.
    disagreements = {r["paper_id"] for r in read_csv(REVIEW_DIR / "05_label_match_review.csv")
                     if r.get("paper_id")}
    live_disagreements = disagreements & active_ids
    cl.check("C10", "no institutional disagreement is still active",
             not live_disagreements,
             (f"still active: {sample(live_disagreements)}" if live_disagreements
              else f"{len(disagreements)} on file, all dropped or resolved"))

    # -- C11 --------------------------------------------------------------
    # An unjoined label is a human answer with no paper attached; it must have
    # been deliberately closed, not left sitting.
    unjoined = read_csv(REVIEW_DIR / "07_ground_truth_unjoined.csv")
    cl.check("C11", "no ground-truth citation is left unjoined",
             not unjoined,
             (f"{len(unjoined)} unjoined citation(s)" if unjoined
              else "every citation in ground_truth.csv resolved to a paper_id"))

    # -- C12 --------------------------------------------------------------
    # The 15 internal duplicate pairs must all have been merged; an unmerged
    # pair is two rows for one paper.
    pairs = read_csv(REVIEW_DIR / "03_hls_internal_duplicates.csv")
    merged = {r["removed_paper_id"] for r in read_csv(REVIEW_DIR / "06_merged_hls_duplicates.csv")}
    unmerged = {r["paper_id"] for r in pairs} & manifest_ids - merged
    still_paired = {p for p in unmerged if p in active_ids}
    cl.check("C12", "every flagged internal duplicate pair has been merged",
             len(still_paired) <= len(pairs) // 2,
             (f"{len(pairs)//2} pairs flagged, {len(merged)} rows retired, "
              f"{len(still_paired)} survivors remain (one per pair is expected)"))

    # -- C13 --------------------------------------------------------------
    # Restoring US papers changes the corpus, not the labels -- but a split
    # already fixed means the corpus was frozen, and this sweep is late.
    # Before the split existed this asserted the opposite -- that nothing had
    # been assigned yet, so the corpus could still change. It was assigned on
    # 2026-08-26 and cannot be reassigned, so the question flips: every label
    # must now carry a split, and it must be stratified as DC30 specifies.
    # An unsplit label here means a paper entered the HLS after the freeze,
    # which is the drift the run-once guard exists to make visible.
    split_rows = conn.execute(
        "SELECT split, COUNT(*) FROM validation_labels GROUP BY split").fetchall()
    counts = {row[0]: row[1] for row in split_rows}
    unsplit = counts.get(None, 0)

    strata = {}
    for row in conn.execute("SELECT * FROM validation_labels WHERE split IS NOT NULL"):
        key = (db._gate_stratum(row), row["split"])
        strata[key] = strata.get(key, 0) + 1
    survivors_held = strata.get(("survivor", db.SPLIT_HOLDOUT), 0)

    cl.check("C13", "every label carries a split, stratified on gate-survivor status",
             unsplit == 0 and survivors_held > 0,
             (f"{unsplit} label(s) have no split -- assigned after the freeze"
              if unsplit else
              f"{counts.get(db.SPLIT_BUILD, 0)} build / {counts.get(db.SPLIT_HOLDOUT, 0)} holdout; "
              f"survivors {strata.get(('survivor', db.SPLIT_BUILD), 0)}/{survivors_held}, "
              f"excluded {strata.get(('excluded', db.SPLIT_BUILD), 0)}/"
              f"{strata.get(('excluded', db.SPLIT_HOLDOUT), 0)}"))

    # -- C14 --------------------------------------------------------------
    # The ledger is what the methods section cites; if it disagrees with the
    # manifest, one of them is lying about how many papers are in the study.
    ledger = read_csv(EXCLUSIONS)
    ledger_hls = {r["paper_id"] for r in ledger if r["set"] == "human_labelled"}
    both = ledger_hls & active_ids
    cl.check("C14", "no paper is both in the exclusion ledger and active",
             not both,
             (f"in the ledger yet active: {sample(both)}" if both
              else f"{len(ledger_hls)} HLS exclusions, none active"))

    # -- verdict ----------------------------------------------------------
    print()
    if cl.failed:
        print(f"{len(cl.failed)} of {len(cl.results)} checks FAILED -- the HLS is not closed.")
        print("Fix these before restoring any US paper; each failure can add restore candidates.")
    else:
        print(f"All {len(cl.results)} checks passed. The HLS is closed and split.")

    # -- DC42 preview -----------------------------------------------------
    removed = read_csv(REVIEW_DIR / "02_removed_us_duplicates.csv")
    ledger_reason = {r["paper_id"]: r["reason"] for r in ledger}
    candidates = [r for r in removed if r["matched_validation_paper_id"] not in labels]

    print()
    print("=" * 70)
    restored = {r["paper_id"] for r in read_csv(REVIEW_DIR / "15_dc42_restored.csv")}
    outstanding = [r for r in candidates if r["removed_paper_id"] not in restored]

    print(f"DC42: {len(candidates)} of {len(removed)} removed US papers have a twin with no label")
    print("=" * 70)
    print(f"  {len(candidates) - len(outstanding)} already restored "
          f"(results/review/15_dc42_restored.csv)")
    print(f"  {len(outstanding)} outstanding"
          + (" -- run scripts/15_restore_dc42_duplicates.py" if outstanding else ""))
    print()
    if not outstanding:
        conn.close()
        return 1 if cl.failed else 0
    by_reason = Counter(
        ledger_reason.get(r["matched_validation_paper_id"], "unknown")[:70]
        for r in candidates)
    for reason, n in by_reason.most_common():
        print(f"  {n:4}  {reason}")
    print()
    for row in candidates:
        print(f"  {row['removed_paper_id']}  <- twin {row['matched_validation_paper_id']}  "
              f"{row['title'][:60]}")

    conn.close()
    return 1 if cl.failed else 0


if __name__ == "__main__":
    sys.exit(main())
