"""Cut the build split into fixed rounds of 50, per task, deterministically.

WHY
    DC32: each promptbook round samples 50 papers from the build split. "Sample"
    must not mean "draw fresh each time" -- a round drawn at random every run
    makes two rounds incomparable, and makes the plateau rule (DC17, two
    consecutive rounds each under 1pp) measure sampling noise as often as it
    measures the promptbook. So the rounds are cut once, written down, and
    reused.

    Rounds are cut per task because the tasks have different denominators. The
    gate is scored on the whole build split; power and data analysis are scored
    only on the papers the humans kept (DC10), so their rounds come from the 123
    build survivors, not all 338.

    Each exclusion round is **stratified on gate-survivor status** in the same
    proportion as the build split as a whole. Without it a round could come out
    80% excluded, and its accuracy would not be comparable to the next round's
    -- which is the one thing rounds exist to be.

    Deterministic and regenerable: ordering hashes `seed + paper_id`, so this
    script produces the same file on any machine, in any order, forever. The CSV
    is the record; re-running it is a no-op unless the build split itself
    changed, and if it did, that is a finding rather than a refresh.

OUTPUTS
    results/04_classification/build_rounds.csv   paper_id, task, round, stratum

USAGE
    python scripts/17_assign_build_rounds.py            # write the file
    python scripts/17_assign_build_rounds.py --dry-run  # show the shape only
"""

import argparse
import csv
import io
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "04_classification" / "build_rounds.csv"

# DC32. Small enough to read every miss, large enough for a repeated failure
# shape to be visible -- which DC23 requires before any rule is written.
ROUND_SIZE = 50

# Same seed as the split, different salt, so round order is independent of
# split order rather than a rotation of it.
SEED = "automated-ignore-rounds"

COLUMNS = ["paper_id", "task", "round", "stratum"]

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def interleave_strata(strata: dict[str, list[str]]) -> list[str]:
    """Order papers so every window of ROUND_SIZE holds each stratum in
    proportion.

    Deals round-robin weighted by stratum size: with 123 survivors and 215
    excluded, each 50-paper round lands ~18 survivors and ~32 excluded without
    anyone computing those numbers. The last round is short and slightly
    off-proportion, which is unavoidable and harmless.
    """
    total = sum(len(v) for v in strata.values())
    if not total:
        return []

    # position in [0, 1) for each paper, spread evenly within its own stratum
    placed: list[tuple[float, str, str]] = []
    for stratum, papers in strata.items():
        n = len(papers)
        for i, paper_id in enumerate(papers):
            placed.append(((i + 0.5) / n, stratum, paper_id))

    placed.sort()
    return [(paper_id, stratum) for _, stratum, paper_id in placed]


def rounds_for(papers: list[tuple[str, str]], task: str) -> list[dict]:
    rows = []
    for index, (paper_id, stratum) in enumerate(papers):
        rows.append({
            "paper_id": paper_id,
            "task": task,
            "round": index // ROUND_SIZE + 1,
            "stratum": stratum,
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report only, write nothing")
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{db.DEFAULT_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    build = [r for r in conn.execute(
        "SELECT * FROM validation_labels WHERE split = ?", (db.SPLIT_BUILD,))]
    conn.close()

    if not build:
        raise SystemExit(
            "No papers carry split='build'. Run "
            "scripts/04_load_ground_truth.py --assign-split first.")

    strata: dict[str, list[str]] = {"survivor": [], "excluded": []}
    for row in build:
        strata[db._gate_stratum(row)].append(row["paper_id"])
    for papers in strata.values():
        papers.sort(key=lambda p: (db._split_rank(p, SEED), p))

    all_rows: list[dict] = []
    # The gate is scored on the whole build split, stratified so each round is
    # comparable to the next.
    all_rows += rounds_for(interleave_strata(strata), "exclusion")
    # Power and data see survivors only -- there is nothing to stratify on, so
    # the hash order is the round order.
    survivors = [(p, "survivor") for p in strata["survivor"]]
    for task in ("power_analysis", "data_analysis"):
        all_rows += rounds_for(survivors, task)

    print(f"build split: {len(build)} papers "
          f"({len(strata['survivor'])} survivors / {len(strata['excluded'])} excluded)")
    print(f"round size: {ROUND_SIZE}\n")

    for task in ("exclusion", "power_analysis", "data_analysis"):
        task_rows = [r for r in all_rows if r["task"] == task]
        by_round = Counter(r["round"] for r in task_rows)
        print(f"{task}  ({len(task_rows)} papers, {len(by_round)} rounds)")
        for rnd in sorted(by_round):
            in_round = [r for r in task_rows if r["round"] == rnd]
            mix = Counter(r["stratum"] for r in in_round)
            detail = (f"  {mix['survivor']:3} survivor / {mix['excluded']:3} excluded"
                      if task == "exclusion" else "")
            print(f"  R{rnd}  {len(in_round):3} papers{detail}")
        print()

    if args.dry_run:
        print("--dry-run: nothing written.")
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"rounds -> {OUT.relative_to(ROOT)}  ({len(all_rows)} rows)")


if __name__ == "__main__":
    main()
