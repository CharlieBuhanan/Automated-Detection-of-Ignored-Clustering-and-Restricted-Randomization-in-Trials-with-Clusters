"""NOT READY -- schema is provisional. Do not build on it yet.

The ground truth is incomplete: only GroundTruthDataNCI01.xlsx has arrived
(232 rows, 230 joined), covering 232 of the 569 Human Labelled Set papers. The NHLBI
labels are still to come, and their columns may not match NCI's -- if they
carry a different set of fields, `validation_labels` changes shape and
`expected_decision()` changes with it.

So treat everything here as a sketch pending those files:
  - the `validation_labels` columns are modelled on one spreadsheet
  - `expected_decision()`'s task mapping is inferred, not confirmed
  - the rows already in data/review.db are a provisional load, safe to discard
  - `assign_split()` has never been run, and must not be until every label
    file is loaded -- it fixes the holdout permanently on the first call

`judgments` is the more settled half (it comes straight from research design/PLAN.md) but no
classification code writes to it yet either.

---

SQLite storage: ground-truth labels and append-only judgments.

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

# The four tasks, fixed. A CHECK constraint on this list is the storage-layer
# half of the "never conflate tasks" rule: a typo'd task name fails loudly at
# insert instead of quietly creating a fifth task nobody notices until the
# accuracy numbers do not add up.
TASKS = ("exclusion", "inclusion", "power_analysis", "data_analysis")

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


def assign_split(conn: sqlite3.Connection, holdout_frac: float = 0.3,
                 seed: str = "cluster-paper-review", force: bool = False) -> dict:
    """Fix the build/holdout split, once, deterministically.

    Refuses to re-run once any paper has a split, because the holdout is only
    worth reporting if it was chosen before anyone saw how the promptbooks perform
    on it. Reshuffling after a disappointing holdout number is the single
    easiest way to publish an inflated one, so it takes an explicit force.

    Assignment hashes `seed + paper_id`, so it depends on nothing but the
    paper's identity -- not row order, not insertion time, not the label count
    at the time it ran. Adding more label files later and re-running leaves
    every existing assignment exactly where it was.
    """
    import hashlib

    existing = conn.execute(
        "SELECT COUNT(*) FROM validation_labels WHERE split IS NOT NULL").fetchone()[0]
    if existing and not force:
        raise RuntimeError(
            f"{existing} paper(s) already have a split. The holdout is fixed once, "
            "on purpose -- pass force=True only if you are deliberately rebuilding it.")

    paper_ids = [r[0] for r in conn.execute(
        "SELECT paper_id FROM validation_labels ORDER BY paper_id")]

    assignments = []
    for paper_id in paper_ids:
        digest = hashlib.sha256(f"{seed}:{paper_id}".encode()).hexdigest()
        # Top 8 hex digits as a uniform fraction in [0, 1).
        fraction = int(digest[:8], 16) / 0x100000000
        assignments.append(
            (SPLIT_HOLDOUT if fraction < holdout_frac else SPLIT_BUILD, paper_id))

    conn.executemany("UPDATE validation_labels SET split = ? WHERE paper_id = ?", assignments)
    conn.commit()

    counts = {SPLIT_BUILD: 0, SPLIT_HOLDOUT: 0}
    for split, _ in assignments:
        counts[split] += 1
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

    `undecidable` is counted separately, never as a miss: it is an abstention,
    and folding it into the error rate would hide a promptbook that is learning to
    refuse rather than to judge.
    """
    labels = {r["paper_id"]: r for r in conn.execute(
        "SELECT * FROM validation_labels WHERE split = ?", (split,))}

    hit = miss = abstained = unlabeled = 0
    for row in latest_judgments(conn, task, promptbook_version):
        label = labels.get(row["paper_id"])
        if label is None:
            unlabeled += 1
            continue
        if row["decision"] == "undecidable":
            abstained += 1
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
        "undecidable": abstained, "unlabeled": unlabeled,
        "accuracy": round(hit / scored, 4) if scored else None,
    }


def expected_decision(label: sqlite3.Row | dict, task: str) -> str | None:
    """The human answer for one task, or None if this paper carries no label
    for it -- which is normal: a paper the humans excluded never received
    power/stats labels, exactly as the gate intends."""
    get = label.__getitem__ if isinstance(label, sqlite3.Row) else label.get

    if task == "exclusion":
        reason = get("exclusion_reason")
        return "exclude" if reason else "keep"
    if task == "inclusion":
        category = get("review_category")
        return category or None
    value = get("power" if task == "power_analysis" else "stats")
    return value.strip().lower() if value else None
