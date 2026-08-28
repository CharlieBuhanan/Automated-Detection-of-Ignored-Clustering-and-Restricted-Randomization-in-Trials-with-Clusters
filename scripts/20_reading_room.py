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

    # Opt into one post-gate call returning both analysis judgments.
    python scripts/20_reading_room.py --task combined_analysis --round 1

    Then re-run the WHOLE build split before reading any accuracy number -- the
    Human Labelled Set is the regression suite, not just the latest batch.

FLAGS YOU WILL ACTUALLY USE
    --task      exclusion | power_analysis | data_analysis | combined_analysis
                combined_analysis is opt-in; the three legacy routes remain
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
RUN_LOG_COLUMNS = (["paper_id", "token", "task", "round", "stratum", "chars",
                    "text_notes", "outcome", "detail", "attempt", "exit_code",
                    "duration_seconds"]
                   + rr.PROVENANCE_COLUMNS)                          # group G

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
    parser.add_argument("--task", required=True, choices=rr.READING_ROOM_ROUTES)
    parser.add_argument("--round", required=True, type=int)
    parser.add_argument("--dry-run", action="store_true",
                        help="Resolve the round and check every wall; spawn nothing")
    parser.add_argument("--preflight-only", action="store_true",
                        help="Spawn ONLY the two-word probe, then stop. Re-checks "
                             "every live wall (login, A14 tools, A17 tokens) "
                             "after a config change, without spending a round")
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
    combined = args.task == rr.COMBINED_ANALYSIS_ROUTE
    if combined:
        version, book_paths, promptbooks = rr.resolve_combined_analysis_promptbooks(
            root=ROOT)
        promptbook_record = rr.combined_analysis_promptbook(
            power_analysis=promptbooks["power_analysis"],
            data_analysis=promptbooks["data_analysis"])
    else:
        version, book_path, promptbook = rr.resolve_promptbook(args.task, root=ROOT)
        promptbook_record = promptbook

    conn = db.connect()
    try:
        labels = rr.load_labels(conn)
    finally:
        conn.close()
    verdicts = rr.load_verdicts()

    if combined:
        plan = rr.load_combined_analysis_round(
            args.round, labels=labels, verdicts=verdicts)
    else:
        plan = rr.load_round(args.task, args.round, labels=labels, verdicts=verdicts)

    print(f"{bar}\nREADING ROOM -- {args.task} round {args.round}\n{bar}")
    if combined:
        print(f"  promptbooks  : {version}")
        for task in rr.schemas.ANALYSIS_TASKS:
            print(f"    {task:<14}: {book_paths[task].relative_to(ROOT)}")
    else:
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

    # One throwaway spawn before the round. Every failure it catches breaks every
    # paper identically, so finding one on paper 1 of 50 wastes 49 papers' quota
    # and finding it on a two-word prompt wastes nothing.
    probe = rr.preflight(room, model=args.model, claude=args.claude,
                         repo_root=ROOT)
    print(f"  preflight    : logged in, {len(probe.tools)} tools offered "
          f"(the room is empty)")
    print(f"  system prompt: {probe.input_tokens:,} billed input tokens on a "
          f"two-word probe (A17 ceiling {rr.PREFLIGHT_TOKEN_CEILING:,}; the CLI "
          f"default measured 12,198)")
    if probe.claude_code_version:
        print(f"  CLI version  : {probe.claude_code_version}")
    print(f"  effort       : {rr.EFFORT}  (pinned; the Batch API run passes the "
          f"same level)")

    if args.preflight_only:
        print(f"{bar}\nPREFLIGHT OK -- every live wall held. No paper was sent."
              f"\n{bar}")
        return 0

    print(f"  workers      : {args.workers}\n{bar}")

    started_at = now()
    index_rows, log_rows, ledger_rows = list(existing), [], []
    fatal: list[str] = []

    def one_paper(paper, body):
        token = rr.new_token(body.text)
        if combined:
            prompt = rr.build_combined_analysis_prompt(
                power_promptbook=promptbooks["power_analysis"],
                data_promptbook=promptbooks["data_analysis"],
                token=token, text=body.text)
        else:
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
            # Group G. Whatever the stream carried, and nothing it did not: an
            # absent field is an empty cell, never a fabricated 0 (G7).
            log_rows.append({
                "paper_id": paper.paper_id, "token": attempt.token,
                "task": args.task, "round": args.round, "stratum": paper.stratum,
                "chars": body.chars, "text_notes": body.notes,
                "outcome": outcome, "detail": detail,
                "attempt": attempt.attempt, "exit_code": attempt.exit_code,
                "duration_seconds": attempt.duration,
                **rr.paper_provenance(attempt.stdout)})
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

    # G2. The CLI auto-updates. A round that straddled an update ran its early
    # papers under one program and its late ones under another, and nothing in
    # the accuracy number would say so.
    try:
        rr.check_round_provenance([r.get("claude_code_version") for r in log_rows])
    except rr.RoundDiscarded as exc:
        fatal.append(str(exc))

    # G1/G10/G11. Written even on a discarded round: the record of what went
    # wrong is worth exactly as much as the record of what went right, and a
    # reader looking at the raw files needs to know which CLI produced them.
    environment = rr.build_run_environment(
        task=args.task, round_no=args.round,
        argv=rr.build_argv(model=args.model, settings_path=room.settings_path,
                           claude=rr.find_claude(args.claude)),
        promptbook_version=version, promptbook_text=promptbook_record,
        settings_path=room.settings_path, tools_offered=probe.tools,
        claude_code_version=probe.claude_code_version, model=args.model,
        started_at=started_at, finished_at=now(), repo_root=ROOT)
    rr.write_run_environment(raw_dir / "run_environment.json", environment)

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
    cost = sum(r["total_cost_usd"] for r in log_rows
               if isinstance(r.get("total_cost_usd"), (int, float)))
    print(f"DONE -- {ok}/{len(log_rows)} responses saved\n{bar}")
    print(f"  raw     -> {raw_dir.relative_to(ROOT)}")
    print(f"  ledger  -> {LEDGER.relative_to(ROOT)}")
    print(f"  run env -> {(raw_dir / 'run_environment.json').relative_to(ROOT)}"
          f"  (commit {environment['git_commit'][:12]}"
          + ("-dirty" if environment["git_commit"].endswith("-dirty") else "")
          + ")")
    print(f"  cost    -> ${cost:.2f} reported by the CLI "
          f"(blank where it reported none -- never defaulted to 0, G7)")
    if combined:
        print("\n  Next: combined response checking/persistence (the following "
              "implementation step).")
    else:
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
