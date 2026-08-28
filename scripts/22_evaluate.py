"""Evaluate persisted judgments against the labelled build or holdout split.

This script is read-only with respect to SQLite and model providers. It writes
analysis artifacts only: a Markdown dashboard plus CSV and JSON files that can
be opened in Excel, R, or Python plotting tools.

Examples
--------
    py -3 scripts/22_evaluate.py --task all --split build --promptbook-version v1
    py -3 scripts/22_evaluate.py --task exclusion --split build --no-write
"""

from __future__ import annotations

import argparse
import io
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import db  # noqa: E402
import evaluate  # noqa: E402


def _render(value, *, percent: bool = False) -> str:
    if value is None:
        return "—"
    if percent:
        return f"{float(value):.1%}"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _default_output(split: str, promptbook_version: str | None) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    version = promptbook_version or "all_versions"
    return ROOT / "results" / "04_classification" / "evaluation" / f"{split}_{version}_{stamp}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only classification metrics, including Cohen's kappa, sensitivity, and specificity.")
    parser.add_argument("--task", default="all", choices=["all", *db.TASKS],
                        help="Task to evaluate (default: all three tasks)")
    parser.add_argument("--split", default=db.SPLIT_BUILD,
                        choices=[db.SPLIT_BUILD, db.SPLIT_HOLDOUT])
    parser.add_argument("--promptbook-version",
                        help="Restrict to one promptbook version; default uses each paper's latest judgment")
    parser.add_argument("--db", type=Path, default=db.DEFAULT_PATH,
                        help="SQLite review database (default: data/review.db)")
    parser.add_argument("--out", type=Path,
                        help="Output directory; default is a timestamped evaluation directory")
    parser.add_argument("--no-write", action="store_true",
                        help="Print metrics only; do not create analysis artifacts")
    args = parser.parse_args()

    tasks = db.TASKS if args.task == "all" else (args.task,)
    conn = db.connect(args.db)
    try:
        results = evaluate.evaluate_tasks(
            conn, tasks, split=args.split,
            promptbook_version=args.promptbook_version)
    finally:
        conn.close()

    print("CLASSIFICATION EVALUATION")
    print(f"  split      : {args.split}")
    print(f"  promptbook : {args.promptbook_version or 'latest judgment per paper'}")
    print("\n  task             eligible  coverage  scored  accuracy  sensitivity  specificity  Cohen's kappa")
    for result in results:
        row = result.summary_row()
        print("  {task:<16} {eligible:>8}  {coverage:>8}  {scored:>6}  {accuracy:>8}  "
              "{sensitivity:>11}  {specificity:>11}  {kappa:>13}".format(
                  task=row["task"], eligible=row["eligible"],
                  coverage=_render(row["coverage"], percent=True), scored=row["scored"],
                  accuracy=_render(row["accuracy"], percent=True),
                  sensitivity=_render(row["sensitivity"], percent=True),
                  specificity=_render(row["specificity"], percent=True),
                  kappa=_render(row["cohen_kappa"]),
              ))

    if args.no_write:
        print("\n  No files written (--no-write). SQLite and model providers were not modified.")
        return 0

    output_dir = (args.out or _default_output(args.split, args.promptbook_version)).resolve()
    paths = evaluate.write_evaluation(output_dir, results)
    print(f"\n  report      -> {paths['report'].relative_to(ROOT)}")
    print(f"  summary CSV -> {paths['summary_csv'].relative_to(ROOT)}")
    print(f"  cases CSV   -> {paths['cases_csv'].relative_to(ROOT)}")
    print("  SQLite and model providers were not modified.")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    raise SystemExit(main())
