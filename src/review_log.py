"""Every verdict a human decided, read back from the logs that recorded it.

The manifest's `verdict` column has two kinds of value in it, and they are not
equal. Most are *derived*: `01_verify_identity.py` computes them from what the
identity ladder can see in a PDF, and recomputing them is free and correct. A
few are *decided*: a person looked at the paper and concluded something the file
itself does not say -- this PDF really is the article, this label was never
reviewed, these two institutes disagree. Recomputing one of those destroys it.

That is not hypothetical. A full re-verification on 2026-08-26 reversed all 75
drops and 2 hand-cleared WEAK papers in a single run: a dropped paper whose PDF
had been moved aside came back `PDF_UNREADABLE`, and one whose PDF was still on
disk came back `VERIFIED` and silently re-entered the active corpus. Nothing was
lost only because DC20 requires every departure to be logged, so the decisions
could be read back out.

This module is that read-back, in one place, so the two scripts that care cannot
disagree about it:

    01_verify_identity.py   skips decided papers instead of rescoring them
    16_reapply_drops.py     repairs a manifest where they were rescored anyway

Ordering is by timestamp, never by which log a row came from. `J2XGTHGE` was
cleared by hand in script 03 as a legible PDF, then dropped weeks later by
script 09 because NHLBI never reviewed it. Both are real decisions about the
same paper; the later one is the live one.
"""

import csv
from pathlib import Path

# Each drop log, and the verdict_reason its script writes. Kept in sync by hand
# with the VERDICT_REASON constant in each script. A new drop script that is not
# listed here loses its papers on the next identity re-run, so add it here in
# the same commit that adds the script.
DROP_LOGS = [
    ("09_nhlbi_unreviewed_dropped.csv", "NHLBI_UNREVIEWED"),
    ("10_nonjudgeable_exclusions_dropped.csv", "NONJUDGEABLE_EXCLUSION"),
    ("12_institutional_disagreements_dropped.csv", "INSTITUTIONAL_DISAGREEMENT_UNRESOLVED"),
]

# The by-hand route (script 03) writes every decision to one shared log, with
# the resulting verdict in a column rather than implied by the filename.
MANUAL_LOG = "04_papers_reviewed_results.csv"

# What script 03 recorded for each decision, so the reason survives a rebuild.
# A `skipped` row is deliberately absent: it means the reviewer moved on, not
# that they concluded anything.
MANUAL_REASONS = {
    "no_issue": "MANUAL_OK",
    "replaced": "MANUAL_REPLACED",
    "dropped": "MANUAL_DROPPED",
}


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def collect_decisions(review_dir: Path) -> dict[str, tuple[str, str]]:
    """{paper_id: (verdict, verdict_reason)} for every human decision on record.

    `review_dir` is `results/review/`. Returns the *latest* decision per paper;
    a paper decided twice appears once, carrying whichever came last by
    timestamp.
    """
    review_dir = Path(review_dir)
    dated: list[tuple[str, str, str, str]] = []

    for filename, reason in DROP_LOGS:
        for row in _read_csv(review_dir / filename):
            if row.get("paper_id"):
                dated.append((row.get("dropped_at", ""), row["paper_id"], "DROPPED", reason))

    for row in _read_csv(review_dir / MANUAL_LOG):
        verdict = row.get("new_verdict")
        if verdict and row.get("paper_id"):
            dated.append((
                row.get("reviewed_at", ""),
                row["paper_id"],
                verdict,
                MANUAL_REASONS.get(row.get("decision", ""), "MANUAL_REVIEWED"),
            ))

    decisions: dict[str, tuple[str, str]] = {}
    for _, paper_id, verdict, reason in sorted(dated, key=lambda d: d[0]):
        decisions[paper_id] = (verdict, reason)
    return decisions
