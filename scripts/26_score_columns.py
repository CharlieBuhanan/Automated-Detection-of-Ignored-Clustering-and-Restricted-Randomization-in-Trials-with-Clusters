"""Score an export from script 25 against the human file, column by column.

Read-only. Rules are data/field_dictionary.csv's `scoring_rule`:
a blank human cell is not scored (decision 13), abstentions are counted apart
from misses, and a cell the rules cannot compare yet is `not_scored` with a
reason (e.g. a unit term with no person-checked row in data/unit_synonyms.csv).

The build split is the default. The holdout is touched once, at the end, so
`--split holdout` needs `--i-am-scoring-the-holdout`.

Writes, beside the export:
    column_scores_<split>.csv   one row per column: compared, match, mismatch, ...
    cell_scores_<split>.csv     one row per compared cell, for reading the misses

Example
-------
    py -3 scripts/26_score_columns.py --promptbook-version v2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import db  # noqa: E402
import gt_export as g  # noqa: E402

SUMMARY_COLUMNS = ["column", "compared", "match", "mismatch", "abstain", "not_scored",
                   "agreement", "note"]
CELL_COLUMNS = ["paper_id", "column", "human", "model", "outcome", "note"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--promptbook-version", required=True)
    parser.add_argument("--export-dir", type=Path, default=None,
                        help="script 25's folder (default ground_truth_export/<version>)")
    parser.add_argument("--split", choices=["build", "holdout", "all"], default="build")
    parser.add_argument("--i-am-scoring-the-holdout", action="store_true")
    parser.add_argument("--db", type=Path, default=db.DEFAULT_PATH)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    if args.split in ("holdout", "all") and not args.i_am_scoring_the_holdout:
        print("STOP: the holdout is scored once, at the end. Add "
              "--i-am-scoring-the-holdout if that is now.")
        return 1
    folder = args.export_dir or g.OUT_DIR / args.promptbook_version
    if not (folder / "model_answers.csv").exists():
        print(f"STOP: no export in {folder}; run scripts/25_export_ground_truth.py first")
        return 1
    _, export = g.read_csv(folder / "model_answers.csv")
    _, index = g.read_csv(folder / "answer_index.csv")
    _, comparison = g.read_csv(folder / "comparison.csv")
    human = g.load_human()

    papers = None
    if args.split != "all":
        conn = db.connect(args.db)
        papers = {row[0] for row in conn.execute(
            "SELECT paper_id FROM validation_labels WHERE split = ?", (args.split,))}
    summary, cells = g.score(export, human, index, comparison, papers=papers)

    width = max(len(r["column"]) for r in summary)
    print(f"{'column':<{width}}  compared  match  miss  abstain  not_scored  agreement")
    for r in summary:
        print(f"{r['column']:<{width}}  {r['compared']:>8}  {r['match']:>5}  "
              f"{r['mismatch']:>4}  {r['abstain']:>7}  {r['not_scored']:>10}  "
              f"{r['agreement'] or '-':>9}  {r['note']}")
    if args.no_write:
        return 0
    g.write_csv(folder / f"column_scores_{args.split}.csv", summary, SUMMARY_COLUMNS)
    g.write_csv(folder / f"cell_scores_{args.split}.csv", cells, CELL_COLUMNS)
    print(f"wrote {folder.relative_to(g.ROOT)}/column_scores_{args.split}.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
