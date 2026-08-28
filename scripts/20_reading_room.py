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
    --resume    re-run only process/checker failures that remain below the
                three-attempt budget; clean raw replies await checker approval
    --force     re-run a round that already has raw files (F5). Off by default
                because re-running double-inserts judgments
    --claude    path to the CLI, if it is not on PATH (F11)
    --parallel  run --workers papers at once. OFF by default: a pool spends six
                papers' quota before the first result reaches the screen, and on
                a five-hour subscription window that is the difference between
                noticing a round going wrong and finding out afterwards
    --workers   how wide --parallel goes, default 6. One paper per process, always
    --serial    the default; accepted so existing commands keep working
    --model     override the pinned model. You almost never want this

HOW A ROUND STOPS
    Serially, a `tool_use` or `tool_result` block ends the round **on the paper
    it happened on**. The room was not sealed, every later paper would run under
    the same broken conditions, and their quota is worth more unspent than spent
    proving the same thing 49 more times. Under --parallel the pool has already
    submitted everything, so the breach is collected and the round finishes.

    The per-paper line carries a running token total for the same reason: it is
    the number that says whether there is room to finish.

WHAT IT READS
    data/extracted_text_stripped/<paper_id>.json -- the references-stripped copy
    written by `scripts/19_strip_references.py`, which is 21.6% smaller than the
    extraction cache and decided by no criterion. Papers prepared two different
    ways in one round is a refusal, before anything spawns.

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
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import db                                              # noqa: E402
import reading_room as rr                              # noqa: E402

RESULTS = ROOT / "results" / "04_classification"
RAW_ROOT = RESULTS / "raw"
CHECKED_ROOT = RESULTS / "checked"
LEDGER = RESULTS / "retry_ledger.csv"

INDEX_COLUMNS = ["paper_id", "token", "task", "round", "promptbook_version",
                 "model", "attempt", "exit_code", "duration_seconds",
                 "raw_path", "started_at"]
RUN_LOG_COLUMNS = (["paper_id", "token", "task", "round", "stratum", "chars",
                    "text_notes", "outcome", "detail", "attempt", "exit_code",
                    "duration_seconds"]
                   + rr.PROVENANCE_COLUMNS)                          # group G

def configure_stdout() -> None:
    """Use UTF-8 for the executable without replacing a test runner's capture."""
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
    parser.add_argument("--parallel", action="store_true",
                        help="Run --workers papers at once. Off by default: the "
                             "pool commits six papers of quota before the first "
                             "result is readable")
    parser.add_argument("--workers", type=int, default=rr.DEFAULT_WORKERS,
                        help="How wide --parallel goes. Ignored without it")
    parser.add_argument("--serial", "--no-parallel", action="store_true",
                        dest="serial",
                        help="One paper at a time. This is the default; the flag "
                             "is kept so existing commands keep working")
    parser.add_argument("--model", default=rr.MODEL)
    parser.add_argument("--timeout", type=int, default=rr.TIMEOUT_SECONDS)
    args = parser.parse_args()

    # Refuses on contradictory flags, so it happens before anything is resolved.
    mode = rr.resolve_run_mode(parallel=args.parallel, serial=args.serial,
                               workers=args.workers)

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
    print(f"  text         : {rr.CACHE_DIR.relative_to(ROOT)}")
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

    # A clean subprocess exit proves only that bytes were saved.  It does not
    # prove the bytes parse or obey the promptbook.  Pair the latest raw index
    # row with the latest checker report so --resume repairs parse/semantic
    # failures instead of silently skipping them forever.
    latest = rr.latest_attempts_by_paper(existing)
    checked = read_csv(CHECKED_ROOT / f"{args.task}_r{args.round}.csv")
    attempt_by_paper: dict[str, int] = {}
    if args.resume or args.force:
        selected, accepted, awaiting, terminal = [], 0, 0, 0
        for paper in papers:
            prior = latest.get(paper.paper_id)
            state = rr.retry_state_for_attempt(prior, checked)
            if args.force and prior is not None:
                # --force deliberately makes another attempt, but it is not a
                # loophole around F2's bounded spend.
                if rr.attempt_number(prior) >= rr.MAX_ATTEMPTS:
                    state = {"state": rr.TERMINAL_REVIEW_REQUIRED,
                             "should_run": False, "next_attempt": None,
                             "failure_kind": state.get("failure_kind", "")}
                else:
                    state = {"state": "forced_retry", "should_run": True,
                             "next_attempt": rr.attempt_number(prior) + 1,
                             "failure_kind": ""}
            if state["should_run"]:
                selected.append(paper)
                attempt_by_paper[paper.paper_id] = state["next_attempt"]
            elif state["state"] == "accepted":
                accepted += 1
            elif state["state"] == "awaiting_check":
                awaiting += 1
            elif state["state"] == rr.TERMINAL_REVIEW_REQUIRED:
                terminal += 1
        papers = selected
        label = "--force" if args.force else "--resume"
        print(f"  {label:<13}: {accepted} accepted, {awaiting} awaiting checker, "
              f"{terminal} review-required, {len(papers)} to go")

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

    # Free, and before the first spawn: a round half on stripped text and half
    # on whole text is two conditions averaged into one accuracy number.
    rr.check_round_text_preparation([body.refs_method for _, body in prepared])

    if not args.dry_run:
        rr.find_claude(args.claude)                                     # F11

    if args.dry_run:
        print(f"\n  --dry-run: every wall checked, {len(prepared)} paper(s) would "
              f"be sent, nothing spawned.")
        total = sum(b.chars for _, b in prepared)
        print(f"  total text: {total:,} chars "
              f"(~{total // 3:,} tokens at 3 chars/token)")
        cut = sum(b.refs_removed for _, b in prepared)
        whole = [p.paper_id for p, b in prepared if not b.refs_removed]
        print(f"  references: {cut:,} chars already removed "
              f"(~{cut // 3:,} tokens not being sent); {len(whole)} paper(s) "
              f"went out whole")
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

    print(f"  workers      : {mode.label}")
    print(bar)

    started_at = now()
    index_rows, log_rows, ledger_rows = list(existing), [], []
    fatal: list[str] = []
    # The running spend, and how much of it the CLI declined to report. G7: an
    # absent usage block is counted as unknown, never as zero -- a counter that
    # treats unreported papers as free is a counter that says "keep going".
    tokens_so_far, tokens_unreported, calls_made = 0, 0, 0
    stopped_after, breach_stopped = 0, False

    def one_paper(item):
        paper, body = item
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
                               paper_id=paper.paper_id,
                               attempt=attempt_by_paper.get(paper.paper_id, 1),
                               model=args.model,
                               claude=args.claude, timeout=args.timeout,
                               repo_root=ROOT)
        attempt.raw_path = rr.write_raw(attempt, raw_dir)
        return paper, body, attempt

    # Both strategies live in `reading_room` and yield the same `(item, call)`
    # pairs, where `call()` returns the triple `one_paper` produced or re-raises
    # what it raised. The one shared result-handling body below is the point:
    # serial mode must not become a second runner that drifts from the parallel
    # one. `closing` so an early exit shuts the generator down -- and with it the
    # pool's `with` block -- rather than leaving it to the garbage collector.
    with closing(rr.runner_for(mode, prepared, one_paper)) as runner:
        for i, (item, call) in enumerate(runner, 1):
            paper, _ = item
            stopped_after = i
            try:
                paper, body, attempt = call()
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

            calls_made += 1
            spent = rr.billed_total_tokens(rr.stream_usage(attempt.stdout))
            if spent is None:
                tokens_unreported += 1
            else:
                tokens_so_far += spent

            print(f"  [{i:>3}/{len(prepared)}] {outcome:<15} {paper.paper_id} "
                  f"{attempt.duration:>6.1f}s  {body.chars:>7,} chars  "
                  f"{rr.format_tokens(tokens_so_far):>6} tok"
                  + (f"+{tokens_unreported}?" if tokens_unreported else "")
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
            # Successful process output is finalized by checker 21, which can
            # distinguish a real judgment from parse/semantic failure.  Record
            # process failures here because no checker pass can recover their
            # absent/incomplete response.  This keeps one ledger row per raw
            # attempt rather than an optimistic runner row plus a checker row.
            if not attempt.ok:
                terminal_status = (rr.TERMINAL_REVIEW_REQUIRED
                                   if attempt.attempt >= rr.MAX_ATTEMPTS else "")
                ledger_rows.append({
                    "timestamp": now(), "task": args.task, "round": args.round,
                    "paper_id": paper.paper_id, "token": attempt.token,
                    "attempt": attempt.attempt, "outcome": "failure",
                    "failure_kind": rr.FAILURE_PROCESS, "detail": detail,
                    "exit_code": attempt.exit_code,
                    "duration_seconds": attempt.duration,
                    "raw_path": str(attempt.raw_path.relative_to(ROOT)),
                    "retry_eligible": "no" if terminal_status else "yes",
                    "terminal_status": terminal_status})

            # Serially, the breach ends the round on the paper it happened on.
            # Every later paper would run under the same broken conditions, so
            # their quota is worth more unspent than spent proving it 49 more
            # times. Under --parallel the pool has already submitted them all,
            # so there is nothing left to save and the round finishes.
            if not sealed and mode.serial:
                breach_stopped = True
                break

    if breach_stopped:
        unsent = len(prepared) - stopped_after
        print(f"\n  !! STOPPED on paper {stopped_after} of {len(prepared)}: the "
              f"room was not sealed.\n     {unsent} paper(s) were not sent; that "
              f"quota is unspent.")

    # C1/C2 papers never reached the CLI; they still need a row, or the round's
    # denominator quietly shrinks.
    for paper, body in text_problems:
        log_rows.append({"paper_id": paper.paper_id, "task": args.task,
                         "round": args.round, "stratum": paper.stratum,
                         "chars": 0, "text_notes": body.notes,
                         "outcome": "no_text", "detail": rr.NO_TEXT_REASON})

    write_csv(raw_dir / "index.csv", INDEX_COLUMNS, index_rows)
    write_csv(raw_dir / "run_log.csv", RUN_LOG_COLUMNS, log_rows)
    if ledger_rows:
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

    unreported = (f", {tokens_unreported} paper(s) reported none"
                  if tokens_unreported else "")
    print(f"  tokens  -> {tokens_so_far:,} billed in+out across "
          f"{calls_made} call(s){unreported}")

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
    print(f"\n  Next: python scripts/21_check_responses.py --task {args.task} "
          f"--round {args.round}")
    return 0


if __name__ == "__main__":
    configure_stdout()
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
