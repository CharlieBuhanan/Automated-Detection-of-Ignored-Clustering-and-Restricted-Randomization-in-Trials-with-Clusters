"""Join one checked round to paper titles, human labels and promptbook rules.

Read-only. It calls no model, only reads SQLite, and writes only into
``results/04_classification/review_tables/``. The checked report is the spine:
one row per paper the round actually judged, so a table is scoped to exactly
one task, one round, and one promptbook version.

Truth comes from ``validation_labels`` through ``db.expected_decision`` -- the
same mapping ``22_evaluate.py`` scores against, so an ``outcome`` here and a
row in that script's ``cases.csv`` cannot disagree.

Examples
--------
    py -3 scripts/23_review_table.py --task data_analysis --round 1
    py -3 scripts/23_review_table.py --task data_analysis --round 1 --html
    py -3 scripts/23_review_table.py --all-rounds --html
    py -3 scripts/23_review_table.py --html results/04_classification/review_tables/data_analysis_r1_review_table.csv
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import db                                              # noqa: E402
import reading_room as rr                              # noqa: E402

RESULTS = ROOT / "results" / "04_classification"
CHECKED = RESULTS / "checked"
RAW_ROOT = RESULTS / "raw"
OUT_ROOT = RESULTS / "review_tables"
MANIFEST = ROOT / "data" / "zotero_manifest.csv"

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

COLUMNS = [
    "paper_id", "title", "first_author", "year", "journal", "doi",
    "task", "round", "promptbook_version", "split",
    "truth", "decision", "outcome", "confidence",
    "reasoning", "promptbook_evidence", "cited_rules",
    "status", "failure_kind", "failure_case", "detail", "raw_path",
]

# Errors and anything unscoreable first: those are the rows a reviewer opens the
# table to read. Correct calls sort last because they are the bulk of it.
OUTCOME_ORDER = ["false_negative", "false_positive", "undecidable", "wrong_text",
                 "failed", "unlabelled", "true_positive", "true_negative"]

OUTCOME_LABEL = {
    "false_negative": "FN", "false_positive": "FP", "true_positive": "TP",
    "true_negative": "TN", "undecidable": "undecidable", "wrong_text": "wrong text",
    "failed": "failed", "unlabelled": "unlabelled",
}

BINARY = ("true_positive", "true_negative", "false_positive", "false_negative")

# `<task>_r<n>.csv`, or `<task>_v<n>_r<n>.csv` once rounds carried the version.
CHECKED_NAME = re.compile(
    r"^(?P<task>exclusion|power_analysis|data_analysis)"
    r"(?:_(?P<version>v\d+))?_r(?P<round>\d+)$")

# `N. **D11. ...` -- the lookahead keeps the opening `**` inside the captured
# body so the emphasis stays balanced when it is rendered.
RULE_START = re.compile(r"^\s*\d+\.\s+(?=\*\*([EPD]\d{1,2})\.)")

SPLIT_RULES = re.compile(r"[;,]")


# ------------------------------------------------------------------ locating

def locate_checked(task: str, round_no: int, version: str | None) -> Path:
    """Mirror of 21_check_responses.locate_raw_dir, over the checked reports.

    Pre-versioning rounds are named `<task>_r<n>.csv`; versioned ones carry the
    promptbook version. Both stay readable.
    """
    legacy = CHECKED / f"{task}_r{round_no}.csv"
    versioned = sorted(CHECKED.glob(f"{task}_v*_r{round_no}.csv"))
    if version:
        requested = CHECKED / f"{task}_{version}_r{round_no}.csv"
        if requested.is_file():
            return requested
        if legacy.is_file() and run_environment(legacy).get("promptbook_version") == version:
            return legacy
        raise rr.Refuse(
            f"no checked {task} round {round_no} report for promptbook {version}")
    candidates = ([legacy] if legacy.is_file() else []) + versioned
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise rr.Refuse(
            f"no checked report for {task} round {round_no}. Run "
            f"scripts/21_check_responses.py --task {task} --round {round_no} first")
    names = ", ".join(path.name for path in candidates)
    raise rr.Refuse(
        f"multiple checked reports match {task} round {round_no} ({names}); "
        f"pass --promptbook-version, or --all-rounds to build every one")


def discover_checked(task: str | None) -> list[Path]:
    """Every checked report, optionally for one task, oldest round first.

    Iterating files rather than resolving names is what lets --all-rounds build
    both `power_analysis_r1` and `power_analysis_v1_r1`: as separate tables,
    which is what they are, instead of refusing them as an ambiguous pair.
    """
    found = []
    for path in sorted(CHECKED.glob("*.csv")):
        match = CHECKED_NAME.match(path.stem)
        if match and (task is None or match.group("task") == task):
            found.append((match.group("task"), int(match.group("round")),
                          match.group("version") or "", path))
    if not found:
        scope = f"for {task} " if task else ""
        raise rr.Refuse(f"no checked reports {scope}in {CHECKED.relative_to(ROOT)}")
    found.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in found]


def run_environment(checked_path: Path) -> dict:
    """The run record of the raw round this checked report was written from.

    Reported rather than assumed: the promptbook in force during the round is
    what its rule citations must be read against, and `promptbooks/CURRENT` may
    have moved on since.
    """
    path = RAW_ROOT / checked_path.stem / "run_environment.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------- sources

def load_manifest() -> dict[str, dict]:
    if not MANIFEST.is_file():
        raise rr.Refuse(f"{MANIFEST} is missing; run scripts/00_fetch_zotero.py")
    with MANIFEST.open(encoding="utf-8", newline="") as handle:
        return {row["paper_id"]: row for row in csv.DictReader(handle)}


def load_labels(db_path: Path) -> dict[str, dict]:
    conn = db.connect(db_path)
    try:
        return {row["paper_id"]: dict(row)
                for row in conn.execute("SELECT * FROM validation_labels")}
    finally:
        conn.close()


def load_rules(task: str, version: str | None) -> dict[str, str]:
    """Rule id -> its text, from the promptbook the round ran under.

    Returns empty rather than refusing when the version is unknown or the file
    has gone: rule text is a reading aid, and losing it must not cost the join.
    """
    if not version or not task:
        return {}
    path = ROOT / "promptbooks" / version / f"{task}.md"
    if not path.is_file():
        return {}
    return extract_rules(path.read_text(encoding="utf-8"))


def extract_rules(text: str) -> dict[str, str]:
    rules: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        match = RULE_START.match(line)
        if match:
            if current:
                rules[current] = " ".join(buffer).strip()
            current, buffer = match.group(1), [line[match.end():].strip()]
        elif current is not None:
            # A heading, or any unindented line, ends the list item.
            if line.startswith("#") or (line.strip() and not line.startswith((" ", "\t"))):
                rules[current] = " ".join(buffer).strip()
                current, buffer = None, []
            elif line.strip():
                buffer.append(line.strip())
    if current:
        rules[current] = " ".join(buffer).strip()
    return rules


# -------------------------------------------------------------------- fields

def outcome_of(*, status: str, truth: str | None, decision: str) -> str:
    """Mirrors evaluate._classification_outcome so this table and cases.csv use
    one vocabulary. Unscoreable rows are named, never folded into a cell of the
    confusion matrix."""
    if status != "ok":
        return "failed"
    if decision in ("undecidable", "wrong_text"):
        return decision
    if truth not in ("yes", "no") or decision not in ("yes", "no"):
        return "unlabelled"
    if truth == "yes":
        return "true_positive" if decision == "yes" else "false_negative"
    return "true_negative" if decision == "no" else "false_positive"


def sort_key(row: dict) -> tuple:
    """Worst outcome first, then most confident first -- a confident error is
    the one worth reading."""
    try:
        confidence = -float(row.get("confidence") or "")
    except (TypeError, ValueError):
        confidence = 0.0
    outcome = row.get("outcome", "")
    order = OUTCOME_ORDER.index(outcome) if outcome in OUTCOME_ORDER else len(OUTCOME_ORDER)
    return (order, confidence, row.get("paper_id", ""))


def tally(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = row.get("outcome", "")
        counts[key] = counts.get(key, 0) + 1
    return counts


def build_rows(checked_path: Path, *, manifest: dict[str, dict],
               labels: dict[str, dict]) -> tuple[list[dict], dict]:
    with checked_path.open(encoding="utf-8", newline="") as handle:
        checked = list(csv.DictReader(handle))
    if not checked:
        raise rr.Refuse(f"{checked_path} has no rows")

    environment = run_environment(checked_path)
    version = environment.get("promptbook_version") or ""

    rows: list[dict] = []
    for record in checked:
        paper_id = record["paper_id"]
        task = record.get("task") or environment.get("task") or ""
        meta = manifest.get(paper_id, {})
        label = labels.get(paper_id)
        truth = db.expected_decision(label, task) if label and task in db.TASKS else None
        status = record.get("status") or ""
        decision = record.get("decision") or ""
        rows.append({
            "paper_id": paper_id,
            "title": meta.get("title", ""),
            "first_author": meta.get("first_author", ""),
            "year": meta.get("year", ""),
            "journal": meta.get("journal", ""),
            "doi": meta.get("doi", ""),
            "task": task,
            "round": record.get("round", ""),
            "promptbook_version": version,
            "split": (label or {}).get("split") or "",
            "truth": truth or "",
            "decision": decision,
            "outcome": outcome_of(status=status, truth=truth, decision=decision),
            "confidence": record.get("confidence", ""),
            "reasoning": record.get("reasoning", ""),
            "promptbook_evidence": record.get("promptbook_evidence", ""),
            "cited_rules": record.get("cited_rules", ""),
            "status": status,
            "failure_kind": record.get("failure_kind", ""),
            "failure_case": record.get("failure_case", ""),
            "detail": record.get("detail", ""),
            "raw_path": record.get("raw_path", ""),
        })
    rows.sort(key=sort_key)

    return rows, {
        "checked": checked_path,
        "task": rows[0]["task"],
        "round": rows[0]["round"],
        "promptbook_version": version,
        "model": environment.get("model", ""),
        "effort": environment.get("effort", ""),
        "missing_title": sum(1 for row in rows if not row["title"]),
        "missing_truth": sum(1 for row in rows if not row["truth"]),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------- html

INLINE = ((re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
          (re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"), r"<em>\1</em>"),
          (re.compile(r"`([^`]+)`"), r"<code>\1</code>"))


def inline_markdown(text: str) -> str:
    """Escape first, then re-introduce only the three inline marks the
    promptbooks use. Nothing from a CSV cell can inject markup."""
    out = html.escape(text)
    for pattern, replacement in INLINE:
        out = pattern.sub(replacement, out)
    return out


def rule_block(row: dict, rules: dict[str, str], *, missing: str) -> str:
    # 21_check_responses writes `";".join(decision.cited_rules())`. Commas are
    # tolerated so a hand-edited table still renders.
    ids = [part.strip() for part in SPLIT_RULES.split(row.get("cited_rules") or "")
           if part.strip()]
    if not ids:
        evidence = (row.get("promptbook_evidence") or "").strip()
        if not evidence:
            return ""
        return f'<div class="rule"><span class="rid">{html.escape(evidence)}</span></div>'
    parts = []
    for rule_id in ids:
        text = rules.get(rule_id)
        body = (inline_markdown(text) if text
                else f'<span class="unknown">{html.escape(missing)}</span>')
        parts.append(
            f'<div class="rule"><span class="rid">{html.escape(rule_id)}</span>{body}</div>')
    return "".join(parts)


def accuracy_of(counts: dict[str, int]) -> tuple[int, int]:
    scored = sum(counts.get(key, 0) for key in BINARY)
    correct = counts.get("true_positive", 0) + counts.get("true_negative", 0)
    return correct, scored


def render_html(rows: list[dict], meta: dict, rules: dict[str, str]) -> str:
    counts = tally(rows)
    correct, scored = accuracy_of(counts)
    accuracy = f"{correct / scored:.1%}" if scored else "—"
    # An unresolvable rule and an unknown promptbook are different findings: the
    # first is a citation to check, the second is missing provenance.
    missing = ("rule text unavailable: this round has no run_environment.json, "
               "so the promptbook it ran under is unrecorded"
               if not meta.get("promptbook_version")
               else "not found in this promptbook")

    chips = [f'<button class="chip active" data-outcome="all">all <b>{len(rows)}</b></button>']
    for key in OUTCOME_ORDER:
        if counts.get(key):
            chips.append(f'<button class="chip {key}" data-outcome="{key}">'
                         f'{OUTCOME_LABEL[key]} <b>{counts[key]}</b></button>')

    cards = []
    for row in rows:
        outcome = row.get("outcome", "")
        title = html.escape(row.get("title") or row.get("paper_id", ""))
        byline = " ".join(part for part in (row.get("first_author", ""),
                                            row.get("year", "")) if part)
        try:
            confidence = f'{float(row.get("confidence") or ""):.2f}'
        except (TypeError, ValueError):
            confidence = "—"
        facts = [f'<span>truth <b>{html.escape(row.get("truth") or chr(8212))}</b></span>',
                 f'<span>model <b>{html.escape(row.get("decision") or chr(8212))}</b></span>',
                 f'<span>conf <b>{confidence}</b></span>']
        if row.get("split"):
            facts.append(f'<span>{html.escape(row["split"])}</span>')
        detail = ""
        if outcome == "failed" and row.get("detail"):
            case = row.get("failure_case") or ""
            detail = (f'<div class="detail"><b>'
                      f'{html.escape(row.get("failure_kind") or "failed")}'
                      f'{" " + html.escape(case) if case else ""}</b> '
                      f'{html.escape(row["detail"])}</div>')
        reasoning = (f'<blockquote>{html.escape(row["reasoning"])}</blockquote>'
                     if row.get("reasoning") else "")
        cards.append(f"""<article class="card {outcome}" data-outcome="{outcome}">
<header><span class="tag {outcome}">{OUTCOME_LABEL.get(outcome, outcome)}</span>
<div class="who"><h2>{title}</h2>
<p>{html.escape(byline)} &middot; <code>{html.escape(row.get("paper_id", ""))}</code></p></div></header>
<div class="facts">{"".join(facts)}</div>
{rule_block(row, rules, missing=missing)}
{reasoning}
{detail}
</article>""")

    subtitle = " · ".join(part for part in (
        meta.get("task", ""),
        f'round {meta.get("round", "")}' if meta.get("round") else "",
        meta.get("promptbook_version", ""),
        meta.get("model", ""),
        f'effort {meta["effort"]}' if meta.get("effort") else "",
        f"{len(rows)} papers",
        f"accuracy {accuracy} of {scored} scored" if scored else "") if part)

    warnings = []
    if meta.get("missing_truth"):
        warnings.append(f'{meta["missing_truth"]} paper(s) carry no human label for this task')
    if meta.get("missing_title"):
        warnings.append(f'{meta["missing_title"]} paper(s) are not in the Zotero manifest')
    warning = f'<p class="warn">{html.escape(" · ".join(warnings))}</p>' if warnings else ""

    heading = f'{meta.get("task", "review")} r{meta.get("round", "")} review table'
    return TEMPLATE.format(title=html.escape(heading), subtitle=html.escape(subtitle),
                           warning=warning, chips="".join(chips), cards="\n".join(cards))


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  --bg:#fbfbfa; --card:#fff; --ink:#1a1a19; --muted:#6b6b66; --line:#e4e4e0;
  --fn:#b3261e; --fp:#a8590c; --tp:#1a7f4b; --tn:#5a5a55; --odd:#6b4ba8;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#17171a; --card:#1f1f23; --ink:#ececeb; --muted:#9a9a95; --line:#33333a;
    --fn:#ff8a80; --fp:#ffb870; --tp:#6fd39b; --tn:#9a9a95; --odd:#c0a3f0; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 -apple-system,
  BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif; }}
.wrap {{ max-width:900px; margin:0 auto; padding:32px 20px 96px; }}
h1 {{ font-size:22px; margin:0 0 4px; letter-spacing:-.01em; }}
.sub {{ color:var(--muted); font-size:13px; margin:0; }}
.warn {{ color:var(--fp); font-size:13px; margin:8px 0 0; }}
.bar {{ position:sticky; top:0; z-index:5; background:var(--bg); padding:16px 0 12px;
  border-bottom:1px solid var(--line); margin:16px 0 20px; display:flex;
  flex-wrap:wrap; gap:8px; }}
.chip {{ font:inherit; font-size:13px; padding:5px 11px; border-radius:99px; cursor:pointer;
  border:1px solid var(--line); background:var(--card); color:var(--muted); }}
.chip b {{ color:var(--ink); }}
.chip.active {{ border-color:currentColor; color:var(--ink); }}
.chip.false_negative, .tag.false_negative {{ color:var(--fn); }}
.chip.false_positive, .tag.false_positive {{ color:var(--fp); }}
.chip.true_positive, .tag.true_positive {{ color:var(--tp); }}
.chip.true_negative, .tag.true_negative {{ color:var(--tn); }}
.chip.undecidable, .chip.wrong_text, .chip.failed, .chip.unlabelled,
.tag.undecidable, .tag.wrong_text, .tag.failed, .tag.unlabelled {{ color:var(--odd); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:16px 18px; margin-bottom:12px; border-left:3px solid currentColor;
  color:var(--tn); }}
.card.false_negative {{ color:var(--fn); }}
.card.false_positive {{ color:var(--fp); }}
.card.true_positive {{ color:var(--tp); }}
.card.undecidable, .card.wrong_text, .card.failed, .card.unlabelled {{ color:var(--odd); }}
.card > * {{ color:var(--ink); }}
header {{ display:flex; gap:12px; align-items:baseline; }}
.tag {{ font-size:11px; font-weight:700; letter-spacing:.06em; text-transform:uppercase;
  white-space:nowrap; padding-top:3px; }}
.who h2 {{ font-size:15px; font-weight:600; margin:0; line-height:1.4; }}
.who p {{ margin:2px 0 0; font-size:12px; color:var(--muted); }}
.facts {{ display:flex; flex-wrap:wrap; gap:14px; font-size:12.5px; color:var(--muted);
  margin:10px 0 0; }}
.facts b {{ color:var(--ink); font-weight:600; }}
.rule {{ font-size:13px; margin:10px 0 0; padding-left:11px;
  border-left:2px solid var(--line); color:var(--muted); }}
.rid {{ display:inline-block; font:600 11px ui-monospace,SFMono-Regular,Menlo,monospace;
  color:var(--ink); background:var(--bg); border:1px solid var(--line); border-radius:4px;
  padding:1px 5px; margin-right:7px; }}
.unknown {{ font-style:italic; }}
blockquote {{ margin:10px 0 0; font-size:13.5px; color:var(--ink); }}
blockquote::before {{ content:"\\201C"; }}
blockquote::after {{ content:"\\201D"; }}
.detail {{ margin:10px 0 0; font-size:12.5px; color:var(--muted); white-space:pre-wrap;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
code {{ font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace; }}
.card[hidden] {{ display:none; }}
</style></head><body><div class="wrap">
<h1>{title}</h1><p class="sub">{subtitle}</p>{warning}
<div class="bar">{chips}</div>
{cards}
</div><script>
var chips = document.querySelectorAll('.chip');
var cards = document.querySelectorAll('.card');
chips.forEach(function (chip) {{
  chip.addEventListener('click', function () {{
    var want = chip.dataset.outcome;
    chips.forEach(function (other) {{ other.classList.toggle('active', other === chip); }});
    cards.forEach(function (card) {{
      card.hidden = want !== 'all' && card.dataset.outcome !== want;
    }});
  }});
}});
</script></body></html>
"""


def rules_for_csv(rows: list[dict]) -> dict[str, str]:
    """Rule text for an already-written table. The CSV carries the task and the
    promptbook version on every row, so re-rendering needs no database."""
    rules: dict[str, str] = {}
    for task, version in {(row.get("task", ""), row.get("promptbook_version", ""))
                          for row in rows}:
        rules.update(load_rules(task, version))
    return rules


def meta_for_csv(rows: list[dict], path: Path) -> dict:
    first = rows[0]
    environment = run_environment(
        CHECKED / f'{path.stem.removesuffix("_review_table")}.csv')
    return {
        "task": first.get("task", ""), "round": first.get("round", ""),
        "promptbook_version": first.get("promptbook_version", ""),
        "model": environment.get("model", ""), "effort": environment.get("effort", ""),
        "missing_title": sum(1 for row in rows if not row.get("title")),
        "missing_truth": sum(1 for row in rows if not row.get("truth")),
    }


# --------------------------------------------------------------------- shell

def show(path: Path) -> str:
    return str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)


def build_one(checked_path: Path, *, manifest: dict[str, dict], labels: dict[str, dict],
              out: Path | None, want_html: bool) -> dict:
    rows, meta = build_rows(checked_path, manifest=manifest, labels=labels)
    target = out or OUT_ROOT / f"{checked_path.stem}_review_table.csv"
    write_csv(target, rows)

    counts = tally(rows)
    correct, scored = accuracy_of(counts)
    print(f"\n  {checked_path.name}")
    print(f"    promptbook : {meta['promptbook_version'] or 'unknown (no run_environment.json)'}")
    line = f"    papers     : {len(rows)}"
    if scored:
        line += f"   scored {scored}   accuracy {correct / scored:.1%}"
    print(line)
    print("    outcomes   : " + "  ".join(
        f"{OUTCOME_LABEL[key]} {counts[key]}" for key in OUTCOME_ORDER if counts.get(key)))
    if meta["missing_truth"]:
        print(f"    no label   : {meta['missing_truth']} paper(s)")
    if meta["missing_title"]:
        print(f"    no title   : {meta['missing_title']} paper(s) missing from the manifest")
    print(f"    csv   -> {show(target)}")

    if want_html:
        rules = load_rules(meta["task"], meta["promptbook_version"])
        page = target.with_suffix(".html")
        page.write_text(render_html(rows, meta, rules), encoding="utf-8")
        print(f"    html  -> {show(page)}")
    return meta


def render_existing(source: Path) -> int:
    if not source.is_file():
        raise rr.Refuse(f"{source} does not exist")
    with source.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise rr.Refuse(f"{source} has no rows")
    if "outcome" not in rows[0]:
        raise rr.Refuse(
            f"{source} has no `outcome` column, so it is not a review table. "
            f"Build one with --task/--round first")
    rows.sort(key=sort_key)
    page = source.with_suffix(".html")
    page.write_text(render_html(rows, meta_for_csv(rows, source), rules_for_csv(rows)),
                    encoding="utf-8")
    print(f"  html  -> {show(page)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One review table per checked task/round: title, human label, "
                    "model decision, reasoning, and the rule it cited.")
    parser.add_argument("--task", choices=list(db.TASKS))
    parser.add_argument("--round", type=int, dest="round_no")
    parser.add_argument("--all-rounds", action="store_true",
                        help="Build every checked report (optionally filtered by --task) "
                             "into its own table")
    parser.add_argument("--promptbook-version",
                        help="Disambiguate when one task/round has several checked reports")
    parser.add_argument("--db", type=Path, default=db.DEFAULT_PATH)
    parser.add_argument("--out", type=Path,
                        help="Output CSV path; single-round builds only")
    parser.add_argument("--html", nargs="?", const=True, default=False, metavar="CSV",
                        help="With no value, also write an HTML page beside each CSV. "
                             "With a path, render that existing review table and exit.")
    args = parser.parse_args()

    # --html <csv>: render an existing table. No database, no manifest.
    if isinstance(args.html, str):
        return render_existing(Path(args.html))

    if args.all_rounds:
        if args.round_no is not None:
            parser.error("--all-rounds covers every round; drop --round")
        if args.out:
            parser.error("--out names one file; it cannot be used with --all-rounds")
        targets = discover_checked(args.task)
    else:
        if not args.task or args.round_no is None:
            parser.error("--task and --round are required unless you pass --all-rounds, "
                         "or --html with a CSV to render")
        targets = [locate_checked(args.task, args.round_no, args.promptbook_version)]

    manifest = load_manifest()
    labels = load_labels(args.db)

    print("REVIEW TABLE" + (f" · {len(targets)} checked reports" if len(targets) > 1 else ""))
    for checked_path in targets:
        build_one(checked_path, manifest=manifest, labels=labels,
                  out=args.out, want_html=args.html is True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except rr.Refuse as refusal:
        print(f"REFUSED: {refusal}", file=sys.stderr)
        sys.exit(2)
