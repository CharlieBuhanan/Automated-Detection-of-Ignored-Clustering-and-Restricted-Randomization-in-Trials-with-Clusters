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

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

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
    -- These remain nullable to preserve historical CLI judgments.  Every new
    -- reportable judgment is linked to an immutable run and raw response; the
    -- evaluator labels NULL rows as legacy/unprovenanced instead of guessing
    -- their effort or transport.
    run_id          TEXT,
    response_id     TEXT,
    timestamp       TEXT NOT NULL,
    UNIQUE (paper_id, task, judgment_index)
);

-- `classification_runs` holds the round/request invariants.  It is separate
-- from judgments because one combined response can yield two task judgments,
-- and because a retry can yield no judgment at all while still being evidence
-- about cost and failure handling.
CREATE TABLE IF NOT EXISTS classification_runs (
    run_id                  TEXT PRIMARY KEY,
    task                    TEXT NOT NULL,
    round_no                INTEGER,
    transport               TEXT NOT NULL,
    route                   TEXT NOT NULL,
    model_used              TEXT NOT NULL,
    effort                  TEXT NOT NULL,
    system_prompt_sha256    TEXT NOT NULL,
    promptbook_version      TEXT NOT NULL,
    promptbook_sha256       TEXT NOT NULL,
    request_config_sha256   TEXT NOT NULL,
    config_fingerprint      TEXT NOT NULL,
    environment_json        TEXT NOT NULL,
    source_path             TEXT,
    created_at              TEXT NOT NULL
);

-- One immutable raw/provider response belongs to one run.  `response_id` is
-- local and stable (not necessarily an Anthropic ID), so both the CLI and
-- future Batch transport can use the same idempotency boundary.
CREATE TABLE IF NOT EXISTS classification_responses (
    response_id             TEXT PRIMARY KEY,
    run_id                  TEXT NOT NULL REFERENCES classification_runs(run_id),
    paper_id                TEXT NOT NULL,
    attempt                 INTEGER,
    provider_response_id    TEXT,
    raw_path                TEXT,
    status                  TEXT NOT NULL,
    metadata_json           TEXT,
    created_at              TEXT NOT NULL,
    UNIQUE (run_id, paper_id, attempt)
);

CREATE INDEX IF NOT EXISTS idx_judgments_paper_task ON judgments (paper_id, task);
CREATE INDEX IF NOT EXISTS idx_judgments_promptbook ON judgments (promptbook_version);
CREATE INDEX IF NOT EXISTS idx_classification_runs_config
    ON classification_runs (config_fingerprint);
CREATE INDEX IF NOT EXISTS idx_classification_responses_run_paper
    ON classification_responses (run_id, paper_id);
CREATE INDEX IF NOT EXISTS idx_labels_split         ON validation_labels (split);
"""

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "review.db"


def _migrate_judgment_provenance(conn: sqlite3.Connection) -> None:
    """Add provenance links to an existing append-only judgments table.

    SQLite's ``CREATE TABLE IF NOT EXISTS`` deliberately does not alter an old
    table.  The project already has paid, valid CLI judgments, so this migration
    only adds nullable columns and never rewrites a scientific decision.  An
    old row therefore remains visibly legacy until a documented backfill can
    link it to immutable raw evidence.
    """
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(judgments)").fetchall()
    }
    if "run_id" not in columns:
        conn.execute("ALTER TABLE judgments ADD COLUMN run_id TEXT")
    if "response_id" not in columns:
        conn.execute("ALTER TABLE judgments ADD COLUMN response_id TEXT")

    # Partial uniqueness preserves the historical NULL rows while making a
    # replay of a known raw/provider response fail loudly rather than acquire a
    # new judgment_index and silently inflate a metric denominator.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_judgments_run_id ON judgments (run_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_judgments_response_id ON judgments (response_id)")
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_judgments_response_task
             ON judgments (response_id, task) WHERE response_id IS NOT NULL""")
    conn.commit()


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
    _migrate_judgment_provenance(conn)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- provenance

# These are intentionally broader than Reading Room's original G11 list.  A
# change in route, transport, or request serialization can change what reaches
# the model even if the model/effort pair is unchanged.  Values are recorded in
# the database rather than inferred later from a directory name.
COMPARABLE_CONFIGURATION_FIELDS = (
    "model_used",
    "effort",
    "system_prompt_sha256",
    "promptbook_version",
    "promptbook_sha256",
    "route",
    "transport",
    "request_config_sha256",
)


class ProvenanceError(ValueError):
    """A run/response link is incomplete or contradicts immutable evidence."""


def _canonical_json(value: Any) -> str:
    """Stable JSON for fingerprints and immutable-record comparisons."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _nonempty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProvenanceError(f"{field} is required for a reportable run")
    return value


def _run_request_config(environment: Mapping[str, Any], *, route: str,
                        transport: str) -> dict[str, Any]:
    """The request-affecting portion of a run environment.

    Timestamps and host details distinguish *runs* but not experimental
    conditions.  Conversely, the verbatim argv/settings/schema fields can
    change a request while the named promptbook version stays the same, so they
    deliberately contribute to this hash whenever present.
    """
    request_keys = (
        "argv", "thinking", "settings_sha256", "claude_code_version",
        "tools_offered", "request_template_sha256", "response_schema_sha256",
        "max_output_tokens", "temperature", "top_p",
    )
    return {
        "route": route,
        "transport": transport,
        **{key: environment.get(key) for key in request_keys
           if environment.get(key) is not None},
    }


def _run_configuration(*, model_used: str, effort: str,
                       system_prompt_sha256: str, promptbook_version: str,
                       promptbook_sha256: str, route: str, transport: str,
                       request_config_sha256: str) -> dict[str, str]:
    return {
        "model_used": model_used,
        "effort": effort,
        "system_prompt_sha256": system_prompt_sha256,
        "promptbook_version": promptbook_version,
        "promptbook_sha256": promptbook_sha256,
        "route": route,
        "transport": transport,
        "request_config_sha256": request_config_sha256,
    }


def run_id_from_environment(environment: Mapping[str, Any], *,
                            source_path: str | Path | None = None) -> str:
    """Deterministic local identity for one immutable CLI/API run record.

    The full environment (including timing) participates here on purpose: two
    otherwise identical rounds are two distinct runs.  Configuration
    comparability instead uses ``config_fingerprint`` below, which excludes
    incidental timing/host values.
    """
    task = str(environment.get("task") or "classification")
    round_no = environment.get("round")
    prefix = f"{task}-r{round_no}" if round_no is not None else task
    identity = {
        "environment": dict(environment),
        "source_path": str(source_path) if source_path is not None else None,
    }
    return f"run-{prefix}-{_sha256_json(identity)[:20]}"


def response_id_for_attempt(*, run_id: str, paper_id: str, attempt: int | None,
                            provider_response_id: str | None = None) -> str:
    """Stable local response identity, shared by one or two task judgments."""
    if provider_response_id:
        # Scope a provider handle to its local run: providers need not promise
        # global uniqueness across transports or test fixtures.
        suffix = f"provider:{provider_response_id}"
    else:
        suffix = f"attempt:{attempt if attempt is not None else 'unknown'}"
    return f"response-{_sha256_json({'run_id': run_id, 'paper_id': paper_id, 'id': suffix})}"


def register_run_environment(
        conn: sqlite3.Connection, environment: Mapping[str, Any], *,
        source_path: str | Path | None = None, run_id: str | None = None,
        transport: str = "reading_room", route: str | None = None,
        commit: bool = True) -> str:
    """Record an immutable, fully configured classification run.

    Re-registering exactly the same run is a no-op; attempting to reuse an ID
    for a different configuration raises.  This makes checker/API restarts
    safe without allowing mutable provenance.
    """
    task = _nonempty_string(environment.get("task"), field="task")
    model_used = _nonempty_string(environment.get("model"), field="model")
    effort = _nonempty_string(environment.get("effort"), field="effort")
    system_prompt_sha256 = _nonempty_string(
        environment.get("system_prompt_sha256"), field="system_prompt_sha256")
    promptbook_version = _nonempty_string(
        environment.get("promptbook_version"), field="promptbook_version")
    promptbook_sha256 = _nonempty_string(
        environment.get("promptbook_sha256"), field="promptbook_sha256")
    route = _nonempty_string(route or environment.get("route") or task, field="route")
    transport = _nonempty_string(transport or environment.get("transport"), field="transport")
    request_config_sha256 = str(environment.get("request_config_sha256") or
                                _sha256_json(_run_request_config(
                                    environment, route=route, transport=transport)))
    config = _run_configuration(
        model_used=model_used, effort=effort,
        system_prompt_sha256=system_prompt_sha256,
        promptbook_version=promptbook_version,
        promptbook_sha256=promptbook_sha256,
        route=route, transport=transport,
        request_config_sha256=request_config_sha256)
    config_fingerprint = _sha256_json(config)
    run_id = run_id or run_id_from_environment(environment, source_path=source_path)
    run_id = _nonempty_string(run_id, field="run_id")
    payload = {
        "run_id": run_id,
        "task": task,
        "round_no": environment.get("round"),
        "transport": transport,
        "route": route,
        "model_used": model_used,
        "effort": effort,
        "system_prompt_sha256": system_prompt_sha256,
        "promptbook_version": promptbook_version,
        "promptbook_sha256": promptbook_sha256,
        "request_config_sha256": request_config_sha256,
        "config_fingerprint": config_fingerprint,
        "environment_json": _canonical_json(dict(environment)),
        "source_path": str(source_path) if source_path is not None else None,
        "created_at": _now(),
    }
    prior = conn.execute(
        "SELECT * FROM classification_runs WHERE run_id = ?", (run_id,)).fetchone()
    if prior is not None:
        immutable = ("task", "round_no", "transport", "route", "model_used", "effort",
                     "system_prompt_sha256", "promptbook_version", "promptbook_sha256",
                     "request_config_sha256", "config_fingerprint", "environment_json",
                     "source_path")
        differences = [field for field in immutable if prior[field] != payload[field]]
        if differences:
            raise ProvenanceError(
                f"run_id {run_id!r} already records different immutable fields: "
                f"{', '.join(differences)}")
        return run_id

    conn.execute(
        """INSERT INTO classification_runs
           (run_id, task, round_no, transport, route, model_used, effort,
            system_prompt_sha256, promptbook_version, promptbook_sha256,
            request_config_sha256, config_fingerprint, environment_json,
            source_path, created_at)
           VALUES (:run_id, :task, :round_no, :transport, :route, :model_used,
                   :effort, :system_prompt_sha256, :promptbook_version,
                   :promptbook_sha256, :request_config_sha256,
                   :config_fingerprint, :environment_json, :source_path,
                   :created_at)""",
        payload,
    )
    if commit:
        conn.commit()
    return run_id


def register_response(
        conn: sqlite3.Connection, *, response_id: str, run_id: str,
        paper_id: str, attempt: int | None, provider_response_id: str | None = None,
        raw_path: str | Path | None = None, status: str = "accepted",
        metadata: Mapping[str, Any] | None = None, commit: bool = True) -> str:
    """Record one immutable raw/provider response, idempotently.

    A duplicate with precisely the same facts is safe on resume.  A duplicate
    ID that points to another paper, attempt, raw path, or provider message is
    evidence of a bookkeeping error and is rejected.
    """
    response_id = _nonempty_string(response_id, field="response_id")
    run_id = _nonempty_string(run_id, field="run_id")
    paper_id = _nonempty_string(paper_id, field="paper_id")
    if conn.execute("SELECT 1 FROM classification_runs WHERE run_id = ?", (run_id,)).fetchone() is None:
        raise ProvenanceError(
            f"run_id {run_id!r} is not registered; record its environment before a response")
    payload = {
        "response_id": response_id,
        "run_id": run_id,
        "paper_id": paper_id,
        "attempt": attempt,
        "provider_response_id": provider_response_id,
        "raw_path": str(raw_path) if raw_path is not None else None,
        "status": _nonempty_string(status, field="status"),
        "metadata_json": _canonical_json(dict(metadata)) if metadata is not None else None,
        "created_at": _now(),
    }
    prior = conn.execute(
        "SELECT * FROM classification_responses WHERE response_id = ?", (response_id,)).fetchone()
    if prior is not None:
        immutable = ("run_id", "paper_id", "attempt", "provider_response_id", "raw_path",
                     "status", "metadata_json")
        differences = [field for field in immutable if prior[field] != payload[field]]
        if differences:
            raise ProvenanceError(
                f"response_id {response_id!r} already records different immutable fields: "
                f"{', '.join(differences)}")
        return response_id

    conn.execute(
        """INSERT INTO classification_responses
           (response_id, run_id, paper_id, attempt, provider_response_id,
            raw_path, status, metadata_json, created_at)
           VALUES (:response_id, :run_id, :paper_id, :attempt,
                   :provider_response_id, :raw_path, :status, :metadata_json,
                   :created_at)""",
        payload,
    )
    if commit:
        conn.commit()
    return response_id


def judgment_exists_for_response_task(conn: sqlite3.Connection, *, response_id: str,
                                      task: str) -> bool:
    """Whether this exact response has already become this task's judgment."""
    return conn.execute(
        "SELECT 1 FROM judgments WHERE response_id = ? AND task = ?",
        (response_id, task),
    ).fetchone() is not None


def response_judgment_tasks(conn: sqlite3.Connection, response_id: str) -> tuple[str, ...]:
    """Stable task list already ingested from a raw/provider response."""
    return tuple(row["task"] for row in conn.execute(
        "SELECT task FROM judgments WHERE response_id = ? ORDER BY task", (response_id,)))


# ------------------------------------------------------------------ labels


def insert_labels(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Insert label rows, preserving each paper's split. Returns how many landed.

    `INSERT OR REPLACE` on paper_id, so re-running a load after fixing a bad
    citation match corrects the row instead of failing. Labels are truth being
    transcribed, not judgments being accumulated -- the append-only rule that
    governs `judgments` would only pile up duplicate transcriptions here.

    **`split` survives a reload when the paper's identity did not change.** An
    earlier version wrote NULL unconditionally, on the reasoning that a corrected
    match means a different paper and a holdout assignment made for a different
    paper is exactly the drift the split exists to prevent. That reasoning is
    right about a *corrected* match and wrong about every other row: a load
    re-inserts the whole file, so one fixed citation silently nulled all 483
    splits. Since assign_split() refuses to re-run (DC18), recovering from that
    needs `--force-split`, which deals a *different* split -- the permanent,
    un-reassignable structure destroyed by an ordinary reload.

    So the identity test is made explicit instead of assumed. A row keeps its
    split when `citation_raw` is unchanged -- that string is what the join
    resolved, so if it moved, the label now describes a different paper and the
    old assignment must not follow it.
    """
    now = _now()
    existing = {r["paper_id"]: r for r in conn.execute(
        "SELECT paper_id, split, citation_raw FROM validation_labels")}

    prepared = []
    for row in rows:
        prior = existing.get(row["paper_id"])
        keeps_identity = prior is not None and prior["citation_raw"] == row["citation_raw"]
        prepared.append({**row, "loaded_at": now,
                         "split": prior["split"] if keeps_identity else None})

    conn.executemany(
        """INSERT OR REPLACE INTO validation_labels
           (paper_id, source_file, citation_raw, exclusion_reason, power, stats,
            review_category, split, matched_by, match_score, loaded_at)
           VALUES (:paper_id, :source_file, :citation_raw, :exclusion_reason, :power,
                   :stats, :review_category, :split, :matched_by, :match_score, :loaded_at)""",
        prepared,
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
                    judgment_index: int | None = None, run_id: str | None = None,
                    response_id: str | None = None, commit: bool = True) -> int:
    """Append one judgment. Returns its judgment_index.

    Pass `judgment_index` explicitly when replaying an interrupted batch: the
    UNIQUE constraint then makes a re-inserted row fail rather than silently
    become a second judgment, which would inflate the accuracy denominator.

    New reportable rows must provide both ``run_id`` and ``response_id`` after
    registering their immutable run environment and raw/provider response.  The
    pair is optional only for legacy rows preserved by the provenance migration.
    ``commit=False`` is for an all-or-nothing combined response; callers then
    own the surrounding transaction or use :func:`insert_judgments_atomically`.
    """
    if task not in TASKS:
        raise ValueError(f"unknown task {task!r}; expected one of {TASKS}")
    if (run_id is None) != (response_id is None):
        raise ProvenanceError(
            "run_id and response_id must be supplied together (or both omitted for legacy data)")
    if run_id is not None:
        response = conn.execute(
            "SELECT run_id, paper_id FROM classification_responses WHERE response_id = ?",
            (response_id,),
        ).fetchone()
        if response is None:
            raise ProvenanceError(
                f"response_id {response_id!r} is not registered before its judgment")
        if response["run_id"] != run_id:
            raise ProvenanceError(
                f"response_id {response_id!r} belongs to run {response['run_id']!r}, not {run_id!r}")
        if response["paper_id"] != paper_id:
            raise ProvenanceError(
                f"response_id {response_id!r} belongs to paper {response['paper_id']!r}, not {paper_id!r}")

    index = judgment_index or next_judgment_index(conn, paper_id, task)
    conn.execute(
        """INSERT INTO judgments
           (paper_id, task, judgment_index, pass_name, model_used, decision,
            reasoning, promptbook_evidence, confidence, promptbook_version,
            run_id, response_id, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (paper_id, task, index, pass_name, model_used, decision, reasoning,
         promptbook_evidence, confidence, promptbook_version, run_id,
         response_id, _now()),
    )
    if commit:
        conn.commit()
    return index


def insert_judgments_atomically(conn: sqlite3.Connection,
                                judgments: list[Mapping[str, Any]]) -> list[int]:
    """Insert an all-or-nothing set of task judgments from one response.

    This is the persistence boundary for the combined power/data route: a bad
    second half rolls back the first half, yielding zero judgments rather than
    an invalid partially-combined scientific record.  A savepoint works both
    as a stand-alone operation and inside a caller's larger transaction.
    """
    if not judgments:
        return []
    conn.execute("SAVEPOINT combined_judgment_insert")
    try:
        indices = [insert_judgment(conn, commit=False, **dict(record))
                   for record in judgments]
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT combined_judgment_insert")
        conn.execute("RELEASE SAVEPOINT combined_judgment_insert")
        raise
    conn.execute("RELEASE SAVEPOINT combined_judgment_insert")
    conn.commit()
    return indices


def latest_judgments(conn: sqlite3.Connection, task: str,
                     promptbook_version: str | None = None) -> list[sqlite3.Row]:
    """Each paper's current answer for a task: its highest judgment_index.

    Scope to a `promptbook_version` to ask what a specific promptbook
    concluded, which is what the regression step compares between commits.
    """
    # `classification_runs` carries its own `task` and `promptbook_version`, so
    # once that table is LEFT JOINed the bare column names are ambiguous and
    # SQLite refuses the query.  The subquery sees only `judgments` and stays
    # unqualified; the outer clause is qualified to `j`.
    where = "task = ?"
    outer_where = "j.task = ?"
    params: list = [task]
    if promptbook_version:
        where += " AND promptbook_version = ?"
        outer_where += " AND j.promptbook_version = ?"
        params.append(promptbook_version)

    # The same filter is applied twice on purpose: once to pick each paper's
    # highest index within this scope, once to keep the joined row inside it.
    # Filtering only the subquery would let a paper's judgment from a different
    # promptbook version come back as its "latest".
    return conn.execute(
        f"""SELECT j.*, r.config_fingerprint AS provenance_config_fingerprint,
                      r.transport AS provenance_transport,
                      r.route AS provenance_route,
                      r.effort AS provenance_effort,
                      r.source_path AS provenance_source_path,
                      r.request_config_sha256 AS provenance_request_config_sha256
                 FROM judgments j
            LEFT JOIN classification_runs r ON r.run_id = j.run_id
            JOIN (SELECT paper_id, MAX(judgment_index) AS top
                    FROM judgments
                   WHERE {where}
                GROUP BY paper_id) latest
              ON j.paper_id = latest.paper_id
             AND j.judgment_index = latest.top
           WHERE {outer_where}""",
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
