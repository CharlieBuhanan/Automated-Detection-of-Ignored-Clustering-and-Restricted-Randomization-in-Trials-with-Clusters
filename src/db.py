"""SQLite storage: ground-truth labels and append-only judgments.

Status, 2026-08-27. All three label files have arrived and are merged into
data/ground_truth.csv by scripts/07_build_ground_truth.py (NCI's
GroundTruthDataNCI01.xlsx, NHLBI's crt_review_table_112.tex and
NHLBI_exclusions_178.csv). 483 papers carry a clean label in
`validation_labels`.

**The split is assigned and permanent (2026-08-26):** 338 build / 145 holdout,
stratified on gate-survivor status -- 123/53 survivors, 215/92 excluded.
`assign_split()` now refuses to re-run without an explicit force, which is the
point of it (DC18). Build rounds were cut on top of that split by
scripts/17_assign_build_rounds.py and live in
results/04_classification/build_rounds.csv, not here.

`judgments` is still empty: the schema comes straight from research design/PLAN.md,
but no classification code writes to it yet.

Two tables, two very different lifetimes:

    validation_labels   the human answers. Written once per label file, then
                        treated as read-only truth. One row per paper.
    judgments           what the model said. One row per judgment, appended
                        forever, never updated in place.

Extracted text is deliberately NOT here -- it lives in data/extracted_text/ as
JSON. Text is bulk, immutable, and read by path; putting 100MB of it in the
same file as the accuracy math would make every query drag it around.

Nothing in this module knows about Claude, promptbooks, or PDFs. It stores rows and
answers questions about them, so the classification code can be tested against
a temporary database.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# The three tasks, fixed. A CHECK constraint on this list is the storage-layer
# half of the "never conflate tasks" rule: a typo'd task name fails loudly at
# insert instead of quietly creating a fourth task nobody notices until the
# accuracy numbers do not add up.
#
# "inclusion" was dropped as a task: nothing in the human labels encodes it.
# NCI's `review_category` covers only 95 of the 176 kept papers and no NHLBI
# paper at all, so there is no answer to score an inclusion call against.
# Exclusion alone is the gate.
TASKS = ("exclusion", "power_analysis", "data_analysis")

PASS_PRIMARY = "primary"
PASS_REVIEW = "review"

SPLIT_BUILD = "build"
SPLIT_HOLDOUT = "holdout"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS validation_labels (
    paper_id         TEXT PRIMARY KEY,
    source_file      TEXT NOT NULL,
    citation_raw     TEXT NOT NULL,
    exclusion_reason TEXT,
    power            TEXT,
    stats            TEXT,
    review_category  TEXT,
    split            TEXT CHECK (split IS NULL OR split IN ('{SPLIT_BUILD}', '{SPLIT_HOLDOUT}')),
    matched_by       TEXT NOT NULL,
    match_score      REAL,
    loaded_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS judgments (
    paper_id        TEXT NOT NULL,
    task            TEXT NOT NULL CHECK (task IN {TASKS!r}),
    judgment_index  INTEGER NOT NULL,
    pass_name       TEXT NOT NULL CHECK (pass_name IN ('{PASS_PRIMARY}', '{PASS_REVIEW}')),
    model_used      TEXT NOT NULL,
    decision        TEXT NOT NULL,
    reasoning       TEXT NOT NULL,
    promptbook_evidence TEXT NOT NULL,
    confidence      REAL,
    promptbook_version  TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    UNIQUE (paper_id, task, judgment_index)
);

CREATE INDEX IF NOT EXISTS idx_judgments_paper_task ON judgments (paper_id, task);
CREATE INDEX IF NOT EXISTS idx_judgments_promptbook ON judgments (promptbook_version);
CREATE INDEX IF NOT EXISTS idx_labels_split         ON validation_labels (split);
"""

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "review.db"


def connect(db_path: Path = DEFAULT_PATH) -> sqlite3.Connection:
    """Open (creating if needed) the database, with the schema applied.

    Foreign keys and WAL are on: WAL so a long batch run can be read from
    another process while it writes, which is how you watch a job's progress
    without stopping it.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ labels


def insert_labels(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Insert label rows. Returns how many landed.

    `INSERT OR REPLACE` on paper_id, so re-running a load after fixing a bad
    citation match corrects the row instead of failing. Labels are truth being
    transcribed, not judgments being accumulated -- the append-only rule that
    governs `judgments` would only pile up duplicate transcriptions here.

    Note this deliberately clears `split`: a corrected match means the paper's
    identity changed, and silently keeping a holdout assignment made for a
    different paper is exactly the drift the split exists to prevent.
    """
    now = _now()
    conn.executemany(
        """INSERT OR REPLACE INTO validation_labels
           (paper_id, source_file, citation_raw, exclusion_reason, power, stats,
            review_category, split, matched_by, match_score, loaded_at)
           VALUES (:paper_id, :source_file, :citation_raw, :exclusion_reason, :power,
                   :stats, :review_category, NULL, :matched_by, :match_score, :loaded_at)""",
        [{**r, "loaded_at": now} for r in rows],
    )
    conn.commit()
    return len(rows)


def label_counts(conn: sqlite3.Connection) -> dict:
    """Per-task label coverage, for reconciling against the source spreadsheet."""
    row = conn.execute(
        """SELECT COUNT(*)                                              AS total,
                  SUM(exclusion_reason IS NOT NULL AND exclusion_reason != '') AS excluded,
                  SUM(power           IS NOT NULL AND power           != '') AS power,
                  SUM(stats           IS NOT NULL AND stats           != '') AS stats,
                  SUM(review_category IS NOT NULL AND review_category != '') AS review_category,
                  SUM(split = ?)                                        AS build,
                  SUM(split = ?)                                        AS holdout
           FROM validation_labels""",
        (SPLIT_BUILD, SPLIT_HOLDOUT),
    ).fetchone()
    return {k: (row[k] or 0) for k in row.keys()}


def _split_rank(paper_id: str, seed: str) -> float:
    """A paper's position in the shuffle: a uniform fraction in [0, 1).

    Hashed from `seed + paper_id` alone, so it depends on nothing but the
    paper's identity -- not row order, not insertion time, not how many labels
    existed when it ran.
    """
    import hashlib

    digest = hashlib.sha256(f"{seed}:{paper_id}".encode()).hexdigest()
    return int(digest[:8], 16) / 0x100000000


def _gate_stratum(label: sqlite3.Row | dict) -> str:
    """Which stratum a paper belongs to: did the humans keep it or exclude it?

    This is the same question expected_decision() answers for the exclusion
    task, phrased as a stratum name so the counts read plainly in the log.
    """
    return "excluded" if expected_decision(label, "exclusion") == "yes" else "survivor"


def assign_split(conn: sqlite3.Connection, holdout_frac: float = 0.3,
                 seed: str = "automated-ignore", force: bool = False) -> dict:
    """Fix the build/holdout split, once, deterministically, stratified on the gate.

    Refuses to re-run once any paper has a split, because the holdout is only
    worth reporting if it was chosen before anyone saw how the promptbooks perform
    on it. Reshuffling after a disappointing holdout number is the single
    easiest way to publish an inflated one, so it takes an explicit force.

    **Stratified on gate-survivor status.** Papers the humans excluded carry no
    power/stats label, so an unstratified 30% draw over all labels leaves
    whatever number of survivors the hash happens to deal into the holdout --
    and survivors are the only papers power_analysis and data_analysis can be
    scored on. Drawing 30% from each stratum separately makes that count a
    guarantee (~53 of 176) instead of a coin flip, and costs nothing: the
    exclusion task is scored over both strata either way.

    Within a stratum, papers are ranked by `_split_rank()` and the lowest
    `holdout_frac` of them are held out. Ranking rather than thresholding is
    what makes the per-stratum count exact.

    **The trade-off ranking buys:** a paper's assignment now depends on which
    other papers are in its stratum, so this is no longer stable under adding
    labels later -- loading a new label file and re-running would reshuffle.
    That is guarded twice over: the function refuses to re-run at all, and
    `scripts/04_load_ground_truth.py --assign-split` refuses to call it while
    any active HLS paper still lacks a label.

    Returns the two split counts plus a per-stratum breakdown under "strata".
    """
    existing = conn.execute(
        "SELECT COUNT(*) FROM validation_labels WHERE split IS NOT NULL").fetchone()[0]
    if existing and not force:
        raise RuntimeError(
            f"{existing} paper(s) already have a split. The holdout is fixed once, "
            "on purpose -- pass force=True only if you are deliberately rebuilding it.")

    strata: dict[str, list[str]] = {"survivor": [], "excluded": []}
    for row in conn.execute("SELECT * FROM validation_labels ORDER BY paper_id"):
        strata[_gate_stratum(row)].append(row["paper_id"])

    assignments = []
    breakdown = {}
    for stratum, paper_ids in strata.items():
        # Sort by rank, then paper_id: paper_id breaks a hash tie the same way
        # on every machine, so the boundary paper is never decided by row order.
        ranked = sorted(paper_ids, key=lambda p: (_split_rank(p, seed), p))
        n_holdout = round(holdout_frac * len(ranked))
        for position, paper_id in enumerate(ranked):
            assignments.append(
                (SPLIT_HOLDOUT if position < n_holdout else SPLIT_BUILD, paper_id))
        breakdown[stratum] = {
            SPLIT_BUILD: len(ranked) - n_holdout,
            SPLIT_HOLDOUT: n_holdout,
        }

    conn.executemany("UPDATE validation_labels SET split = ? WHERE paper_id = ?", assignments)
    conn.commit()

    counts = {SPLIT_BUILD: 0, SPLIT_HOLDOUT: 0}
    for split, _ in assignments:
        counts[split] += 1
    counts["strata"] = breakdown
    return counts


# ------------------------------------------------------------------ judgments


def next_judgment_index(conn: sqlite3.Connection, paper_id: str, task: str) -> int:
    """The index the next judgment of this paper on this task should carry.

    Counts across the whole project, not per run: promptbook-building rounds
    re-judge the same papers repeatedly, and the running total is what answers
    "how much has this paper been chewed on?"
    """
    row = conn.execute(
        "SELECT MAX(judgment_index) FROM judgments WHERE paper_id = ? AND task = ?",
        (paper_id, task),
    ).fetchone()
    return (row[0] or 0) + 1


def insert_judgment(conn: sqlite3.Connection, *, paper_id: str, task: str, pass_name: str,
                    model_used: str, decision: str, reasoning: str, promptbook_evidence: str,
                    confidence: float | None, promptbook_version: str,
                    judgment_index: int | None = None) -> int:
    """Append one judgment. Returns its judgment_index.

    Pass `judgment_index` explicitly when replaying an interrupted batch: the
    UNIQUE constraint then makes a re-inserted row fail rather than silently
    become a second judgment, which would inflate the accuracy denominator.
    """
    if task not in TASKS:
        raise ValueError(f"unknown task {task!r}; expected one of {TASKS}")

    index = judgment_index or next_judgment_index(conn, paper_id, task)
    conn.execute(
        """INSERT INTO judgments
           (paper_id, task, judgment_index, pass_name, model_used, decision,
            reasoning, promptbook_evidence, confidence, promptbook_version, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (paper_id, task, index, pass_name, model_used, decision, reasoning,
         promptbook_evidence, confidence, promptbook_version, _now()),
    )
    conn.commit()
    return index


def latest_judgments(conn: sqlite3.Connection, task: str,
                     promptbook_version: str | None = None) -> list[sqlite3.Row]:
    """Each paper's current answer for a task: its highest judgment_index.

    Scope to a `promptbook_version` to ask what a specific promptbook
    concluded, which is what the regression step compares between commits.
    """
    where = "task = ?"
    params: list = [task]
    if promptbook_version:
        where += " AND promptbook_version = ?"
        params.append(promptbook_version)

    # The same filter is applied twice on purpose: once to pick each paper's
    # highest index within this scope, once to keep the joined row inside it.
    # Filtering only the subquery would let a paper's judgment from a different
    # promptbook version come back as its "latest".
    return conn.execute(
        f"""SELECT j.* FROM judgments j
            JOIN (SELECT paper_id, MAX(judgment_index) AS top
                    FROM judgments
                   WHERE {where}
                GROUP BY paper_id) latest
              ON j.paper_id = latest.paper_id
             AND j.judgment_index = latest.top
           WHERE {where}""",
        params + params,
    ).fetchall()


def accuracy_against_labels(conn: sqlite3.Connection, task: str, split: str = SPLIT_BUILD,
                            promptbook_version: str | None = None) -> dict:
    """Compare the current judgments for a task against the human labels.

    Two decisions never count as a miss, for different reasons:

    `undecidable` is an abstention -- folding it into the error rate would hide
    a promptbook that is learning to refuse rather than to judge.

    `wrong_text` is a *data* problem, not a judgment: the model is saying the
    fetched text is not a study report at all. Scoring it against a human label
    would charge the promptbook for a bad PDF. Counted and reported separately
    so a cluster of them is visible as a corpus fault, which is the point.
    """
    labels = {r["paper_id"]: r for r in conn.execute(
        "SELECT * FROM validation_labels WHERE split = ?", (split,))}

    hit = miss = abstained = wrong_text = unlabeled = 0
    for row in latest_judgments(conn, task, promptbook_version):
        label = labels.get(row["paper_id"])
        if label is None:
            unlabeled += 1
            continue
        if row["decision"] == "undecidable":
            abstained += 1
            continue
        if row["decision"] == "wrong_text":
            wrong_text += 1
            continue
        truth = expected_decision(label, task)
        if truth is None:
            unlabeled += 1
        elif row["decision"] == truth:
            hit += 1
        else:
            miss += 1

    scored = hit + miss
    return {
        "task": task, "split": split, "hit": hit, "miss": miss,
        "undecidable": abstained, "wrong_text": wrong_text, "unlabeled": unlabeled,
        "accuracy": round(hit / scored, 4) if scored else None,
    }


def expected_decision(label: sqlite3.Row | dict, task: str) -> str | None:
    """The human answer for one task, or None if this paper carries no label
    for it -- which is normal: a paper the humans excluded never received
    power/stats labels, exactly as the gate intends.

    Every task answers in the same vocabulary the Decision schema uses --
    "yes" / "no" -- so accuracy_against_labels() can compare without knowing
    which task it is looking at. For exclusion, "yes" means exclude the paper.
    An earlier version returned "exclude"/"keep" here, which no model output
    could ever equal: exclusion scored 0% however good the answers were.
    """
    get = label.__getitem__ if isinstance(label, sqlite3.Row) else label.get

    if task == "exclusion":
        # A recorded reason is what "the humans excluded this" looks like.
        return "yes" if get("exclusion_reason") else "no"
    value = get("power" if task == "power_analysis" else "stats")
    return value.strip().lower() if value else None
