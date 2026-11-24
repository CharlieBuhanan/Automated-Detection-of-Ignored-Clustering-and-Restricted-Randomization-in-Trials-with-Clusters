"""Validate a Reading Room round, then persist only fully checked judgments.

The runner saves raw stream-json first. This script is deliberately the only
place where a response becomes a judgment: it validates the stream walls,
provenance, schema and task-local promptbook evidence before touching SQLite.
For ``combined_analysis`` one raw response produces two ordinary judgments, or
none at all. A parser/semantic failure is retryable until ``MAX_ATTEMPTS``;
exhaustion is a ``review_required`` terminal status, never a fabricated model
``undecidable`` judgment.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import db                                              # noqa: E402
import reading_room as rr                              # noqa: E402
import schemas                                         # noqa: E402

RESULTS = ROOT / "results" / "04_classification"
RAW_ROOT = RESULTS / "raw"
LEDGER = RESULTS / "retry_ledger.csv"

# Decision 18: every `other: <label>` in an accepted answer, append-only, so a
# label that recurs across papers can be promoted into its list in a later
# promptbook version. Written only on --write, with the judgments.
OTHER_LABELS = RESULTS / "other_labels.csv"
OTHER_LABEL_COLUMNS = ["timestamp", "route", "round", "promptbook_version",
                       "paper_id", "attempt", "field", "label", "raw_path"]

CHECKED_COLUMNS = [
    "paper_id", "token", "task", "round", "status", "decision",
    "confidence", "reasoning", "promptbook_evidence", "cited_rules",
    "was_fenced", "failure_kind", "failure_case", "detail",
    "flagged_other_papers", "raw_path", "attempt", "retry_eligible",
    "terminal_status", "power_decision", "power_confidence",
    "power_reasoning", "power_promptbook_evidence", "power_cited_rules",
    "data_decision", "data_confidence", "data_reasoning",
    "data_promptbook_evidence", "data_cited_rules",
    "exclusion_reason", "other_labels",
]

WRITE_RECEIPTS = "checker_write_receipts.json"

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise rr.Refuse(f"{path} does not exist. Run scripts/20_reading_room.py first")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def latest_attempt_per_paper(index: list[dict]) -> tuple[list[dict], list[dict]]:
    """Collapse append-only raw index rows to the latest attempt per paper."""
    latest = rr.latest_attempts_by_paper(index)
    winners = {id(row) for row in latest.values()}
    kept = [row for row in index if id(row) in winners]
    superseded = [row for row in index if id(row) not in winners]
    return kept, superseded


def route_book_for_version(task: str, version: str) -> rr.RouteBook:
    """Load the exact frozen book named by a run environment, not CURRENT.

    The version also fixes the answer shape (rr.response_contract), so a v1
    reply is always re-checked as a v1 reply.
    """
    if not version:
        raise rr.Refuse("the run environment names no promptbook version")
    return rr.resolve_route_book(task, root=ROOT, version=version)


def promptbook_context_for_version(task: str, version: str) -> tuple[str, str, dict[str, set[str]]]:
    """(version, hashed promptbook text, known rule IDs) for one recorded run."""
    book = route_book_for_version(task, version)
    return book.version, book.promptbook, book.known_rules


def locate_raw_dir(task: str, round_no: int, version: str | None) -> Path:
    """Find one versioned run, retaining pre-versioning directories as legacy."""
    legacy = RAW_ROOT / f"{task}_r{round_no}"
    versioned = list(RAW_ROOT.glob(f"{task}_v*_r{round_no}"))
    if version:
        requested = RAW_ROOT / f"{task}_{version}_r{round_no}"
        if requested.is_dir():
            return requested
        if legacy.is_dir():
            environment = rr.load_run_environment(legacy / "run_environment.json")
            if environment.get("promptbook_version") == version:
                return legacy
        raise rr.Refuse(f"no {task} round {round_no} raw run for promptbook {version}")
    candidates = ([legacy] if legacy.is_dir() else []) + versioned
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise rr.Refuse(f"no raw run found for {task} round {round_no}")
    raise rr.Refuse(f"multiple raw runs match {task} round {round_no}; pass --promptbook-version")


def write_checked(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CHECKED_COLUMNS,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def snapshot_id(index: list[dict]) -> str:
    """Stable identity for exactly the latest raw evidence being written."""
    rows = [{key: row.get(key, "") for key in
             ("paper_id", "token", "attempt", "exit_code", "raw_path")}
            for row in index]
    return rr.sha256_text(json.dumps(rows, sort_keys=True, separators=(",", ":")))


def load_receipts(path: Path) -> dict:
    if not path.is_file():
        return {"snapshots": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise rr.Refuse(
            f"{path} is not valid JSON. Refusing a checker write because its "
            "duplicate-protection receipt cannot be trusted") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("snapshots"), dict):
        raise rr.Refuse(f"{path} has no valid snapshots mapping; refusing duplicate-risk write")
    return payload


def write_receipt(path: Path, receipts: dict, *, snapshot: str, pass_name: str,
                  judgments: int, ledger_rows: int) -> None:
    """Atomically record a successful checker write for duplicate protection."""
    receipts = {**receipts, "snapshots": dict(receipts["snapshots"])}
    receipts["snapshots"][snapshot] = {
        "written_at": now(), "pass_name": pass_name,
        "judgments": judgments, "ledger_rows": ledger_rows,
    }
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(receipts, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
    partial.replace(path)


def retry_fields(*, attempt: int, failure_kind: str) -> dict[str, str]:
    """Return checker-visible retry/terminal metadata without inventing a call."""
    retryable = failure_kind in rr.RETRYABLE_FAILURE_KINDS
    eligible = retryable and attempt < rr.MAX_ATTEMPTS
    return {
        "retry_eligible": "yes" if eligible else "no",
        "terminal_status": (rr.TERMINAL_REVIEW_REQUIRED
                            if retryable and not eligible else ""),
    }


def failure_record(record: dict, row: dict, *, kind: str, detail: str,
                   case: str = "") -> dict:
    """Mark one raw response failed and attach resume-safe metadata."""
    record.update({"status": "failed", "failure_kind": kind,
                   "failure_case": case, "detail": detail[:400]})
    record.update(retry_fields(attempt=rr.attempt_number(row), failure_kind=kind))
    return record


def ledger_row(record: dict, row: dict) -> dict:
    """Map a checked record to its one append-only ledger row."""
    return {
        "timestamp": now(), "task": record["task"], "round": record["round"],
        "paper_id": record["paper_id"], "token": record["token"],
        "attempt": record["attempt"],
        "outcome": "ok" if record["status"] == "ok" else "failure",
        "failure_kind": record.get("failure_kind", ""),
        "detail": record.get("detail", "")[:400],
        "exit_code": row.get("exit_code", ""),
        "duration_seconds": row.get("duration_seconds", ""),
        "raw_path": record["raw_path"],
        "retry_eligible": record.get("retry_eligible", ""),
        "terminal_status": record.get("terminal_status", ""),
    }


def task_decisions(record: dict) -> dict[str, schemas.Decision]:
    """Internal parsed decisions attached to a passed checker record."""
    return record["_task_decisions"]


def add_legacy_decision_fields(record: dict, decision: schemas.Decision) -> None:
    record.update({
        "decision": decision.decision, "confidence": decision.confidence,
        "reasoning": decision.reasoning,
        "promptbook_evidence": decision.promptbook_evidence,
        "cited_rules": ";".join(decision.cited_rules()),
    })


def add_combined_decision_fields(record: dict,
                                 decisions: dict[str, schemas.Decision]) -> None:
    for task, decision in decisions.items():
        prefix = "power" if task == "power_analysis" else "data"
        record.update({
            f"{prefix}_decision": decision.decision,
            f"{prefix}_confidence": decision.confidence,
            f"{prefix}_reasoning": decision.reasoning,
            f"{prefix}_promptbook_evidence": decision.promptbook_evidence,
            f"{prefix}_cited_rules": ";".join(decision.cited_rules()),
        })


def add_answer_fields(record: dict, answer) -> None:
    """Report the ground-truth extras; nothing for a legacy (v0/v1) reply."""
    if answer is None:
        return
    if isinstance(answer, schemas.ExclusionWithReason):
        record["exclusion_reason"] = answer.exclusion_reason or ""
    record["other_labels"] = "; ".join(
        f"{field}={label}" for field, label in schemas.other_labels(answer))


def answer_row(record: dict, *, response_id: str, run_id: str, route: str,
               version: str) -> dict | None:
    """The `structured_answers` row for one passed record, if it has an answer."""
    answer = record.get("_answer")
    if answer is None:
        return None
    payload = answer.model_dump(exclude={"paper_id"})
    return {"response_id": response_id, "run_id": run_id,
            "paper_id": record["paper_id"], "route": route,
            "schema_name": type(answer).__name__, "promptbook_version": version,
            "answer": payload}


def other_label_rows(passed: list[dict], *, route: str, round_no: int,
                     version: str, skip: set[tuple[str, int]]) -> list[dict]:
    """One log row per `other: <label>` in the answers just written."""
    stamp = now()
    rows = []
    for record in passed:
        answer = record.get("_answer")
        if answer is None or (record["paper_id"], record["attempt"]) in skip:
            continue
        for field, label in schemas.other_labels(answer):
            rows.append({"timestamp": stamp, "route": route, "round": round_no,
                         "promptbook_version": version, "paper_id": record["paper_id"],
                         "attempt": record["attempt"], "field": field, "label": label,
                         "raw_path": record["raw_path"]})
    return rows


def append_other_labels(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.is_file()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OTHER_LABEL_COLUMNS)
        if new:
            writer.writeheader()
        writer.writerows(rows)


def persist_passed(*, passed: list[dict], environment: dict,
                   environment_path: Path, route: str, version: str,
                   pass_name: str) -> tuple[int, set[tuple[str, int]]]:
    """Register provenance and atomically persist every accepted task decision.

    Combined responses contribute two entries to one SQLite savepoint. Every
    record has already passed both semantic checks before it reaches this
    function, and the DB unique response/task key catches a crash-replay even
    if the checker receipt was lost.
    """
    conn = db.connect()
    already_written: set[tuple[str, int]] = set()
    try:
        run_id = db.register_run_environment(
            conn, environment, source_path=environment_path,
            transport="reading_room", route=route)
        inserts: list[dict] = []
        answers: list[dict] = []
        for record in passed:
            metadata = dict(record.get("_provenance") or {})
            response_id = db.response_id_for_attempt(
                run_id=run_id, paper_id=record["paper_id"],
                attempt=record["attempt"],
                provider_response_id=metadata.get("request_id"))
            db.register_response(
                conn, response_id=response_id, run_id=run_id,
                paper_id=record["paper_id"], attempt=record["attempt"],
                provider_response_id=metadata.get("request_id"),
                raw_path=record["raw_path"], status="accepted",
                metadata=metadata)
            existing = db.response_judgment_tasks(conn, response_id)
            if existing:
                expected = set(task_decisions(record))
                if set(existing) != expected:
                    raise rr.Refuse(
                        f"response {response_id} already has different persisted task judgment(s) "
                        f"{list(existing)}")
                if (record.get("_answer") is not None
                        and not db.structured_answer_exists(conn, response_id)):
                    raise rr.Refuse(
                        f"response {response_id} has judgments but no stored full "
                        "answer; refusing to guess how it was half-written")
                already_written.add((record["paper_id"], record["attempt"]))
                continue
            row = answer_row(record, response_id=response_id, run_id=run_id,
                             route=route, version=version)
            if row is not None:
                answers.append(row)
            for task, decision in task_decisions(record).items():
                inserts.append({
                    "paper_id": record["paper_id"], "task": task,
                    "pass_name": pass_name,
                    "model_used": record.get("model_used") or environment["model"],
                    "decision": decision.decision,
                    "reasoning": decision.reasoning,
                    "promptbook_evidence": decision.promptbook_evidence,
                    "confidence": decision.confidence,
                    "promptbook_version": version,
                    "run_id": run_id, "response_id": response_id,
                })
        db.insert_judgments_atomically(conn, inserts, answers)
        return len(inserts), already_written
    finally:
        conn.close()


def print_summary(*, route: str, passed: list[dict], failures: list[dict],
                  confidences: dict[str, list[float]], show: int) -> None:
    print(f"\n  passed     : {len(passed)}")
    print(f"  failed     : {len(failures)}")
    if failures:
        for kind, count in Counter(r["failure_kind"] for r in failures).items():
            cases = Counter(r.get("failure_case") or "-"
                            for r in failures if r["failure_kind"] == kind)
            detail = ", ".join(f"{case}x{count}" for case, count in cases.items())
            print(f"      {kind:<10} {count:>3}   ({detail})")
        terminal = [record for record in failures
                    if record.get("terminal_status") == rr.TERMINAL_REVIEW_REQUIRED]
        if terminal:
            print(f"  review req.: {len(terminal)} exhausted {rr.MAX_ATTEMPTS} attempts "
                  "(no judgment was fabricated)")

    fenced = sum(1 for record in passed if record["was_fenced"])
    if fenced:
        print(f"  fenced     : {fenced} reply/replies arrived in a ``` fence "
              "(stripped; track rising format drift)")
    flagged = [record for record in passed if record.get("flagged_other_papers")]
    if flagged:
        print(f"  E12 flags  : {len(flagged)} reply/replies name another paper "
              "-- for human review, not rejected")
        for record in flagged[:show]:
            print(f"      {record['paper_id']}: {record['flagged_other_papers']}")

    labelled = [record for record in passed if record.get("other_labels")]
    if labelled:
        print(f"  other-label: {len(labelled)} reply/replies used 'other: <label>' "
              "-- logged on --write; promote a label only when it recurs")
        for record in labelled[:show]:
            print(f"      {record['paper_id']}: {record['other_labels']}")

    for task, values in confidences.items():
        if route == rr.COMBINED_ANALYSIS_ROUTE:
            decisions = Counter(task_decisions(record)[task].decision for record in passed)
            undecidable = sum(1 for record in passed
                              if task_decisions(record)[task].decision == "undecidable")
            print(f"\n  {task} decisions  : {dict(decisions)}")
        else:
            decisions = Counter(record["decision"] for record in passed)
            undecidable = sum(1 for record in passed if record["decision"] == "undecidable")
            print(f"\n  decisions  : {dict(decisions)}")
        print(f"  {task} undecidable: {undecidable}/{len(passed)} "
              f"({undecidable / len(passed):.1%})")
        distinct = sorted(set(values))
        if distinct:
            print(f"  {task} confidence : {len(distinct)} distinct value(s), "
                  f"{min(distinct):.2f}-{max(distinct):.2f}")

    for record in failures[:show]:
        print(f"\n  --- {record['paper_id']} [{record.get('failure_case')}] ---")
        print(f"      {record['detail']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Reading Room round and write its judgments.")
    parser.add_argument("--task", required=True, choices=rr.READING_ROOM_ROUTES)
    parser.add_argument("--round", required=True, type=int)
    parser.add_argument("--promptbook-version",
                        help="Select a versioned raw run when a round has more than one")
    parser.add_argument("--write", action="store_true",
                        help="Atomically insert accepted judgments and ledger rows")
    parser.add_argument("--pass-name", default=db.PASS_PRIMARY,
                        choices=[db.PASS_PRIMARY, db.PASS_REVIEW])
    parser.add_argument("--show", type=int, default=3,
                        help="Print the first N failures in full")
    args = parser.parse_args()

    bar = "=" * 74
    raw_dir = locate_raw_dir(args.task, args.round, args.promptbook_version)
    index = read_csv(raw_dir / "index.csv")
    if not index:
        raise rr.Refuse(f"{raw_dir / 'index.csv'} is empty: nothing to check")
    index, superseded = latest_attempt_per_paper(index)
    environment_path = raw_dir / "run_environment.json"
    environment = rr.load_run_environment(environment_path)
    book = route_book_for_version(
        args.task, str(environment.get("promptbook_version") or ""))
    version, promptbook, known_rules = book.version, book.promptbook, book.known_rules
    if environment.get("promptbook_sha256") != rr.sha256_text(promptbook):
        raise rr.Refuse(
            f"the promptbook text for {args.task} changed since this round ran "
            "(sha256 differs from run_environment.json). Restore the frozen "
            "version or re-run the round (DC53/G11)")

    real_ids = set(rr.load_verdicts())
    rule_count = sum(len(rules) for rules in known_rules.values())
    print(f"{bar}\nCHECK RESPONSES -- {args.task} round {args.round}\n{bar}")
    print(f"  promptbook : {version} ({rule_count} rules, {book.contract} answer shape)")
    print(f"  responses  : {len(index)}")
    if superseded:
        print(f"  superseded : {len(superseded)} earlier attempt(s) ignored "
              "(latest raw response per paper; evidence kept on disk)")
    print(f"  ran under  : {environment.get('model')} / effort "
          f"{environment.get('effort')} / CLI {environment.get('claude_code_version')} "
          f"/ commit {str(environment.get('git_commit'))[:12]}")

    checked: list[dict] = []
    fatal: list[str] = []
    versions: list[str] = []

    for row in index:
        paper_id, token = row["paper_id"], row["token"]
        raw_path = ROOT / row["raw_path"]
        record = {
            "paper_id": paper_id, "token": token, "task": args.task,
            "round": args.round, "raw_path": row["raw_path"],
            "attempt": rr.attempt_number(row), "was_fenced": False,
            "status": "ok", "retry_eligible": "", "terminal_status": "",
            "model_used": row.get("model") or environment.get("model", rr.MODEL),
        }

        # A non-zero exit never reached a checker-visible assistant reply. The
        # runner owns its ledger row; the checked report makes it resume-visible.
        if str(row.get("exit_code") or "") != "0":
            checked.append(failure_record(
                record, row, kind=rr.FAILURE_PROCESS,
                detail=f"exit code {row.get('exit_code')}"))
            continue
        if not raw_path.is_file():
            checked.append(failure_record(
                record, row, kind=rr.FAILURE_PROCESS,
                detail=f"raw response file is missing: {raw_path}"))
            continue

        stream_text = raw_path.read_text(encoding="utf-8", errors="replace")
        try:
            rr.scan_stream_for_tools(stream_text, paper=paper_id)
        except rr.RoundDiscarded as exc:
            fatal.append(str(exc))
            checked.append(failure_record(record, row, kind="FATAL",
                                          detail=str(exc), case="A1/A2"))
            continue

        try:
            rr.check_paper_provenance(stream_text, paper=paper_id,
                                      model=environment.get("model", rr.MODEL))
        except rr.RoundDiscarded as exc:
            fatal.append(str(exc))
            checked.append(failure_record(record, row, kind="FATAL",
                                          detail=str(exc), case="G3/G8/G12"))
            continue
        except rr.SemanticFailure as exc:
            kind = (rr.FAILURE_TRUNCATION if exc.case == "G9"
                    else rr.FAILURE_INCOMPLETE)
            checked.append(failure_record(record, row, kind=kind,
                                          detail=str(exc), case=exc.case))
            continue
        versions.append(rr.paper_provenance(stream_text).get("claude_code_version"))

        reply = rr.assistant_text(stream_text)
        try:
            rr.check_no_real_paper_ids(reply, token, real_ids)
        except rr.RoundDiscarded as exc:
            fatal.append(str(exc))
            checked.append(failure_record(record, row, kind="FATAL",
                                          detail=str(exc), case="E11"))
            continue

        try:
            checked_reply = rr.parse_and_check_reply(reply, book=book, token=token)
            decisions, was_fenced = checked_reply.decisions, checked_reply.was_fenced
            if args.task == rr.COMBINED_ANALYSIS_ROUTE:
                add_combined_decision_fields(record, decisions)
            else:
                add_legacy_decision_fields(record, decisions[args.task])
            add_answer_fields(record, checked_reply.answer)
        except schemas.ParseFailure as exc:
            checked.append(failure_record(record, row, kind=rr.FAILURE_PARSE,
                                          detail=str(exc), case="D"))
            continue
        except rr.RoundDiscarded as exc:
            fatal.append(str(exc))
            checked.append(failure_record(record, row, kind="FATAL",
                                          detail=str(exc), case="E9"))
            continue
        except rr.SemanticFailure as exc:
            checked.append(failure_record(record, row, kind=rr.FAILURE_SEMANTIC,
                                          detail=str(exc), case=exc.case))
            continue

        record.update({
            "was_fenced": was_fenced,
            "flagged_other_papers": ";".join(rr.flag_other_papers(reply)),
            "_task_decisions": decisions,
            "_answer": checked_reply.answer,
            "_provenance": rr.paper_provenance(stream_text),
        })
        checked.append(record)

    passed = [record for record in checked if record["status"] == "ok"]
    try:
        rr.check_round_provenance(versions)
    except rr.RoundDiscarded as exc:
        fatal.append(str(exc))

    confidences: dict[str, list[float]] = {
        task: [task_decisions(record)[task].confidence for record in passed]
        for task in (schemas.ANALYSIS_TASKS if args.task == rr.COMBINED_ANALYSIS_ROUTE
                     else (args.task,))
    }
    for task, values in confidences.items():
        if rr.constant_confidence(values):
            fatal.append(
                f"every one of the {len(values)} {task} judgments returned "
                f"confidence={values[0]}. That is a template, not a judgment (E8)")

    # Match the raw directory identity: future versions of the same task/round
    # must not overwrite this checker report. Legacy raw runs retain their
    # legacy checked filename.
    out = RESULTS / "checked" / f"{raw_dir.name}.csv"
    write_checked(out, checked)
    failures = [record for record in checked if record["status"] == "failed"]
    print_summary(route=args.task, passed=passed, failures=failures,
                  confidences=confidences, show=args.show)
    print(f"\n  report -> {out.relative_to(ROOT)}")

    if fatal:
        print(f"\n{bar}\nROUND DISCARDED\n{bar}")
        for message in fatal[:5]:
            print(f"  {message}")
        print("\n  Nothing was written to the database or retry ledger. Raw files "
              "and the checked report remain as evidence.")
        return 2

    # The runner already filed non-zero process failures, because there is no
    # reply for this checker to validate. Every clean raw response gets exactly
    # one final ledger row here: accepted, retryable failure, or review-required.
    ledger_rows = [ledger_row(record, row)
                   for record, row in zip(checked, index)
                   if record.get("failure_kind") != rr.FAILURE_PROCESS]
    if not args.write:
        task_count = sum(len(task_decisions(record)) for record in passed)
        print(f"\n  Nothing written -- not the database or retry ledger. Re-run "
              f"with --write to insert {task_count} judgment(s) and file "
              f"{len(ledger_rows)} final ledger row(s).")
        return 0

    snapshot = snapshot_id(index)
    receipt_path = raw_dir / WRITE_RECEIPTS
    receipts = load_receipts(receipt_path)
    if snapshot in receipts["snapshots"]:
        prior = receipts["snapshots"][snapshot]
        raise rr.Refuse(
            f"this exact raw snapshot was already written at {prior.get('written_at')}; "
            "refusing duplicate judgment/ledger insertion")

    inserted, already_written = persist_passed(
        passed=passed, environment=environment, environment_path=environment_path,
        route=args.task, version=version, pass_name=args.pass_name)
    ledger_rows = [row for row in ledger_rows
                   if (row["paper_id"], rr.attempt_number(row)) not in already_written]
    if ledger_rows:
        rr.append_ledger(LEDGER, ledger_rows)
    label_rows = other_label_rows(passed, route=args.task, round_no=args.round,
                                  version=version, skip=already_written)
    append_other_labels(OTHER_LABELS, label_rows)
    if label_rows:
        print(f"  logged {len(label_rows)} other-label(s) -> "
              f"{OTHER_LABELS.relative_to(ROOT)}")
    write_receipt(receipt_path, receipts, snapshot=snapshot,
                  pass_name=args.pass_name, judgments=inserted,
                  ledger_rows=len(ledger_rows))
    print(f"\n  wrote {inserted} judgment(s) to data/review.db "
          f"(promptbook {version}, pass {args.pass_name})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except rr.Refuse as exc:
        print(f"\nREFUSED: {exc}")
        sys.exit(1)
