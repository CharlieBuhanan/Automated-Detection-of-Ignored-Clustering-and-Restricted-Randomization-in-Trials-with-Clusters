"""Export model answers as the 43-column ground-truth CSV (plan step 5).

Read-only against SQLite and providers: it reads accepted answers from
`structured_answers` and writes CSVs. It never calls a model.

One row per active HLS paper, in manifest order, with exactly the columns of
data/ground_truth.csv. A paper the model has not answered still gets its row
(`labeled` = 0, model columns blank), so the file always covers the corpus.

Writes, under results/04_classification/ground_truth_export/<version>/:
    model_answers.csv   the 43 columns (active papers)
    dropped_audit.csv   the 77 dropped HLS papers, and whether any was answered
    skipped_audit.csv   papers whose human rows disagree (decision 2)
    comparison.csv      n_long under both conventions; model vs derived `should`
    answer_index.csv    which stored response each row came from

Example
-------
    py -3 scripts/25_export_ground_truth.py --promptbook-version v2
    py -3 scripts/25_export_ground_truth.py --promptbook-version v2 --run-id <id> --no-write
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import db  # noqa: E402
import gt_export as g  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--promptbook-version", required=True,
                        help="only answers made under this promptbook (v2 or later)")
    parser.add_argument("--run-id", action="append", default=[],
                        help="restrict to these runs (repeatable); default every run")
    parser.add_argument("--db", type=Path, default=db.DEFAULT_PATH)
    parser.add_argument("--out", type=Path, default=None,
                        help="output folder (default ground_truth_export/<version>)")
    parser.add_argument("--no-write", action="store_true", help="print counts only")
    args = parser.parse_args()

    try:
        human = g.load_human()
    except g.ExportError as exc:
        print(f"STOP: {exc}")
        return 1
    conn = db.connect(args.db)
    answers = g.load_answers(conn, promptbook_version=args.promptbook_version,
                             run_ids=args.run_id)
    export = g.export_rows(human, answers)

    answered = sum(r["labeled"] == "1" for r in export.rows)
    print(f"active HLS papers : {len(human.active)}")
    print(f"rows exported     : {len(export.rows)} ({answered} answered by the model)")
    print(f"gate answers      : {len(answers.gate)}   full answers: {len(answers.full)}")
    print(f"skipped (human rows disagree): {len(export.skipped)}")
    print(f"dropped HLS papers: {len(export.dropped)} "
          f"({sum(r['model_answered'] for r in export.dropped)} answered)")
    if export.orphans:
        print(f"WARNING: {len(export.orphans)} answered papers are not active HLS: "
              f"{export.orphans[:5]}")
    if args.no_write:
        return 0

    out = args.out or g.OUT_DIR / args.promptbook_version
    g.write_csv(out / "model_answers.csv", export.rows, export.header)
    g.write_csv(out / "dropped_audit.csv", export.dropped,
                ["paper_id", "verdict_reason", "model_answered"])
    g.write_csv(out / "skipped_audit.csv", export.skipped, ["paper_id", "reason"])
    g.write_csv(out / "comparison.csv", export.comparison, g.COMPARISON_COLUMNS)
    g.write_csv(out / "answer_index.csv", export.answer_index, g.ANSWER_INDEX_COLUMNS)
    print(f"wrote {out.relative_to(g.ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
