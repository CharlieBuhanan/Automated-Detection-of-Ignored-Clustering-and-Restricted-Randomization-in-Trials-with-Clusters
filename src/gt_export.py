"""Step 5 of research design/GROUND_TRUTH_OUTPUT_PLAN.md: the 43-column export and
per-column scoring.

Two pure halves, so both are testable without a database:

* :func:`export_rows` turns validated answers (``ExclusionWithReason`` and
  ``FullAnalysis``) plus the human file's provenance into rows with exactly the
  columns of ``data/ground_truth.csv``, in its order. How each column is
  rendered is ``data/field_dictionary.csv``'s ``export_rule``.
* :func:`score` compares an export with the human file column by column, by
  the dictionary's ``scoring_rule``. A blank human cell is never a miss
  (decision 13); a model abstention is counted apart from misses; a cell the
  rules cannot compare yet (a unit name with no person-checked synonym, a
  human value that will not parse) is ``not_scored`` with its reason, never
  silently a match or a miss.

Reads only. Model answers come from ``structured_answers``; nothing here calls
a model or edits the human file.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import schemas as s

ROOT = Path(__file__).resolve().parent.parent
GROUND_TRUTH = ROOT / "data" / "ground_truth.csv"
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
FIELD_DICTIONARY = ROOT / "data" / "field_dictionary.csv"
UNIT_SYNONYMS = ROOT / "data" / "unit_synonyms.csv"
OUT_DIR = ROOT / "results" / "04_classification" / "ground_truth_export"

# Decision 1: read from the frozen manifest; stop if they change.
EXPECTED_ACTIVE_HLS = 477
EXPECTED_DROPPED_HLS = 77

EXCLUSION_ROUTE = "exclusion"
COMBINED_ROUTE = "combined_analysis"
NR = "NR"
LABEL_KEYS = ("excluded", "power_correct", "data_correct")
COUNT_COLUMNS = ("n_outer", "n_2nd", "n_3rd", "n_4th")


class ExportError(RuntimeError):
    """The inputs disagree with a frozen expectation; nothing is written."""


# ------------------------------------------------------------------ inputs


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


@dataclass
class HumanSide:
    header: list[str]
    active: list[str]                         # paper ids, manifest order
    dropped: list[dict]                       # manifest rows
    rows_by_paper: dict[str, list[dict]]

    def primary_row(self, paper_id: str) -> dict:
        """The row whose provenance the export copies and that scoring reads.

        Most papers have one row. A paper both institutes labelled has two that
        agree on every label (DC37 dropped the disagreements); the one carrying
        the detailed extraction wins, then NHLBI, then file order.
        """
        rows = self.rows_by_paper[paper_id]
        return sorted(rows, key=lambda r: (not r["comment_levels"] and not r["n_trt"],
                                           r["source_institute"] != "NHLBI"))[0]

    def conflicts(self, paper_id: str) -> list[str]:
        """Label keys on which this paper's human rows disagree (decision 2)."""
        rows = self.rows_by_paper[paper_id]
        return [key for key in LABEL_KEYS
                if len({r[key] for r in rows if r[key] != ""}) > 1]


def load_human(ground_truth: Path = GROUND_TRUTH, manifest: Path = MANIFEST, *,
               expected_active: int | None = EXPECTED_ACTIVE_HLS,
               expected_dropped: int | None = EXPECTED_DROPPED_HLS) -> HumanSide:
    header, rows = read_csv(ground_truth)
    _, manifest_rows = read_csv(manifest)
    hls = [r for r in manifest_rows if r["set"] == "human_labelled"]
    active = [r["paper_id"] for r in hls if r["verdict"] != "DROPPED"]
    dropped = [r for r in hls if r["verdict"] == "DROPPED"]
    if expected_active is not None and len(active) != expected_active:
        raise ExportError(f"manifest has {len(active)} active HLS papers, expected "
                          f"{expected_active}; re-freeze deliberately before exporting")
    if expected_dropped is not None and len(dropped) != expected_dropped:
        raise ExportError(f"manifest has {len(dropped)} dropped HLS papers, expected "
                          f"{expected_dropped}")
    by_paper: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_paper[row["paper_id"]].append(row)
    missing = [p for p in active if p not in by_paper]
    if missing:
        raise ExportError(f"{len(missing)} active papers have no ground_truth.csv row: "
                          f"{missing[:5]}")
    return HumanSide(header, active, dropped, dict(by_paper))


@dataclass
class ModelAnswers:
    """The accepted answer per paper and route, plus where each came from."""

    gate: dict[str, s.ExclusionWithReason] = field(default_factory=dict)
    full: dict[str, s.FullAnalysis] = field(default_factory=dict)
    source: dict[tuple[str, str], str] = field(default_factory=dict)  # -> response_id


def load_answers(conn: sqlite3.Connection, *, promptbook_version: str,
                 run_ids: Iterable[str] = ()) -> ModelAnswers:
    """Latest stored answer per (paper, route) for one promptbook version.

    Stored answers were validated on the way in; they are re-validated here so
    a schema change can never export a shape the current code would reject.
    """
    run_ids = list(run_ids)
    sql = ("SELECT response_id, run_id, paper_id, route, answer_json, created_at "
           "FROM structured_answers WHERE promptbook_version = ?")
    params: list = [promptbook_version]
    if run_ids:
        sql += f" AND run_id IN ({','.join('?' * len(run_ids))})"
        params += run_ids
    sql += " ORDER BY created_at, response_id"
    answers = ModelAnswers()
    for row in conn.execute(sql, params):
        payload = json.loads(row["answer_json"]) | {"paper_id": row["paper_id"]}
        if row["route"] == EXCLUSION_ROUTE:
            answers.gate[row["paper_id"]] = s.ExclusionWithReason.model_validate(payload)
        elif row["route"] == COMBINED_ROUTE:
            answers.full[row["paper_id"]] = s.FullAnalysis.model_validate(payload)
        else:
            continue
        answers.source[(row["paper_id"], row["route"])] = row["response_id"]
    return answers


# --------------------------------------------------------------- rendering


def _label(value: str | None) -> str:
    """`other: food pantry` -> `food pantry`; listed values unchanged."""
    return "" if value is None else s.other_label(value)


def render_count(count: s.ClusterCount) -> str:
    if count.kind == s.NOT_REPORTED:
        return NR
    if count.kind == s.UNCLEAR:
        return s.UNCLEAR
    text = (f"{count.low}-{count.high}" if count.kind == "range"
            else f"~{count.value}" if count.kind == "approximate" else str(count.value))
    return f"{text}/{_label(count.per)}" if count.per else text


def render_missing(value) -> str:
    if value == s.NOT_REPORTED:
        return NR
    return str(value)


def render_restriction(rr: s.RestrictedRandomization) -> str:
    if rr.status != "restricted":
        return {"none": "none", s.NOT_REPORTED: NR}.get(rr.status, rr.status)
    text = "yes, " + ", ".join(_label(x) for x in rr.schemes)
    return f"{text} by {rr.variables}" if rr.variables else text


def _number(value: float) -> str:
    return f"{value:g}"


def render_icc(icc: s.Icc) -> str:
    if icc.status != "reported":
        return render_missing(icc.status)
    parts = []
    for value in icc.values:
        number = (_number(value.value) if value.kind == "exact"
                  else f"{_number(value.low)}-{_number(value.high)}")
        parts.append(f"{value.applies_to} {number}" if value.applies_to and
                     len(icc.values) > 1 else number)
    return "; ".join(parts)


DATA_METHOD_NAMES = {
    "mixed_effects": "Mixed model", "gee": "GEE", "cluster_level": "Cluster-level analysis",
    "cluster_robust_se": "Cluster-robust SE", "permutation": "Permutation test",
    "bayesian_hierarchical": "Bayesian hierarchical model",
    "cluster_fixed_effects": "Cluster fixed effects",
    "individual_level": "Individual-level analysis",
}
POWER_METHOD_NAMES = {"formula": "Formula", "simulation": "Simulation",
                      "not_described": "Method not described"}


def _accounting(done, units: list[str]) -> str:
    """The shared '... accounting for clustering at x, not restricted rand.' tail."""
    clauses = {
        "all_levels": f"accounting for clustering at {', '.join(map(_label, units))}",
        "some_levels": f"accounting for clustering at {', '.join(map(_label, units))} only",
        "ignored": "not accounting for clustering",
        "unclear": "clustering unclear",
    }
    text = clauses[done.clustering]
    text += {"accounted": ", restricted rand.", "ignored": ", not restricted rand.",
             "unclear": ", restricted rand. unclear", "not_applicable": ""}[done.restricted_rand]
    text += {"accounted": ", longitudinality", "ignored": ", not longitudinality",
             "not_applicable": ""}[done.longitudinality]
    return text


def render_data_done(done: s.DataDone) -> str:
    if done.method == s.NOT_REPORTED:
        return "Not reported"
    name = DATA_METHOD_NAMES.get(done.method, _label(done.method))
    text = f"{name} {_accounting(done, done.levels_modeled)}"
    if done.small_sample_correction == "yes":
        text += ", with small-sample correction"
    return text + (" (planned only)" if done.planned_only else "")


def render_power_done(done: s.PowerDone) -> str:
    if done.reported == "no":
        return "Not reported"
    name = POWER_METHOD_NAMES.get(done.method, _label(done.method))
    text = f"{name} {_accounting(done, done.units_accounted)}"
    if done.source_note:
        text += f" ({done.source_note})"
    return text + (" (post hoc)" if done.timing == "post_hoc" else "")


def render_comment(comment: s.DataComment) -> str:
    tags = ", ".join(_label(tag) for tag in comment.tags)
    if comment.note:
        return f"{tags}: {comment.note}" if tags else comment.note
    return tags


@dataclass(frozen=True)
class ShouldFactors:
    units: tuple[str, ...]
    restricted_rand: bool
    longitudinality: bool

    def render(self) -> str:
        text = ("Account for clustering at " + ", ".join(map(_label, self.units))
                if self.units else "Account for no clustering")
        if self.restricted_rand:
            text += ", restricted rand."
        if self.longitudinality:
            text += ", longitudinality"
        return text


def derived_should(design: s.StudyDesign) -> ShouldFactors:
    """What a correct analysis must account for, from the design alone.

    Longitudinality follows the export's n_long convention (baseline counted):
    required when the primary outcome is measured two or more times.
    """
    n_long = design.n_long()
    return ShouldFactors(
        units=tuple(design.correlated_units),
        restricted_rand=design.restricted_randomization.status == "restricted",
        longitudinality=isinstance(n_long, int) and n_long >= 2)


def model_should(should: s.Should) -> ShouldFactors:
    return ShouldFactors(tuple(should.units), should.restricted_rand, should.longitudinality)


def _decision_01(decision: str) -> str:
    return {"yes": "1", "no": "0"}.get(decision, "")


def _verdict(decision: str) -> str:
    return decision if decision in ("yes", "no") else ""


def design_cells(design: s.StudyDesign) -> dict[str, str]:
    outer_first = list(reversed(design.levels))
    counts = {column: render_count(level.count) if level else ""
              for column, level in zip(COUNT_COLUMNS, outer_first + [None] * 4)}
    return {
        "n_trt": render_missing(design.n_trt),
        "n_levels": str(design.n_levels()),
        "comment_levels": " within ".join(_label(u) for u in design.units()),
        **counts,
        "unit_rand": _label(design.unit_rand),
        "ind_samp_unit": _label(design.ind_samp_unit),
        "restricted_rand_raw": render_restriction(design.restricted_randomization),
        "icc": render_icc(design.icc),
        "n_long": render_missing(design.n_long()),
        "stepped_wedge_raw": render_missing(design.stepped_wedge),
        "restricted_rand": {"restricted": "yes", "none": "no", s.NOT_REPORTED: "no",
                            s.UNCLEAR: s.UNCLEAR}[design.restricted_randomization.status],
        "stepped_wedge": {"yes": "yes", "no": "no", s.NOT_REPORTED: "no",
                          s.UNCLEAR: s.UNCLEAR}[design.stepped_wedge],
    }


PROVENANCE = ("paper_id", "paper_id_note", "source_institute", "source_file", "source_row",
              "citation_raw", "cite_key", "matched_by", "match_score", "source_note",
              "source_doi", "source_pmid", "reason_source")


def export_row(header: list[str], human_row: dict, gate: s.ExclusionWithReason | None,
               full: s.FullAnalysis | None) -> dict:
    row = {column: "" for column in header}
    row.update({column: human_row[column] for column in PROVENANCE})
    row["labeled"] = "1" if gate or full else "0"
    if gate:
        row["excluded"] = _decision_01(gate.decision)
        if gate.decision == "yes":
            row["exclusion_reason"] = gate.reason_name() or ""
            row["exclusion_reason_raw"] = gate.exclusion_reason or ""
    if full:
        power, data = full.power_analysis, full.data_analysis
        row.update(design_cells(full.design))
        should = derived_should(full.design).render()
        row.update({
            "power_correct": _verdict(power.decision), "power_correct_raw": power.decision,
            "data_correct": _verdict(data.decision), "data_correct_raw": data.decision,
            "data_done": render_data_done(data.done), "data_should": should,
            "data_comment": render_comment(data.comment),
            "power_done": render_power_done(power.done), "power_should": should,
        })
    if list(row) != header:
        raise ExportError("export row drifted from the ground_truth.csv column order")
    return row


COMPARISON_COLUMNS = [
    "paper_id", "baseline_measured", "n_followup", "n_long", "n_long_followup_only",
    "levels_beyond_4th", "derived_should", "power_model_should", "power_should_agrees",
    "data_model_should", "data_should_agrees",
]
# One row per answered paper: which stored responses the export used, and the
# gate's raw decision, so scoring can tell an abstention from "never asked".
ANSWER_INDEX_COLUMNS = ["paper_id", "gate_response_id", "gate_decision",
                        "full_response_id"]


def comparison_row(paper_id: str, full: s.FullAnalysis, answers: ModelAnswers) -> dict:
    design = full.design
    derived = derived_should(design)
    power = model_should(full.power_analysis.should)
    data = model_should(full.data_analysis.should)
    return {
        "paper_id": paper_id,
        "baseline_measured": design.longitudinal.baseline_measured,
        "n_followup": design.longitudinal.n_followup,
        "n_long": render_missing(design.n_long()),
        "n_long_followup_only": render_missing(design.longitudinal.n_long_followup_only()),
        "levels_beyond_4th": " within ".join(_label(u) for u in design.units()[:-4]),
        "derived_should": derived.render(),
        "power_model_should": power.render(), "power_should_agrees": int(power == derived),
        "data_model_should": data.render(), "data_should_agrees": int(data == derived),
    }


@dataclass
class Export:
    header: list[str]
    rows: list[dict]
    dropped: list[dict]
    skipped: list[dict]
    comparison: list[dict]
    answer_index: list[dict]
    orphans: list[str]           # answered papers that are not active HLS


def export_rows(human: HumanSide, answers: ModelAnswers) -> Export:
    rows, skipped, comparison, index = [], [], [], []
    for paper_id in human.active:
        conflict = human.conflicts(paper_id)
        if conflict:
            skipped.append({"paper_id": paper_id,
                            "reason": "human rows disagree on " + ", ".join(conflict)})
            continue
        gate, full = answers.gate.get(paper_id), answers.full.get(paper_id)
        rows.append(export_row(human.header, human.primary_row(paper_id), gate, full))
        if full:
            comparison.append(comparison_row(paper_id, full, answers))
        if gate or full:
            index.append({
                "paper_id": paper_id,
                "gate_response_id": answers.source.get((paper_id, EXCLUSION_ROUTE), ""),
                "gate_decision": gate.decision if gate else "",
                "full_response_id": answers.source.get((paper_id, COMBINED_ROUTE), "")})
    dropped = [{"paper_id": r["paper_id"], "verdict_reason": r["verdict_reason"],
                "model_answered": int(r["paper_id"] in answers.gate
                                      or r["paper_id"] in answers.full)}
               for r in human.dropped]
    known = set(human.active)
    orphans = sorted((set(answers.gate) | set(answers.full)) - known)
    return Export(human.header, rows, dropped, skipped, comparison, index, orphans)


# ----------------------------------------------------------------- scoring

MATCH, MISMATCH, ABSTAIN, NOT_SCORED = "match", "mismatch", "abstain", "not_scored"

_NR_WORDS = {"nr", "not reported", "not mentioned", "missing", "none reported",
             "not listed", "not specified", "unknown"}


def _norm_unit_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def load_synonyms(path: Path = UNIT_SYNONYMS) -> dict[str, str]:
    """Person-checked human term -> unit. Unchecked rows are proposals only."""
    if not path.exists():
        return {}
    _, rows = read_csv(path)
    return {_norm_unit_text(r["human_term"]): r["unit"] for r in rows
            if r.get("checked", "").strip().lower() == "yes"}


def canonical_unit(text: str, synonyms: dict[str, str]) -> tuple[str, bool]:
    """(canonical form, resolved?). A listed unit or a checked synonym resolves."""
    term = _norm_unit_text(text)
    as_unit = term.replace(" ", "_")
    for candidate in (as_unit, as_unit.rstrip("s")):
        if candidate in s.UNITS:
            return candidate, True
    if term in synonyms:
        return synonyms[term], True
    return term, False


def parse_human_levels(text: str) -> list[str] | None:
    """'patient within physician within clinic' -> units; None if it is prose."""
    if "?" in text:
        return None
    # A reviewer's aside after ';' ("...within state; 3 states") is not a level.
    head = text.split(";", 1)[0].strip()
    pieces = [p.strip() for p in re.split(r"\s+within\s+", head)]
    if len(pieces) < 2 or any(not p or len(p.split()) > 4 or "," in p for p in pieces):
        return None
    return pieces


_COUNT = re.compile(r"^(~)?(\d+)(?:-(\d+))?(?:/(.+))?$")
_PER_WORDS = re.compile(r"^(\S+)\s+per\s+(.+)$")


def parse_count(text: str) -> tuple | None:
    """'~20/school' -> ('approximate', (20,), True). None when it will not parse."""
    text = text.strip()
    if _norm_unit_text(text) in _NR_WORDS:
        return (NR, (), False)
    if text == s.UNCLEAR:
        return (s.UNCLEAR, (), False)
    text = re.sub(r"\s+total$", "", text).replace("--", "-").replace("–", "-")
    per_words = _PER_WORDS.match(text)            # '44 per health district'
    if per_words:
        text = f"{per_words.group(1)}/{per_words.group(2)}"
    match = _COUNT.match(text.replace(",", "").replace(" ", ""))
    if not match:
        return None
    approx, first, second, per = match.groups()
    if second:
        return ("range", (int(first), int(second)), bool(per))
    return ("approximate" if approx else "exact", (int(first),), bool(per))


_ICC_NUMBER = re.compile(r"(?<![\w.])(\d*\.\d+|\d+)(?:\s*[-–]\s*(\d*\.\d+|\d+))?(?![\w.])")


def parse_icc(text: str) -> frozenset | str | None:
    """Set of (low, high) pairs, or NR, or None when it will not parse."""
    if _norm_unit_text(text) in _NR_WORDS:
        return NR
    if any(sign in text for sign in "<>≤≥"):
        return None
    pairs = set()
    for low, high in _ICC_NUMBER.findall(text):
        low_value = float(low)
        pairs.add((low_value, float(high) if high else low_value))
    if not pairs or any(not (0 <= v <= 1) for pair in pairs for v in pair):
        return None
    return frozenset(pairs)


_RESTRICT = re.compile(r"restrict|strat|match|pair|constrain|minimi", re.I)
_LONG = re.compile(r"longitud|repeated", re.I)
_CLUSTER = re.compile(r"cluster|level|within|random effect|account for (?:both )?\w+",
                      re.I)


def parse_human_should(text: str) -> tuple[bool, bool] | None:
    """(restricted required, longitudinality required); None if not a factor list."""
    if not text or not text.lower().startswith(("account", "analysis", "model",
                                                "mixed", "power", "generalized",
                                                "complex", "pre-hoc", "multilevel")):
        return None
    return bool(_RESTRICT.search(text)), bool(_LONG.search(text))


def _cell(paper_id: str, column: str, human: str, model: str, outcome: str,
          note: str = "") -> dict:
    return {"paper_id": paper_id, "column": column, "human": human, "model": model,
            "outcome": outcome, "note": note}


# Columns the scorer does not compare, and why (field dictionary scoring_rule).
UNSCORED = {
    "data_done": "pending person-coded human values (plan checklist)",
    "power_done": "pending person-coded human values (plan checklist)",
    "data_comment": "person spot-check only (decision 16)",
}
SCORED_COLUMNS = ("excluded", "exclusion_reason", "power_correct", "data_correct",
                  "n_trt", "n_levels", "comment_levels", *COUNT_COLUMNS, "unit_rand",
                  "ind_samp_unit", "restricted_rand", "icc", "n_long", "stepped_wedge",
                  "data_should", "power_should")
SECONDARY_SCORES = ("n_long (follow-up only)",)


def score_cell(column: str, human: dict, model: dict, synonyms: dict[str, str], *,
               gate_decision: str = "", has_full: bool = False) -> dict | None:
    """One comparison, or None when there is nothing to compare.

    Nothing to compare: the human cell is blank (decision 13), or the model was
    never asked that task (`gate_decision` empty for the gate columns,
    `has_full` false for the rest).
    """
    pid = human["paper_id"]
    h, m = human.get(column, ""), model.get(column, "")
    if column in ("excluded", "exclusion_reason"):
        if not gate_decision:
            return None
    elif not has_full:
        return None
    if column == "excluded":
        if h == "":
            return None
        if m == "":
            return _cell(pid, column, h, gate_decision, ABSTAIN, "undecidable / wrong_text")
        return _cell(pid, column, h, m, MATCH if h == m else MISMATCH)
    if column == "exclusion_reason":
        if human["excluded"] != "1" or model["excluded"] != "1" or not h:
            return None
        if h in ("protocol_paper", "duplicate_group_random_drop"):
            return _cell(pid, column, h, m, NOT_SCORED, "retired cross-paper rule")
        model_name = "secondary_analysis" if m == "secondary_in_title" else m
        return _cell(pid, column, h, m, MATCH if model_name == h else MISMATCH)
    if column in ("power_correct", "data_correct"):
        if h not in ("yes", "no"):
            return None
        if m == "":
            return _cell(pid, column, h, model[f"{column}_raw"], ABSTAIN, "undecidable")
        return _cell(pid, column, h, m, MATCH if h == m else MISMATCH)
    if h == "":
        return None
    if column in ("n_trt", "n_long", "restricted_rand", "stepped_wedge"):
        return _cell(pid, column, h, m, MATCH if h.strip() == m else MISMATCH)
    if column == "n_levels":
        units = parse_human_levels(human["comment_levels"])
        if units is None:
            return _cell(pid, column, h, m, NOT_SCORED, "human comment_levels is prose")
        recomputed = str(len(units) - 1)
        note = "" if recomputed == h else f"human file says {h}; Q8 recomputed"
        return _cell(pid, column, recomputed, m,
                     MATCH if recomputed == m else MISMATCH, note)
    if column in ("comment_levels", "unit_rand", "ind_samp_unit"):
        terms = (parse_human_levels(h) if column == "comment_levels" else [h])
        if terms is None:
            return _cell(pid, column, h, m, NOT_SCORED, "human value is prose")
        model_terms = m.split(" within ") if column == "comment_levels" else [m]
        human_canon = [canonical_unit(t, synonyms) for t in terms]
        model_canon = [canonical_unit(t, synonyms)[0] for t in model_terms]
        if [c for c, _ in human_canon] == model_canon:
            return _cell(pid, column, h, m, MATCH)
        unresolved = [t for t, (_, ok) in zip(terms, human_canon) if not ok]
        if unresolved:
            return _cell(pid, column, h, m, NOT_SCORED,
                         "no checked synonym for " + ", ".join(unresolved))
        return _cell(pid, column, h, m, MISMATCH)
    if column in COUNT_COLUMNS:
        parsed = parse_count(h)
        if parsed is None:
            return _cell(pid, column, h, m, NOT_SCORED, "human count will not parse")
        return _cell(pid, column, h, m, MATCH if parse_count(m) == parsed else MISMATCH)
    if column == "icc":
        parsed = parse_icc(h)
        if parsed is None:
            return _cell(pid, column, h, m, NOT_SCORED, "human ICC will not parse")
        return _cell(pid, column, h, m, MATCH if parse_icc(m) == parsed else MISMATCH)
    if column in ("data_should", "power_should"):
        needed = parse_human_should(h)
        if needed is None:
            return _cell(pid, column, h, m, NOT_SCORED, "human value is not a factor list")
        restricted, longitudinal = needed
        has = (", restricted rand." in m, ", longitudinality" in m)
        # Decision 14: every human-required factor present; extras are not misses.
        ok = (has[0] or not restricted) and (has[1] or not longitudinal)
        return _cell(pid, column, h, m, MATCH if ok else MISMATCH, "factors only, not units")
    raise ValueError(f"no scoring rule for {column}")


def score(export: list[dict], human: HumanSide, answer_index: list[dict],
          comparison: list[dict] = (), *, papers: set[str] | None = None,
          synonyms: dict[str, str] | None = None) -> tuple[list[dict], list[dict]]:
    """(per-column summary, per-cell detail) over the papers given (default all)."""
    synonyms = load_synonyms() if synonyms is None else synonyms
    cells: list[dict] = []
    index = {r["paper_id"]: r for r in answer_index}
    followup_only = {r["paper_id"]: r["n_long_followup_only"] for r in comparison}
    for row in export:
        pid = row["paper_id"]
        if papers is not None and pid not in papers:
            continue
        human_row = human.primary_row(pid)
        answered = index.get(pid, {})
        for column in SCORED_COLUMNS:
            cell = score_cell(column, human_row, row, synonyms,
                              gate_decision=answered.get("gate_decision", ""),
                              has_full=bool(answered.get("full_response_id")))
            if cell:
                cells.append(cell)
        if pid in followup_only and human_row["n_long"]:
            m = followup_only[pid]
            cells.append(_cell(pid, "n_long (follow-up only)", human_row["n_long"], m,
                               MATCH if human_row["n_long"] == m else MISMATCH,
                               "alternative convention, not the export"))
    summary = []
    for column in SCORED_COLUMNS + SECONDARY_SCORES:
        counts = Counter(c["outcome"] for c in cells if c["column"] == column)
        compared = counts[MATCH] + counts[MISMATCH]
        summary.append({
            "column": column, "compared": compared, "match": counts[MATCH],
            "mismatch": counts[MISMATCH], "abstain": counts[ABSTAIN],
            "not_scored": counts[NOT_SCORED],
            "agreement": f"{counts[MATCH] / compared:.3f}" if compared else "",
            "note": "",
        })
    for column, why in UNSCORED.items():
        summary.append({"column": column, "compared": 0, "match": 0, "mismatch": 0,
                        "abstain": 0, "not_scored": 0, "agreement": "", "note": why})
    return summary, cells


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
