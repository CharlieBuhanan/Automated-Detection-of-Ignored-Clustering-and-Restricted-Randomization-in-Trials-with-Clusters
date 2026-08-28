"""Validate a round's raw responses, then write the judgments. Never scores blind.

WHAT IT DOES
    Reads the raw files `20_reading_room.py` saved and puts each one through the
    same ordered gauntlet, every step assuming the previous one passed:

        0.  collapse index.csv to the LATEST attempt per paper
        1.  exit code 0                        else -> retry ledger
        2.  ZERO tool_use / tool_result        else -> DISCARD THE WHOLE ROUND
        3.  JSON parses (note a ``` fence)
        4.  pydantic Decision validates        (src/schemas.py, both routes)
        5.  decision in the allowed set; wrong_text on exclusion only
        6.  reasoning <= 200 chars
        7.  promptbook_evidence cites a rule that EXISTS in the version in force
        8.  confidence in [0,1] AND not identical across the round
        9.  the blinded token echoes back unchanged
        10. resolve token -> paper_id, write the judgment

    Steps 2, 8, 9 and the real-paper_id check are ROUND-level. One failure there
    is not one bad paper -- it is evidence the walls had a hole, and every paper
    in the round ran under the same conditions.

QUICK START
    python scripts/21_check_responses.py --task exclusion --round 1            # report
    python scripts/21_check_responses.py --task exclusion --round 1 --write    # + db

    Nothing is written to `data/review.db` -- or to `retry_ledger.csv` -- without
    --write. Run it without the flag first; the report tells you what would land.

FLAGS
    --task / --round   which round's raw files to read (required)
    --write            insert the judgments into `judgments` (append-only, DC19)
    --pass-name        primary | review    (default primary)
    --show N           print the first N failures in full, with the raw text

WHAT IT DOES NOT DO
    It does not re-prompt. A paper that fails here is logged to the retry ledger
    with its failure kind, and `20_reading_room.py --resume` is what sends it
    again. Keeping the two apart means a bug in the checker can never cost money.

    It also does not compute accuracy. That is `evaluate.py`, against the labels,
    and it is deliberately downstream of everything here.
"""

import argparse
import csv
import io
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

CHECKED_COLUMNS = ["paper_id", "token", "task", "round", "status", "decision",
                   "confidence", "reasoning", "promptbook_evidence",
                   "cited_rules", "was_fenced", "failure_kind", "failure_case",
                   "detail", "flagged_other_papers", "raw_path"]

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise rr.Refuse(f"{path} does not exist. Run scripts/20_reading_room.py first")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def latest_attempt_per_paper(index: list[dict]) -> tuple[list[dict], list[dict]]:
    """Collapse the append-only index to the one attempt that counts per paper.

    `index.csv` is appended to, never rewritten, so after a `--resume` a paper's
    earlier failure still sits above its later success. Scoring every row reports
    the same paper twice -- once ok, once as a process failure -- and re-logs to
    the retry ledger a failure the rerun already cleared. That corrupts DC24's
    retry rate at the exact moment it is meant to be read, and DC24 is only
    meaningful if the ledger says which failures were real.

    "Latest" cannot key on `attempt` alone: nothing increments it (MAX_ATTEMPTS
    is defined but unused, so every row a resumed paper gets is `attempt 1`
    again). Append order is the real chronology, so file position is what breaks
    the tie -- with `attempt` and `started_at` ahead of it, so this keeps working
    unchanged the day a real retry loop starts numbering them.

    Returns (kept, superseded). The superseded rows are not discarded silently:
    main() prints the count, and the raw files behind them stay on disk.
    """
    best: dict[str, tuple[int, str, int]] = {}
    for position, row in enumerate(index):
        try:
            attempt = int(row.get("attempt") or 0)
        except (TypeError, ValueError):
            attempt = 0
        key = (attempt, row.get("started_at") or "", position)
        paper_id = row.get("paper_id", "")
        if paper_id not in best or key > best[paper_id]:
            best[paper_id] = key
    winners = {key[2] for key in best.values()}
    kept = [row for position, row in enumerate(index) if position in winners]
    superseded = [row for position, row in enumerate(index) if position not in winners]
    return kept, superseded


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Reading Room round and write its judgments.")
    parser.add_argument("--task", required=True, choices=db.TASKS)
    parser.add_argument("--round", required=True, type=int)
    parser.add_argument("--write", action="store_true",
                        help="Insert judgments into data/review.db")
    parser.add_argument("--pass-name", default=db.PASS_PRIMARY,
                        choices=[db.PASS_PRIMARY, db.PASS_REVIEW])
    parser.add_argument("--show", type=int, default=3,
                        help="Print the first N failures in full")
    args = parser.parse_args()

    bar = "=" * 74
    raw_dir = RAW_ROOT / f"{args.task}_r{args.round}"
    index = read_csv(raw_dir / "index.csv")
    if not index:
        raise rr.Refuse(f"{raw_dir / 'index.csv'} is empty: nothing to check")
    index, superseded = latest_attempt_per_paper(index)

    # G1, before anything is read: a round nobody can trace back to the model,
    # effort, CLI version and prompt hashes that produced it is not a reportable
    # result, so it is not scored at all.
    environment = rr.load_run_environment(raw_dir / "run_environment.json")

    version, _, promptbook = rr.resolve_promptbook(args.task, root=ROOT)
    known_rules = rr.promptbook_rule_ids(promptbook, args.task)

    # The promptbook in force now must be the one the round actually ran under,
    # or step 7 checks cited rules against the wrong rulebook.
    if environment.get("promptbook_version") != version:
        raise rr.Refuse(
            f"this round ran under promptbook "
            f"{environment.get('promptbook_version')!r} but promptbooks/CURRENT "
            f"now names {version!r}. Rule ids would be checked against a "
            f"rulebook the model never saw (G11)")
    if environment.get("promptbook_sha256") != rr.sha256_text(promptbook):
        raise rr.Refuse(
            f"promptbooks/{version}/{args.task}.md has changed since this round "
            f"ran (sha256 differs from run_environment.json). A version is "
            f"frozen once it has been run -- restore it or re-run the round "
            f"(DC53/G11)")

    # E11 needs the set of real identifiers the model was never given. The
    # manifest is the whole corpus, which is exactly the right net: a leak that
    # surfaced an unlabelled paper's key is still a leak.
    real_ids = set(rr.load_verdicts())

    print(f"{bar}\nCHECK RESPONSES -- {args.task} round {args.round}\n{bar}")
    print(f"  promptbook : {version} ({len(known_rules)} rules)")
    print(f"  responses  : {len(index)}")
    if superseded:
        print(f"  superseded : {len(superseded)} earlier attempt(s) ignored "
              f"(latest attempt per paper; raw files kept on disk)")
    print(f"  ran under  : {environment.get('model')} / effort "
          f"{environment.get('effort')} / CLI "
          f"{environment.get('claude_code_version')} / commit "
          f"{str(environment.get('git_commit'))[:12]}")

    checked, fatal, ledger_rows, versions = [], [], [], []

    for row in index:
        paper_id, token = row["paper_id"], row["token"]
        raw_path = ROOT / row["raw_path"]
        record = {"paper_id": paper_id, "token": token, "task": args.task,
                  "round": args.round, "raw_path": row["raw_path"],
                  "was_fenced": False, "status": "ok"}

        def fail(kind: str, detail: str, case: str = "") -> dict:
            record.update({"status": "failed", "failure_kind": kind,
                           "failure_case": case, "detail": detail[:400]})
            ledger_rows.append({
                "timestamp": now(), "task": args.task, "round": args.round,
                "paper_id": paper_id, "token": token,
                "attempt": row.get("attempt", 1), "outcome": "failure",
                "failure_kind": kind, "detail": detail[:400],
                "exit_code": row.get("exit_code", ""),
                "duration_seconds": row.get("duration_seconds", ""),
                "raw_path": row["raw_path"]})
            return record

        # 1. exit code
        if str(row.get("exit_code")) != "0":
            checked.append(fail(rr.FAILURE_PROCESS,
                                f"exit code {row.get('exit_code')}"))
            continue

        stream_text = raw_path.read_text(encoding="utf-8", errors="replace") \
            if raw_path.is_file() else ""

        # 2. the walls -- ROUND level
        try:
            rr.scan_stream_for_tools(stream_text, paper=paper_id)
        except rr.RoundDiscarded as exc:
            fatal.append(str(exc))
            checked.append(fail("FATAL", str(exc), case="A1/A2"))
            continue

        # 2b. provenance -- G3/G4/G8/G12 are round-level, G5/G6/G9 are retries.
        # Before parsing, because a truncated reply (G9) must be logged as a
        # truncation and not as the parse failure it would look like downstream.
        try:
            rr.check_paper_provenance(stream_text, paper=paper_id,
                                      model=environment.get("model", rr.MODEL))
        except rr.RoundDiscarded as exc:
            fatal.append(str(exc))
            checked.append(fail("FATAL", str(exc), case="G3/G8/G12"))
            continue
        except rr.SemanticFailure as exc:
            kind = (rr.FAILURE_TRUNCATION if exc.case == "G9"
                    else rr.FAILURE_INCOMPLETE)
            checked.append(fail(kind, str(exc), case=exc.case))
            continue
        versions.append(rr.paper_provenance(stream_text).get("claude_code_version"))

        reply = rr.assistant_text(stream_text)

        # E11 -- ROUND level. Checked on the whole reply, before parsing, so a
        # leaked identifier in prose the parser would discard still counts.
        try:
            rr.check_no_real_paper_ids(reply, token, real_ids)
        except rr.RoundDiscarded as exc:
            fatal.append(str(exc))
            checked.append(fail("FATAL", str(exc), case="E11"))
            continue

        # 3-6. parse and validate. paper_id=None so a missing echo stays missing
        # (E10) instead of being helpfully filled in by the wrapper.
        try:
            decision, was_fenced = schemas.parse_decision(
                reply, task=args.task, paper_id=None)
        except schemas.ParseFailure as exc:
            checked.append(fail(rr.FAILURE_PARSE, str(exc), case="D"))
            continue
        record["was_fenced"] = was_fenced

        # 9. token echo -- ROUND level
        try:
            rr.check_token_echo(decision, token)
        except rr.RoundDiscarded as exc:
            fatal.append(str(exc))
            checked.append(fail("FATAL", str(exc), case="E9"))
            continue

        # 5-7, 10. semantic checks
        try:
            rr.check_decision(decision, task=args.task, token=token,
                              known_rules=known_rules)
        except rr.SemanticFailure as exc:
            checked.append(fail(rr.FAILURE_SEMANTIC, str(exc), case=exc.case))
            continue

        record.update({
            "decision": decision.decision, "confidence": decision.confidence,
            "reasoning": decision.reasoning,
            "promptbook_evidence": decision.promptbook_evidence,
            "cited_rules": ";".join(decision.cited_rules()),
            "flagged_other_papers": ";".join(rr.flag_other_papers(reply)),  # E12
        })
        ledger_rows.append({
            "timestamp": now(), "task": args.task, "round": args.round,
            "paper_id": paper_id, "token": token, "attempt": row.get("attempt", 1),
            "outcome": "ok", "failure_kind": "", "detail": "",
            "exit_code": row.get("exit_code", ""),
            "duration_seconds": row.get("duration_seconds", ""),
            "raw_path": row["raw_path"]})
        checked.append(record)

    passed = [r for r in checked if r["status"] == "ok"]

    # G2 -- ROUND level. The CLI auto-updates; a round that straddled one ran
    # its early and late papers under two different programs.
    try:
        rr.check_round_provenance(versions)
    except rr.RoundDiscarded as exc:
        fatal.append(str(exc))

    # 8. constant confidence -- ROUND level, and only computable now.
    confidences = [r["confidence"] for r in passed]
    if rr.constant_confidence(confidences):
        fatal.append(
            f"every one of the {len(confidences)} judgments returned "
            f"confidence={confidences[0]}. That is a template, not a judgment "
            f"-- the model has stopped reading (E8)")

    # ------------------------------------------------------------------ report
    out = RESULTS / "checked" / f"{args.task}_r{args.round}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CHECKED_COLUMNS,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(checked)
    # DC24. The ledger is append-only, and this script has no way to recognise a
    # row it wrote on an earlier run -- so an ungated append means every repeat
    # of the *report* silently re-files the same 49 attempts. That does not just
    # bloat the file: the retry rate is failures/attempts, so each extra report
    # run inflates the denominator and quietly understates the very number the
    # ledger exists to produce. Report mode is therefore read-only, exactly like
    # `data/review.db` is, and the ledger is written only by the run that also
    # lands the judgments.
    if args.write:
        rr.append_ledger(LEDGER, ledger_rows)

    failures = [r for r in checked if r["status"] == "failed"]
    print(f"\n  passed     : {len(passed)}")
    print(f"  failed     : {len(failures)}")
    if failures:
        for kind, count in Counter(r["failure_kind"] for r in failures).items():
            cases = Counter(r.get("failure_case") or "-"
                            for r in failures if r["failure_kind"] == kind)
            detail = ", ".join(f"{c}x{n}" for c, n in cases.items())
            print(f"      {kind:<10} {count:>3}   ({detail})")
    fenced = sum(1 for r in passed if r["was_fenced"])
    if fenced:
        print(f"  fenced     : {fenced} reply/replies arrived in a ``` fence "
              f"(stripped; a rising rate means the format instruction is losing)")
    flagged = [r for r in passed if r.get("flagged_other_papers")]
    if flagged:
        print(f"  E12 flags  : {len(flagged)} reply/replies name another paper "
              f"-- for human review, not rejected")
        for r in flagged[:args.show]:
            print(f"      {r['paper_id']}: {r['flagged_other_papers']}")

    if passed:
        print(f"\n  decisions  : "
              f"{dict(Counter(r['decision'] for r in passed))}")
        undecidable = sum(1 for r in passed if r["decision"] == "undecidable")
        print(f"  undecidable: {undecidable}/{len(passed)} "
              f"({undecidable / len(passed):.1%}) -- rising while accuracy holds "
              f"flat means the promptbook is teaching abstention")
        values = sorted(set(confidences))
        print(f"  confidence : {len(values)} distinct value(s), "
              f"{min(values):.2f}-{max(values):.2f}")

    for record in failures[:args.show]:
        print(f"\n  --- {record['paper_id']} [{record.get('failure_case')}] ---")
        print(f"      {record['detail']}")

    print(f"\n  report -> {out.relative_to(ROOT)}")

    if fatal:
        print(f"\n{bar}\nROUND DISCARDED\n{bar}")
        for message in fatal[:5]:
            print(f"  {message}")
        print("\n  Nothing written to the database. The raw files are kept as "
              "evidence.")
        return 2

    # -------------------------------------------------------------- 10. write
    if not args.write:
        print(f"\n  Nothing written -- not the database, not the retry "
              f"ledger. Re-run with --write to insert {len(passed)} "
              f"judgment(s) and file {len(ledger_rows)} ledger row(s).")
        return 0

    conn = db.connect()
    try:
        inserted = 0
        for record in passed:
            db.insert_judgment(
                conn, paper_id=record["paper_id"], task=args.task,
                pass_name=args.pass_name, model_used=index[0].get("model", rr.MODEL),
                decision=record["decision"], reasoning=record["reasoning"],
                promptbook_evidence=record["promptbook_evidence"],
                confidence=record["confidence"], promptbook_version=version)
            inserted += 1
    finally:
        conn.close()

    print(f"\n  wrote {inserted} judgment(s) to data/review.db "
          f"(promptbook {version}, pass {args.pass_name})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except rr.Refuse as exc:
        print(f"\nREFUSED: {exc}")
        sys.exit(1)
