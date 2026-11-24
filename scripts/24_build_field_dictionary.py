"""Write data/field_dictionary.csv: the frozen contract for the 43-column output.

One row per column of data/ground_truth.csv, in the same order. For each column
it says who fills it (code, model, derived, blank), which call answers it, its
type and allowed values, where the value sits in the model's structured answer,
how it is exported to CSV text, and how it is scored against the human answer.

Allowed values are read from src/schemas.py rather than typed here, so the
dictionary cannot drift from what the parser accepts. A test re-runs this
builder and fails if the checked-in CSV differs.

Run:  python scripts/24_build_field_dictionary.py          (writes the CSV)
      python scripts/24_build_field_dictionary.py --check  (exit 1 if stale)
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import schemas as s  # noqa: E402

OUT = ROOT / "data" / "field_dictionary.csv"
GROUND_TRUTH = ROOT / "data" / "ground_truth.csv"

FIELDS = ["position", "column", "filled_by", "task", "type", "vocab",
          "allowed_values", "missing_values", "model_field", "export_rule",
          "scoring_rule"]

# filled_by:  code    = copied from the paper's ground-truth/corpus record
#             model   = from the model's structured answer (code formats it)
#             derived = computed from other model fields, never asked directly
#             blank   = always empty (plan decision 10)
# task:       exclusion | full_analysis | none
# Post-gate columns are null when the full-analysis call was not made (decision 5).

MISSING = "not_reported -> NR; unclear -> unclear; null (not asked) -> blank"
COUNT = "exact | approximate | range | per parent unit | not_reported | unclear"
NOT_SCORED = "not scored (provenance)"


def vocab(name: str, extra: tuple[str, ...] = (), open_list: bool = True) -> str:
    values = tuple(getattr(s, name)) + extra
    return "; ".join(values) + ("; other: <label>" if open_list else "")


def code(column: str, note: str) -> dict:
    return dict(column=column, filled_by="code", task="none", type="text",
                model_field="", export_rule=note, scoring_rule=NOT_SCORED)


def count_row(column: str, position_from_outside: int) -> dict:
    ordinal = ["outermost", "2nd from outside", "3rd from outside",
               "4th from outside"][position_from_outside]
    return dict(
        column=column, filled_by="model", task="full_analysis", type="count",
        vocab="", allowed_values=COUNT, missing_values=MISSING,
        model_field=f"design.levels[{ordinal}].count",
        export_rule="exact 10; approximate ~10; range 5-8; per parent ~20/school; "
                    "not_reported NR; blank when fewer levels",
        scoring_rule="exact match on number and kind (decision 15); NR matches only NR; "
                     "scored only where the human cell is filled")


ROWS = [
    code("paper_id", "Zotero item key of the paper (DC1)"),
    code("paper_id_note", "copied from the paper's ground_truth.csv row"),
    code("source_institute", "copied (NCI / NHLBI)"),
    code("source_file", "copied"),
    code("source_row", "copied"),
    code("citation_raw", "copied"),
    code("cite_key", "copied"),
    code("matched_by", "copied"),
    code("match_score", "copied"),
    dict(column="labeled", filled_by="derived", task="none", type="0/1",
         allowed_values="1", model_field="",
         export_rule="1 when the model answered this paper (decision 11)",
         scoring_rule="not scored"),
    dict(column="excluded", filled_by="model", task="exclusion", type="0/1",
         allowed_values="yes; no; undecidable; wrong_text",
         missing_values="undecidable / wrong_text -> blank (abstention)",
         model_field="decision", export_rule="yes -> 1; no -> 0",
         scoring_rule="exact match; abstentions reported separately, not as misses"),
    dict(column="exclusion_reason", filled_by="model", task="exclusion", type="enum",
         vocab="EXCLUSION_REASONS",
         allowed_values="; ".join(f"{k} {v}" for k, v in s.EXCLUSION_REASONS.items()),
         missing_values="blank when kept", model_field="exclusion_reason",
         export_rule="E-number -> readable name (DC45)",
         scoring_rule="match on readable name when both sides excluded; E4 and E5 both "
                      "match human secondary_analysis; human protocol_paper / "
                      "duplicate_group_random_drop are not scorable (retired E12/E17)"),
    dict(column="exclusion_reason_raw", filled_by="derived", task="exclusion",
         type="text", model_field="exclusion_reason",
         export_rule="the E-number exactly as returned", scoring_rule="not scored"),
    dict(column="power_correct", filled_by="model", task="full_analysis", type="enum",
         allowed_values="yes; no; undecidable", missing_values="undecidable -> blank",
         model_field="power_analysis.decision", export_rule="yes / no",
         scoring_rule="exact match; undecidable is an abstention"),
    dict(column="power_correct_raw", filled_by="derived", task="full_analysis",
         type="text", model_field="power_analysis.decision",
         export_rule="decision exactly as returned", scoring_rule="not scored"),
    dict(column="data_correct", filled_by="model", task="full_analysis", type="enum",
         allowed_values="yes; no; undecidable", missing_values="undecidable -> blank",
         model_field="data_analysis.decision", export_rule="yes / no",
         scoring_rule="exact match; undecidable is an abstention"),
    dict(column="data_correct_raw", filled_by="derived", task="full_analysis",
         type="text", model_field="data_analysis.decision",
         export_rule="decision exactly as returned", scoring_rule="not scored"),
    dict(column="review_category", filled_by="blank", task="none", type="",
         export_rule="always blank (decision 10: NCI-only, restates data_correct)",
         scoring_rule="not scored"),
    dict(column="review_category_raw", filled_by="blank", task="none", type="",
         export_rule="always blank (decision 10)", scoring_rule="not scored"),
    dict(column="n_trt", filled_by="model", task="full_analysis", type="integer>=2",
         missing_values=MISSING, model_field="design.n_trt",
         export_rule="the number", scoring_rule="exact match"),
    dict(column="n_levels", filled_by="model", task="full_analysis", type="integer>=1",
         model_field="design.levels",
         export_rule="number of levels - 1 = levels of clustering above the person (Q8)",
         scoring_rule="exact match; human side recomputed as units - 1 from "
                      "comment_levels (Q8), human file never edited"),
    dict(column="comment_levels", filled_by="model", task="full_analysis",
         type="unit list", vocab="UNITS", allowed_values=vocab("UNITS"),
         model_field="design.levels[*].unit",
         export_rule="units inner to outer joined by ' within '; other: <label> -> label",
         scoring_rule="unit sequence match after a person-checked synonym map "
                      "(e.g. PCP -> physician)"),
    count_row("n_outer", 0),
    count_row("n_2nd", 1),
    count_row("n_3rd", 2),
    count_row("n_4th", 3),
    dict(column="unit_rand", filled_by="model", task="full_analysis", type="unit",
         vocab="UNITS", allowed_values="one of design.levels units",
         model_field="design.unit_rand", export_rule="unit name; other -> label",
         scoring_rule="unit match after synonym map"),
    dict(column="ind_samp_unit", filled_by="model", task="full_analysis", type="unit",
         vocab="UNITS", allowed_values="one of design.levels units, unit_rand or further out",
         model_field="design.ind_samp_unit", export_rule="unit name; other -> label",
         scoring_rule="unit match after synonym map"),
    dict(column="restricted_rand_raw", filled_by="model", task="full_analysis",
         type="scheme list", vocab="RESTRICTION_SCHEMES",
         allowed_values=vocab("RESTRICTION_SCHEMES") + "; or status none / not_reported / unclear",
         missing_values=MISSING, model_field="design.restricted_randomization",
         export_rule="none -> none; restricted -> 'yes, <schemes>' + ' by <variables>'",
         scoring_rule="scored through restricted_rand; scheme spot-checked"),
    dict(column="icc", filled_by="model", task="full_analysis", type="icc list",
         allowed_values="exact | range | multiple (each with applies_to) | not_reported | unclear",
         missing_values=MISSING, model_field="design.icc",
         export_rule="0.05; 0.01-0.05; 'clinic 0.05; physician 0.01-0.03'; NR",
         scoring_rule="numeric set match (same values, same ranges); NR matches NR and "
                      "human 'not mentioned' / 'missing'"),
    dict(column="n_long", filled_by="model", task="full_analysis", type="integer>=1",
         missing_values=MISSING, model_field="design.n_long",
         export_rule="the number (1 = measured once)",
         scoring_rule="exact match; does not affect power/data correctness (DC49)"),
    dict(column="stepped_wedge_raw", filled_by="model", task="full_analysis", type="enum",
         allowed_values="yes; no; unclear; not_reported", missing_values=MISSING,
         model_field="design.stepped_wedge", export_rule="as returned; not_reported -> NR",
         scoring_rule="scored through stepped_wedge"),
    dict(column="data_done", filled_by="model", task="full_analysis", type="structured",
         vocab="DATA_METHODS", allowed_values=vocab("DATA_METHODS", (s.NOT_REPORTED,)),
         missing_values="method not_reported -> 'Not reported'",
         model_field="data_analysis.done",
         export_rule="'<Method> accounting for clustering at <levels>[, not restricted rand.]"
                     "[, with small-sample correction]'",
         scoring_rule="method category vs person-coded human text; text spot-checked "
                      "(decision 16)"),
    dict(column="data_should", filled_by="derived", task="full_analysis",
         type="structured", model_field="design.correlated_units; "
         "design.restricted_randomization.status; design.n_long",
         export_rule="'Account for clustering at <correlated_units>[, restricted rand.]"
                     "[, longitudinality]'",
         scoring_rule="every human-required factor present; correct extras not "
                      "penalized (decision 14)"),
    dict(column="data_comment", filled_by="model", task="full_analysis", type="tags+note",
         vocab="DATA_COMMENT_TAGS", allowed_values=vocab("DATA_COMMENT_TAGS"),
         model_field="data_analysis.comment", export_rule="'tag, tag: note'",
         scoring_rule="person spot-check only (decision 16)"),
    dict(column="power_done", filled_by="model", task="full_analysis", type="structured",
         vocab="POWER_METHODS", allowed_values=vocab("POWER_METHODS", ("not_described",)),
         missing_values="reported no -> 'Not reported'", model_field="power_analysis.done",
         export_rule="'<Method> accounting for clustering at <units>[, not restricted rand.]"
                     "[, not longitudinality]'",
         scoring_rule="clustering / restricted / longitudinal parts vs person-coded human "
                      "power_done (plan checklist)"),
    dict(column="power_should", filled_by="derived", task="full_analysis",
         type="structured", model_field="design.correlated_units; "
         "design.restricted_randomization.status; design.n_long",
         export_rule="same as data_should",
         scoring_rule="every human-required factor present; correct extras not "
                      "penalized (decision 14)"),
    dict(column="restricted_rand", filled_by="derived", task="full_analysis", type="enum",
         allowed_values="yes; no; unclear",
         model_field="design.restricted_randomization.status",
         export_rule="restricted -> yes; none / not_reported -> no; unclear -> unclear",
         scoring_rule="exact match"),
    dict(column="stepped_wedge", filled_by="derived", task="full_analysis", type="enum",
         allowed_values="yes; no; unclear", model_field="design.stepped_wedge",
         export_rule="yes / no / unclear; not_reported -> no", scoring_rule="exact match"),
    code("source_note", "copied"),
    code("source_doi", "copied"),
    code("source_pmid", "copied"),
    code("reason_source", "copied"),
]


def build() -> str:
    with GROUND_TRUTH.open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    names = [row["column"] for row in ROWS]
    if names != header:
        raise SystemExit(f"dictionary columns differ from {GROUND_TRUTH.name}:\n"
                         f"  missing {sorted(set(header) - set(names))}\n"
                         f"  extra   {sorted(set(names) - set(header))}\n"
                         f"  or the order differs")
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    for position, row in enumerate(ROWS, start=1):
        writer.writerow({field: "" for field in FIELDS} | row | {"position": position})
    return out.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the checked-in CSV is stale; write nothing")
    args = parser.parse_args()
    text = build()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(ROOT)} is stale: run without --check")
            return 1
        print(f"{OUT.relative_to(ROOT)} is current")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="")
    counts: dict[str, int] = {}
    for row in ROWS:
        counts[row["filled_by"]] = counts.get(row["filled_by"], 0) + 1
    print(f"wrote {OUT.relative_to(ROOT)}: {len(ROWS)} columns {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
