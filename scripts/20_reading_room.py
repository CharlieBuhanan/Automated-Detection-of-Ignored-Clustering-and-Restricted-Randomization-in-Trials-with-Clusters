"""Run one promptbook round inside the Reading Room. Spawns `claude -p`, saves raw.

WHAT IT DOES
    Hands one paper to one sealed `claude -p` process, blinded, with no tools and
    no way to reach this repo, and saves whatever comes back verbatim. It does
    NOT score anything -- `21_check_responses.py` does that, so a parsing bug can
    never destroy the evidence it was parsing.

QUICK START
    # See exactly what would run. Costs nothing, spawns nothing.
    python scripts/20_reading_room.py --task exclusion --round 1 --dry-run

    # Two papers, to prove the walls hold before spending a round.
    python scripts/20_reading_room.py --task exclusion --round 1 --limit 2

    # The real thing.
    python scripts/20_reading_room.py --task exclusion --round 1
    python scripts/21_check_responses.py --task exclusion --round 1

    Then re-run the WHOLE build split before reading any accuracy number -- the
    Human Labelled Set is the regression suite, not just the latest batch.

FLAGS YOU WILL ACTUALLY USE
    --task      exclusion | power_analysis | data_analysis   (required)
    --round     round number from build_rounds.csv           (required)
    --dry-run   plan only: resolve the round, check every wall, spawn nothing
    --limit N   first N papers only. For smoke tests
    --resume    skip papers that already have a successful raw file (F4)
    --force     re-run a round that already has raw files (F5). Off by default
                because re-running double-inserts judgments
    --claude    path to the CLI, if it is not on PATH (F11)
    --workers   concurrent papers, default 6. One paper per process, always
    --model     override the pinned model. You almost never want this

WHERE THINGS LAND
    results/04_classification/raw/<task>_r<round>/
        <token>.attempt<N>.jsonl    the verbatim stream-json, the evidence
        index.csv                   token -> paper_id, the deblinding key
        run_log.csv                 one row per paper: text notes, timing, exit
    results/04_classification/retry_ledger.csv    one row per ATTEMPT (DC24)

    The index is the ONLY thing that maps a token back to a paper. The model
    never sees it. Do not delete it -- without it the raw files are anonymous.

WHAT MAKES IT REFUSE
    Anything in test-plan groups A and B: a wall that would not hold, a holdout
    paper in the round, a paper with no cached text, a promptbook that does not
    exist. Every refusal happens BEFORE the first process is spawned, so a setup
    error costs nothing. See ReadingRoom/tests/TEST_PLAN.md.

WHAT MAKES IT DISCARD THE ROUND
    A `tool_use` or `tool_result` block in any response stream. That means the
    room was not sealed, and every paper in the round ran under the same
    conditions -- so none of them is evidence of anything (A1/A2).
"""

import argparse
import csv
import io
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import db                                              # noqa: E402
import reading_room as rr                              # noqa: E402

RESULTS = ROOT / "results" / "04_classification"
RAW_ROOT = RESULTS / "raw"
LEDGER = RESULTS / "retry_ledger.csv"

INDEX_COLUMNS = ["paper_id", "token", "task", "round", "promptbook_version",
                 "model", "attempt", "exit_code", "duration_seconds",
                 "raw_path", "started_at"]
RUN_LOG_COLUMNS = ["paper_id", "token", "task", "round", "stratum", "chars",
                   "text_notes", "outcome", "detail", "duration_seconds"]

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one promptbook round in the sealed Reading Room.")
    parser.add_argument("--task", required=True, choices=db.TASKS)
    parser.add_argument("--round", required=True, type=int)
    parser.add_argument("--dry-run", action="store_true",
                        help="Resolve the round and check every wall; spawn nothing")
    parser.add_argument("--limit", type=int, help="First N papers only")
    parser.add_argument("--resume", action="store_true",
                        help="Skip papers that already have a successful raw file")
    parser.add_argument("--force", action="store_true",
                        help="Re-run a round that already has raw files (F5)")
    parser.add_argument("--claude", default="claude", help="Path to the CLI")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--model", default=rr.MODEL)
    parser.add_argument("--timeout", type=int, default=rr.TIMEOUT_SECONDS)
    args = parser.parse_args()

    raw_dir = RAW_ROOT / f"{args.task}_r{args.round}"
    bar = "=" * 74

    # ---------------------------------------------------------------- resolve
    # Everything that can refuse, refuses here -- before a process exists.
    version, book_path, promptbook = rr.resolve_promptbook(args.task, root=ROOT)

    conn = db.connect()
    try:
        labels = rr.load_labels(conn)
    finally:
        conn.close()
    verdicts = rr.load_verdicts()

    plan = rr.load_round(args.task, args.round, labels=labels, verdicts=verdicts)

    print(f"{bar}\nREADING ROOM -- {args.task} round {args.round}\n{bar}")
    print(f"  promptbook   : {version}  ({book_path.relative_to(ROOT)})")
    print(f"  model        : {args.model}")
    print(f"  papers       : {plan.n}"
          + (f"  (nominal {rr.ROUND_SIZE}; short rounds are proceeded with, "
             f"never re-cut -- DC47)" if plan.n != rr.ROUND_SIZE else ""))
    for paper_id, why in plan.skipped:
        print(f"    skipped {paper_id}: {why}")

    papers = plan.papers

    # F5. Re-running double-inserts judgments, so it takes a flag.
    existing = read_csv(raw_dir / "index.csv")
    if existing and not (args.force or args.resume):
        print(f"\n  !! {raw_dir.relative_to(ROOT)} already holds {len(existing)} "
              f"response(s).\n     Re-running would double-insert judgments (F5). "
              f"Use --resume to fill gaps, or --force to re-run from scratch.")
        return 1

    done = {r["paper_id"] for r in existing if r.get("exit_code") == "0"}
    if args.resume and done:
        papers = [p for p in papers if p.paper_id not in done]
        print(f"  --resume     : {len(done)} already done, {len(papers)} to go")

    if args.limit:
        papers = papers[:args.limit]
        print(f"  --limit      : first {len(papers)} paper(s) only")

    # ------------------------------------------------- load and clean the text
    # Done before any spawn so C3 (a paper over the cap) refuses for free.
    prepared, text_problems = [], []
    for paper in papers:
        body = rr.read_paper_text(paper.text_path)
        if body.is_empty:                                               # C1/C2
            text_problems.append((paper, body))
            continue
        prepared.append((paper, body))

    for paper, body in text_problems:
        print(f"    no text  {paper.paper_id}: {rr.NO_TEXT_REASON}")

    if not args.dry_run:
        rr.find_claude(args.claude)                                     # F11

    if args.dry_run:
        print(f"\n  --dry-run: every wall checked, {len(prepared)} paper(s) would "
              f"be sent, nothing spawned.")
        total = sum(b.chars for _, b in prepared)
        print(f"  total text: {total:,} chars "
              f"(~{total // 3:,} tokens at 3 chars/token)")
        return 0

    # ----------------------------------------------------------------- the run
    room = rr.prepare_room(repo_root=ROOT)
    print(f"  room         : {room.root}")

    # One throwaway spawn before the round. Both failures the first live run hit
    # -- a stale deny-list name and credentials the room could not see -- break
    # every paper identically, so finding them on paper 1 of 50 wastes 49.
    offered = rr.preflight(room, model=args.model, claude=args.claude,
                           repo_root=ROOT)
    print(f"  preflight    : logged in, {len(offered)} tools offered "
          f"(the room is empty)")
    print(f"  workers      : {args.workers}\n{bar}")

    index_rows, log_rows, ledger_rows = list(existing), [], []
    fatal: list[str] = []

    def one_paper(paper, body):
        token = rr.new_token(body.text)
        prompt = rr.build_prompt(promptbook=promptbook, token=token,
                                 text=body.text, task=args.task)
        attempt = rr.run_paper(prompt, room=room, token=token,
                               paper_id=paper.paper_id, model=args.model,
                               claude=args.claude, timeout=args.timeout,
                               repo_root=ROOT)
        attempt.raw_path = rr.write_raw(attempt, raw_dir)
        return paper, body, attempt

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(one_paper, paper, body): paper
                   for paper, body in prepared}
        for i, future in enumerate(as_completed(futures), 1):
            paper = futures[future]
            try:
                paper, body, attempt = future.result()
            except rr.Refuse as exc:
                print(f"  [{i:>3}/{len(prepared)}] REFUSE {paper.paper_id}: {exc}")
                log_rows.append({"paper_id": paper.paper_id, "task": args.task,
                                 "round": args.round, "outcome": "refused",
                                 "detail": str(exc)})
                continue

            # A1/A2 and A5, on every response, before anything else looks at it:
            # no tool was called, and none was even offered.
            try:
                rr.scan_stream_for_tools(attempt.stdout, paper=paper.paper_id)
                rr.assert_no_tools_offered(attempt.stdout, paper=paper.paper_id)
                sealed = True
            except rr.RoundDiscarded as exc:
                sealed = False
                fatal.append(str(exc))

            outcome = "ok" if attempt.ok else "process_failure"
            if not sealed:
                outcome = "TOOL_USE"
            detail = "" if attempt.ok else attempt.stderr.strip()[:200]

            print(f"  [{i:>3}/{len(prepared)}] {outcome:<15} {paper.paper_id} "
                  f"{attempt.duration:>6.1f}s  {body.chars:>7,} chars"
                  + (f"  [{body.notes}]" if body.notes else ""))

            index_rows.append({
                "paper_id": paper.paper_id, "token": attempt.token,
                "task": args.task, "round": args.round,
                "promptbook_version": version, "model": args.model,
                "attempt": attempt.attempt, "exit_code": attempt.exit_code,
                "duration_seconds": attempt.duration,
                "raw_path": str(attempt.raw_path.relative_to(ROOT)),
                "started_at": now()})
            log_rows.append({
                "paper_id": paper.paper_id, "token": attempt.token,
                "task": args.task, "round": args.round, "stratum": paper.stratum,
                "chars": body.chars, "text_notes": body.notes,
                "outcome": outcome, "detail": detail,
                "duration_seconds": attempt.duration})
            ledger_rows.append({
                "timestamp": now(), "task": args.task, "round": args.round,
                "paper_id": paper.paper_id, "token": attempt.token,
                "attempt": attempt.attempt,
                "outcome": "ok" if attempt.ok else "failure",
                "failure_kind": "" if attempt.ok else rr.FAILURE_PROCESS,
                "detail": detail, "exit_code": attempt.exit_code,
                "duration_seconds": attempt.duration,
                "raw_path": str(attempt.raw_path.relative_to(ROOT))})

    # C1/C2 papers never reached the CLI; they still need a row, or the round's
    # denominator quietly shrinks.
    for paper, body in text_problems:
        log_rows.append({"paper_id": paper.paper_id, "task": args.task,
                         "round": args.round, "stratum": paper.stratum,
                         "chars": 0, "text_notes": body.notes,
                         "outcome": "no_text", "detail": rr.NO_TEXT_REASON})

    write_csv(raw_dir / "index.csv", INDEX_COLUMNS, index_rows)
    write_csv(raw_dir / "run_log.csv", RUN_LOG_COLUMNS, log_rows)
    rr.append_ledger(LEDGER, ledger_rows)

    print(f"{bar}")
    if fatal:
        print(f"ROUND DISCARDED -- the room was not sealed\n{bar}")
        for message in fatal[:5]:
            print(f"  {message}")
        print(f"\n  {len(fatal)} paper(s) used a tool. Every paper in this round "
              f"ran under\n  the same conditions, so none of them is evidence of "
              f"anything.\n  Raw files are kept as evidence. Do NOT score this "
              f"round (A1/A2).")
        return 2

    ok = sum(1 for r in log_rows if r["outcome"] == "ok")
    print(f"DONE -- {ok}/{len(log_rows)} responses saved\n{bar}")
    print(f"  raw     -> {raw_dir.relative_to(ROOT)}")
    print(f"  ledger  -> {LEDGER.relative_to(ROOT)}")
    print(f"\n  Next: python scripts/21_check_responses.py --task {args.task} "
          f"--round {args.round}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except rr.Refuse as exc:
        print(f"\nREFUSED (nothing spent): {exc}")
        sys.exit(1)
    except rr.RoundDiscarded as exc:
        # Only reachable from preflight -- in the round itself these are
        # collected rather than raised, so every paper's evidence is saved.
        print(f"\nPREFLIGHT FAILED (nothing spent): {exc}")
        sys.exit(2)
