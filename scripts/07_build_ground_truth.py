"""Merge the human-labeled ground truth from every institute into one CSV (PLAN.md step 4).

HOW TO RUN
    python scripts/07_build_ground_truth.py            # write data/ground_truth.csv
    python scripts/07_build_ground_truth.py --report   # print the summary, write nothing

WHY THIS EXISTS
    The two institutes delivered their labels in different file formats holding
    different fields:

      NCI    Ground Truth Raw/GroundTruthDataNCI01.xlsx     232 rows,  5 columns
      NHLBI  Ground Truth Raw/crt_review_table_112.tex      159 rows, 22 columns

    NCI recorded only the four review outcomes. NHLBI recorded those plus the
    full design extraction -- cluster counts, ICC, unit of randomization, what
    each analysis did and what it should have done. Neither file is a subset of
    the other, so this script unions them: one row per labeled paper, one column
    per distinct source field, blank where an institute did not collect it.

    Nothing is dropped and nothing is silently rewritten. Every source string is
    kept verbatim in a `*_raw` column; cleaned values sit beside them in a plain
    column. Where the two institutes used different words for the same thing
    ("secondary" vs. "secondary data analysis"), the raw wording survives and
    the normalization is visible in EXCLUSION_VOCAB below rather than buried.

OUTPUTS
    data/ground_truth.csv                       one row per labeled paper
    results/review/07_ground_truth_unjoined.csv rows whose paper_id is unresolved
    Terminal                                    reconciliation against both sources

RE-RUNNING
    Safe and idempotent; rebuilt from the source files every time. When a newer
    NHLBI extraction table arrives, drop it in Ground Truth Raw/ -- the highest
    crt_review_table_NNN.tex wins, matching the SAS reader's own convention.
"""

import argparse
import csv
import io
import json
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

RAW = ROOT / "Ground Truth Raw"
META = ROOT / "data" / "zotero_meta.jsonl"
OUT = ROOT / "data" / "ground_truth.csv"
UNJOINED = ROOT / "results" / "review" / "07_ground_truth_unjoined.csv"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Which Zotero collection each institute's labels describe. The join is scoped
# to one collection so a common surname in the other institute's folder cannot
# collide -- the same reasoning as 04_load_ground_truth.py's SOURCE_FOLDERS.
SOURCE_FOLDERS = {
    "NCI": "FinalCollectionFor Publication",
    "NHLBI": "Locked_26_01_08_337",
}
# 06_merge_validation_duplicates.py collapses papers found in both collections
# into one row carrying this marker, which matches neither name above.
BOTH_FOLDERS = "Both Validation Institutes"

# The 22 columns of the NHLBI LaTeX table, in order. Taken from the header
# comment of NHLBI_Ignore03_v11_bundle/p0101_read_nhlbi.sas so that this script
# and the SAS reader cannot drift apart.
TEX_COLUMNS = [
    "citation", "exclusion_reason", "n_trt", "n_levels", "comment_levels",
    "n_outer", "n_2nd", "n_3rd", "n_4th", "unit_rand", "ind_samp_unit",
    "restricted_rand", "icc", "n_long", "stepped_wedge", "data_done",
    "data_should", "data_correct", "data_comment", "power_done", "power_should",
    "power_correct",
]

# Columns kept verbatim as well as cleaned. These are the ones where a reviewer
# hedged in free text ("yes (close enough)") or the institutes disagreed on
# wording -- exactly the places where overwriting the source would lose meaning.
RAW_KEPT = ["exclusion_reason", "power_correct", "data_correct", "review_category",
            "restricted_rand", "stepped_wedge"]

# Free-text exclusion reasons mapped to a shared vocabulary. The two institutes
# wrote these by hand and never agreed a code list, so this mapping is the only
# place the wordings are reconciled; `exclusion_reason_raw` always holds what
# the reviewer actually typed.
EXCLUSION_VOCAB = {
    "secondary": "secondary_analysis",
    "secondary analysis": "secondary_analysis",
    "secondary data analysis": "secondary_analysis",
    "secondary outcomes": "secondary_analysis",
    "baseline": "baseline_only",
    "implementation": "implementation_study",
    "methods": "methods_paper",
    "review": "review_article",
    "qualitative": "qualitative_study",
    "pilot": "pilot_study",
    "not group randomized": "not_group_randomized",
    "not a group-randomized trial": "not_group_randomized",
    "non-randomized": "not_randomized",
    "random": "duplicate_group_random_drop",
    "second study by same group, excluded randomly": "duplicate_group_random_drop",
    "stepped wedge": "stepped_wedge_design",
}

YES_NO = {"yes": "yes", "y": "yes", "no": "no", "n": "no"}

CITE_KEY = re.compile(r"\\cite\{([^}]+)\}")
ENTRY = re.compile(r"^%\s*Entry\s+(\d+)(.*)$")
# "83. (Hershman, Bansal, et al., 2023)" -> names, year, disambiguating suffix
NCI_CITE = re.compile(r"^\s*(?:(\d+)\.)?\s*\((.+?),\s*(\d{4})([a-z]?)\)\s*$")


# --------------------------------------------------------------------------- #
# LaTeX -> plain text
# --------------------------------------------------------------------------- #

def strip_latex(text: str) -> str:
    """Remove the markup the extraction table uses, leaving the reviewer's words.

    Citations go first and whole: `\\textsuperscript{\\cite{key}}` must be
    matched before the bare `\\cite{...}` rule, or the outer braces survive as
    stray characters in the citation field.
    """
    text = re.sub(r"\\textsuperscript\{\\cite\{[^}]+\}\}", "", text)
    text = re.sub(r"\\cite\{[^}]+\}", "", text)
    text = re.sub(r"\\\\+\s*$", "", text.strip())
    text = re.sub(r"\\text(?:it|bf)\{([^}]+)\}", r"\1", text)
    text = re.sub(r"\\emph\{([^}]+)\}", r"\1", text)
    text = text.replace(r"$\sim$", "~").replace(r"\%", "%").replace(r"\&", "&")
    # Accents: \'a -> a-acute, via the combining form so the result is real text
    # rather than a mangled surname (entry 65 is "Hern\'andez-Galdamez").
    for cmd, comb in ((r"\'", "\u0301"), (r"\`", "\u0300"), (r"\^", "\u0302"),
                      (r'\"', "\u0308"), (r"\~", "\u0303")):
        text = re.sub(re.escape(cmd) + r"\{?([A-Za-z])\}?",
                      lambda m: unicodedata.normalize("NFC", m.group(1) + comb), text)
    text = re.sub(r"---", "\u2014", text)
    text = re.sub(r"[{}]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------- #
# Value cleaning
# --------------------------------------------------------------------------- #

def clean_yes_no(value: str) -> str:
    """'yes (close enough)' -> 'yes'. Returns '' when the hedge has no verdict.

    The SAS reader turns anything that is not exactly yes/no into a missing
    value, which discards two real NHLBI judgments. Reading the leading word
    keeps them, and `*_raw` preserves the qualification either way.
    """
    v = str(value or "").strip().lower()
    if not v:
        return ""
    if v in YES_NO:
        return YES_NO[v]
    lead = re.split(r"[\s(,\u2014-]", v, maxsplit=1)[0]
    return YES_NO.get(lead, "")


def clean_exclusion(value: str) -> str:
    v = re.sub(r"\s+", " ", str(value or "").strip().lower())
    if not v:
        return ""
    return EXCLUSION_VOCAB.get(v, "other")


def clean_restricted(value: str) -> str:
    """The NHLBI column mixes a yes/no answer with a description of the scheme.

    31 of the 87 included papers wrote something like 'yes, stratified by
    department'; others wrote just 'stratified' or 'none'. This reduces it to
    the yes/no flag the SAS reader derives as rr_flag, and leaves the
    description in restricted_rand_raw.
    """
    v = str(value or "").strip().lower()
    if not v:
        return ""
    if v in ("none", "no"):
        return "no"
    if v == "unclear":
        return "unclear"
    return "yes"


def clean_int(value: str) -> str:
    """Numeric where the cell is a plain integer, blank where it is prose.

    Cells hold things like '5000-20000', '~1 per hospital (one has 4)' and
    'up to 28'. Guessing a number out of those would invent precision the
    reviewer did not record, so they stay blank here and readable in the raw.
    """
    v = str(value or "").strip()
    return v if re.fullmatch(r"\d+", v) else ""


# --------------------------------------------------------------------------- #
# Source readers
# --------------------------------------------------------------------------- #

def read_nci(path: Path) -> list[dict]:
    """GroundTruthDataNCI01.xlsx -> row dicts.

    Five columns: Citation, Reason excluded, Power, Stats, Review Category. A
    paper carries either an exclusion reason or the three outcome columns,
    never both -- the gate showing up in the source data.
    """
    frame = pd.read_excel(path, sheet_name="Combined")
    rows = []
    for position, record in enumerate(frame.to_dict("records"), start=1):
        citation = str(record.get("Citation", "") or "").strip()
        match = NCI_CITE.match(citation)
        rows.append({
            "source_institute": "NCI",
            "source_file": path.name,
            "source_row": match.group(1) if match else str(position),
            "citation_raw": citation,
            "cite_key": "",
            "exclusion_reason_raw": _text(record.get("Reason excluded")),
            "power_correct_raw": _text(record.get("Power")),
            "data_correct_raw": _text(record.get("Stats")),
            "review_category_raw": _text(record.get("Review Category")),
        })
    return rows


def read_nhlbi(path: Path) -> list[dict]:
    """crt_review_table_NNN.tex -> row dicts.

    Entries are `% Entry N` comments followed by one `&`-delimited data row.
    The `>= 20` ampersand test is the SAS reader's own, and it is what makes the
    parse robust: 14 rows end a column early (an excluded paper whose trailing
    empty cell was never delimited) and would be missed by an exact count.
    """
    rows = []
    entry_num = note = None
    for line in path.read_text(encoding="utf-8").split("\n"):
        stripped = line.strip()
        header = ENTRY.match(stripped)
        if header:
            entry_num, note = header.group(1), header.group(2).strip(" -")
            continue
        if entry_num is None or stripped.count("&") < 20:
            continue

        cite = CITE_KEY.search(stripped)
        fields = [f.strip() for f in strip_latex(stripped).split("&")]
        fields += [""] * (len(TEX_COLUMNS) - len(fields))  # short rows pad right

        row = {
            "source_institute": "NHLBI",
            "source_file": path.name,
            "source_row": entry_num,
            "citation_raw": fields[0],
            "cite_key": cite.group(1) if cite else "",
            "source_note": note,
        }
        for name, value in zip(TEX_COLUMNS[1:], fields[1:]):
            row[f"{name}_raw" if name in RAW_KEPT else name] = value
        rows.append(row)
        entry_num = note = None
    return rows


def _text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


# --------------------------------------------------------------------------- #
# Derived columns
# --------------------------------------------------------------------------- #

def derive(row: dict) -> dict:
    """Add the cleaned and computed columns beside the raw ones."""
    row["exclusion_reason"] = clean_exclusion(row.get("exclusion_reason_raw", ""))
    row["power_correct"] = clean_yes_no(row.get("power_correct_raw", ""))
    row["data_correct"] = clean_yes_no(row.get("data_correct_raw", ""))
    row["review_category"] = row.get("review_category_raw", "").strip().upper()
    row["restricted_rand"] = clean_restricted(row.get("restricted_rand_raw", ""))
    row["stepped_wedge"] = clean_yes_no(row.get("stepped_wedge_raw", ""))
    for name in ("n_trt", "n_levels", "n_long"):
        row[name] = clean_int(row.get(name, ""))

    row["excluded"] = "1" if row["exclusion_reason"] else "0"
    # A cited paper with no fields filled in has not been reviewed yet; that is
    # different from a paper reviewed and kept, and conflating the two would put
    # 23 unreviewed NHLBI papers into the accuracy denominator as gate survivors.
    row["labeled"] = "0" if not (row["exclusion_reason"] or row["power_correct"]
                                 or row["data_correct"] or row["review_category"]) else "1"
    return row


# --------------------------------------------------------------------------- #
# Join to Zotero paper_ids
# --------------------------------------------------------------------------- #

def load_meta() -> dict:
    records = {}
    with open(META, encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            records[record["paper_id"]] = record
    return records


def surname(text: str) -> str:
    """Last whitespace-separated token, accent- and case-folded.

    Curly apostrophes are folded to ASCII first: the NCI spreadsheet writes
    "O'Connor" with U+2019 while Zotero holds U+0027, and without this the two
    reduce to "connor" and "oconnor" and never meet.
    """
    text = str(text or "").replace("’", "'").replace("‘", "'")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    parts = re.sub(r"[^A-Za-z\s'-]", " ", text).split()
    return parts[-1].lower().replace("-", "").replace("'", "") if parts else ""


def split_cite_key(key: str) -> tuple[str, str, str]:
    """'abdullahiHydroxyureaPrimaryStroke2022' -> ('abdullahi', 'hydroxyurea primary stroke', '2022').

    Zotero's Better BibTeX builds these as surname + capitalized title words +
    year, which is why the NHLBI table can be joined at all: the tex prints only
    'Abdullahi et al.' with no year, and the bibliography it cites
    (Ignore03_NHLBI.bib) was not delivered with the bundle.

    The surname is the leading lowercase run, hyphens included, rather than the
    first word split off at a capital. 13 of the 159 NHLBI first authors are
    hyphenated -- "abrahams-gessel", "philis-tsimikas" -- and splitting on case
    alone turns the second half of the name into a title word, which loses the
    author signal the match depends on.
    """
    match = re.match(r"^(.*?)(\d{4})[a-z]?$", key)
    body, year = (match.group(1), match.group(2)) if match else (key, "")
    lead = re.match(r"^[a-z]+(?:-[a-z]+)*", body)
    author = lead.group(0) if lead else ""
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", body[len(author):])
    return author.replace("-", ""), " ".join(w.lower() for w in words), year


def candidate_pool(meta: dict, institute: str) -> dict:
    folder = SOURCE_FOLDERS[institute]
    return {pid: rec for pid, rec in meta.items()
            if rec.get("set") == "validation"
            and (folder in rec.get("folders", []) or BOTH_FOLDERS in rec.get("folders", []))}


def join_nhlbi(row: dict, pool: dict) -> tuple[str, str, str]:
    """Match a tex row to a paper_id on first author + year, then title words.

    Same two rules the NCI join uses, in the same order. First author plus year
    is decisive on its own when it is unique in the collection -- the title
    words only exist to break a tie, and letting a low title score veto a unique
    author+year hit would reject 12 correct matches whose bibtex key was built
    from a shortened title.
    """
    author, words, year = split_cite_key(row["cite_key"])
    if not author:
        return "", "", ""

    def title_score(pid: str) -> float:
        """Similarity of the key's title words to a candidate's real title.

        The squashed comparison (letters and digits only, no spaces) is there
        because Better BibTeX runs words together: "Point-of-Care" becomes
        "PointofCare", which splits back out as the non-word "pointof" and
        drags a token-based score down. Removing separators from both sides
        sidesteps the whole question of where the word boundaries were.
        """
        title = str(pool[pid].get("title", "")).lower()
        squash = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
        return max(fuzz.token_set_ratio(words, title),
                   fuzz.partial_ratio(words, title),
                   fuzz.partial_ratio(squash(words), squash(title)))

    hits = [pid for pid, rec in pool.items()
            if surname(rec.get("first_author", "")) == author
            and (not year or str(rec.get("year", "")).strip() == year)]

    if len(hits) == 1:
        return hits[0], "cite_key_author_year", f"{title_score(hits[0]):.0f}"
    if len(hits) > 1:
        ranked = sorted(hits, key=title_score, reverse=True)
        best, second = title_score(ranked[0]), title_score(ranked[1])
        # A tie needs the title to actually distinguish them, not merely to win.
        if best >= 70 and best - second >= 10:
            return ranked[0], "cite_key_title_tiebreak", f"{best:.0f}"
        return "", "", f"{best:.0f}"

    # No author hit. A corporate author is why: entry 69's first author is
    # "ICU-RESUS and Eunice Kennedy Shriver National Institute of Child Health",
    # which has no surname for the heuristic to find. Fall back to the title
    # alone, but only when it is near-exact AND the winner is the sole plausible
    # candidate -- a title match with a rival is not evidence, it is a coin toss.
    scored = sorted(((title_score(pid), pid) for pid in pool), reverse=True)
    if scored and scored[0][0] >= 90 and (len(scored) == 1 or scored[1][0] < 70):
        return scored[0][1], "title_only_corporate_author", f"{scored[0][0]:.0f}"
    return "", "", f"{scored[0][0]:.0f}" if scored else ""


def join_nci(row: dict, pool: dict, index: dict) -> tuple[str, str, str]:
    """Match an APA citation to a paper_id, the way 04_load_ground_truth.py does.

    Rule 1: first author + year unique in the collection.
    Rule 2: APA extends an ambiguous citation one author at a time, so the extra
            surnames are compared by *position* -- the same lab publishes with
            the same people in a different order, and membership would tie.
    Anything else is left for a human; a wrong label corrupts every accuracy
    number computed after it.
    """
    match = NCI_CITE.match(row["citation_raw"])
    if not match:
        return "", "", ""
    names = re.sub(r"\bet\s+al\.?", "", match.group(2))
    parts = [p.strip() for p in re.split(r"[,&]", names) if p.strip()]
    if not parts:
        return "", "", ""
    first, extras, year, suffix = surname(parts[0]), [surname(p) for p in parts[1:]], match.group(3), match.group(4)
    if suffix:  # "2022a" means the labeller could not tell two papers apart
        return "", "", ""

    hits = index.get((first, year), [])
    if len(hits) == 1:
        return hits[0], "author_year", "100"
    for pid in hits:
        authors = [surname(a) for a in pool[pid].get("authors", [])]
        if all(i + 1 < len(authors) and authors[i + 1] == extra
               for i, extra in enumerate(extras)) and extras:
            return pid, "author_position", "100"
    return "", "", ""


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def newest_tex() -> Path:
    files = sorted(RAW.glob("crt_review_table_*.tex"),
                   key=lambda p: int(re.search(r"(\d+)", p.stem).group(1)))
    if not files:
        raise SystemExit(f"No crt_review_table_NNN.tex found in {RAW}")
    return files[-1]


def column_order(rows: list[dict]) -> list[str]:
    """Identity, then the four review outcomes, then the design extraction."""
    lead = ["paper_id", "source_institute", "source_file", "source_row",
            "citation_raw", "cite_key", "matched_by", "match_score",
            "labeled", "excluded",
            "exclusion_reason", "exclusion_reason_raw",
            "power_correct", "power_correct_raw",
            "data_correct", "data_correct_raw",
            "review_category", "review_category_raw"]
    rest = [c for c in TEX_COLUMNS[1:] if c not in
            ("exclusion_reason", "power_correct", "data_correct")]
    rest = [f"{c}_raw" if c in RAW_KEPT else c for c in rest]
    rest = [c for c in rest if c not in lead]
    tail = ["restricted_rand", "stepped_wedge", "source_note"]
    seen, ordered = set(), []
    for column in lead + rest + tail:
        if column not in seen:
            seen.add(column)
            ordered.append(column)
    for row in rows:  # nothing silently vanishes if a source gains a field
        for column in row:
            if column not in seen:
                seen.add(column)
                ordered.append(column)
    return ordered


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--report", action="store_true",
                        help="print the summary without writing any file")
    args = parser.parse_args()

    nci_path = RAW / "GroundTruthDataNCI01.xlsx"
    tex_path = newest_tex()
    print(f"NCI   : {nci_path.name}")
    print(f"NHLBI : {tex_path.name}")

    rows = [derive(r) for r in read_nci(nci_path)] + [derive(r) for r in read_nhlbi(tex_path)]

    meta = load_meta()
    pools = {inst: candidate_pool(meta, inst) for inst in SOURCE_FOLDERS}
    nci_index: dict = {}
    for pid, rec in pools["NCI"].items():
        nci_index.setdefault((surname(rec.get("first_author", "")),
                              str(rec.get("year", "")).strip()), []).append(pid)

    for row in rows:
        if row["source_institute"] == "NCI":
            pid, how, score = join_nci(row, pools["NCI"], nci_index)
        else:
            pid, how, score = join_nhlbi(row, pools["NHLBI"])
        row["paper_id"], row["matched_by"], row["match_score"] = pid, how, score

    columns = column_order(rows)
    for row in rows:
        for column in columns:
            row.setdefault(column, "")

    report(rows, pools)

    if args.report:
        print("\n--report: nothing written.")
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {OUT.relative_to(ROOT)}  ({len(rows)} rows x {len(columns)} columns)")

    unjoined = [r for r in rows if not r["paper_id"]]
    UNJOINED.parent.mkdir(parents=True, exist_ok=True)
    with open(UNJOINED, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "source_institute", "source_file", "source_row", "citation_raw",
            "cite_key", "match_score", "labeled"])
        writer.writeheader()
        for row in unjoined:
            writer.writerow({k: row[k] for k in writer.fieldnames})
    print(f"wrote {UNJOINED.relative_to(ROOT)}  ({len(unjoined)} rows for a human)")


def report(rows: list[dict], pools: dict) -> None:
    print()
    print(f"{'':10s} {'rows':>6s} {'labeled':>8s} {'excluded':>9s} "
          f"{'kept':>6s} {'joined':>7s} {'PDFs':>6s}")
    for inst in ("NCI", "NHLBI"):
        sub = [r for r in rows if r["source_institute"] == inst]
        labeled = [r for r in sub if r["labeled"] == "1"]
        print(f"{inst:10s} {len(sub):6d} {len(labeled):8d} "
              f"{sum(r['excluded'] == '1' for r in sub):9d} "
              f"{sum(r['excluded'] == '0' and r['labeled'] == '1' for r in sub):6d} "
              f"{sum(bool(r['paper_id']) for r in sub):7d} {len(pools[inst]):6d}")
    labeled_all = [r for r in rows if r["labeled"] == "1"]
    print(f"{'TOTAL':10s} {len(rows):6d} {len(labeled_all):8d} "
          f"{sum(r['excluded'] == '1' for r in rows):9d} "
          f"{sum(r['excluded'] == '0' and r['labeled'] == '1' for r in rows):6d} "
          f"{sum(bool(r['paper_id']) for r in rows):7d} "
          f"{sum(len(p) for p in pools.values()):6d}")

    unreviewed = [r for r in rows if r["labeled"] == "0"]
    if unreviewed:
        print(f"\ncited but not yet reviewed: {len(unreviewed)} "
              f"(entries {', '.join(r['source_row'] for r in unreviewed[:12])}"
              f"{', ...' if len(unreviewed) > 12 else ''})")

    kept = [r for r in rows if r["excluded"] == "0" and r["labeled"] == "1"]
    for field in ("power_correct", "data_correct"):
        counts: dict = {}
        for row in kept:
            counts[row[field] or "(blank)"] = counts.get(row[field] or "(blank)", 0) + 1
        print(f"{field:16s} {counts}")

    hedged = [r for r in rows if r.get(f"power_correct_raw", "").strip().lower()
              not in ("", "yes", "no")]
    hedged += [r for r in rows if r.get("data_correct_raw", "").strip().lower()
               not in ("", "yes", "no")]
    if hedged:
        print(f"\nfree-text correctness values kept (SAS reads these as missing):")
        for row in hedged:
            print(f"  {row['source_institute']} entry {row['source_row']}: "
                  f"power={row['power_correct_raw']!r} -> {row['power_correct']!r}, "
                  f"data={row['data_correct_raw']!r} -> {row['data_correct']!r}")

    other = sorted({r["exclusion_reason_raw"] for r in rows
                    if r["exclusion_reason"] == "other"})
    if other:
        print(f"\nexclusion reasons not in EXCLUSION_VOCAB: {other}")


if __name__ == "__main__":
    main()
