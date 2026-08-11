"""Does this PDF actually contain the paper Zotero says it does?

md5 verification at fetch time proves the bytes arrived intact. It says nothing
about whether the *right* file was attached to the record. This module answers
that second question, comparing the PDF's front matter against Zotero metadata.

The failure it exists to catch is real and present in this corpus: two records
sampled during development held NIH *grant summary statements* ("Program
Contact... Application Number 1 R01 CA243552-01") instead of the published
article. Both scored 80 and 84 on title similarity, against 96-100 for genuine
matches -- the gap the thresholds below sit in.

Pure functions, no I/O: the caller supplies text and metadata. That keeps the
rules testable, and lets classification-time re-checks (PLAN.md step 1) reuse
the same ladder rather than reimplementing it.

Signals, and why these three:
    doi_hit           Zotero's DOI appears in the text. Objective; found in 95%
                      of sampled PDFs, and the single strongest evidence.
    title_score       Fuzzy title similarity, 0-100.
    first_author_hit  First author's surname present as a whole word.

PMID and PMCID were measured and dropped: they appear in the text of 1% and 0%
of PDFs respectively. Zotero holds them, the documents do not print them.

author_frac is recorded but deliberately NOT gated on -- consortium papers list
30+ authors whose names run past page 2, so a low fraction is normal and means
nothing. First-author presence carries the author signal instead.
"""

import re
import unicodedata

from rapidfuzz import fuzz

# Verdicts, in the order the ladder assigns them.
VERIFIED = "VERIFIED"          # enters the corpus
WEAK = "WEAK"                  # enters flagged; re-checked at classification
MISMATCH = "MISMATCH"          # blocked, needs a human
PDF_UNREADABLE = "PDF_UNREADABLE"  # nothing to check against

# Why a verdict was reached. Stored alongside the verdict so a decision can be
# explained without re-deriving it.
REASON_DOI = "DOI_MATCH"
REASON_TITLE_AUTHOR = "TITLE_AUTHOR_MATCH"
REASON_TITLE_NEAR = "TITLE_NEAR_MATCH"
REASON_AUTHORS_ONLY = "AUTHORS_ONLY"
REASON_NO_MATCH = "NO_MATCH"
REASON_NO_TEXT = "NO_TEXT"
REASON_ADMIN_DOC = "ADMIN_DOCUMENT"

# Phrases that identify a document as grant paperwork rather than a paper: an
# NIH/PCORI summary statement or study-section review sheet.
#
# This check exists because title similarity cannot catch these. A grant and
# the paper it funds share a title, and the PI is usually the first author, so
# a summary statement scores 96+ on title and passes the author check -- two
# were VERIFIED on those grounds before this rule was added.
#
# Measured over all 2063 PDFs: these three phrases flag 12 documents and every
# one is grant paperwork. Weaker candidates were tested and rejected --
# "principal investigator:" hit 8 papers of which 7 were genuine (it appears in
# funding statements), and "consort-ehealth" hit 6 of which 3 were real papers
# citing the reporting checklist.
_ADMIN_MARKERS = [
    re.compile(r"privileged\s+communication"),
    re.compile(r"\bsummary\s+statement\b"),
    re.compile(r"resume\s+and\s+summar\w*\s+of\s+discussion"),
]

# Only the document's opening counts. A methods paper may legitimately discuss
# summary statements in its body; grant paperwork announces itself in the
# header. Every one of the 12 measured hits fell within the first 120
# characters, so this bound is generous.
ADMIN_HEAD_CHARS = 1500

# Tuned against the measured distribution, which is sharply bimodal: in a
# 250-PDF sample every genuine match scored >= 96 and every wrong document
# scored <= 84. Nothing legitimate was observed between 85 and 95, so these
# thresholds sit inside an empty gap rather than splitting a crowded one.
TITLE_VERIFIED = 95   # with the first author present, enough on its own
TITLE_NEAR = 85       # close enough to be worth a human glance, not to trust
AUTHOR_FRAC_NEAR = 0.5

# A 2-page head thinner than this has no usable text layer -- a scanned image.
# Genuine extractions in the sample ran 4,700-11,000 characters; the one
# scanned PDF produced 1.
MIN_HEAD_CHARS = 200

_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}

_DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+")


def normalize(text: str) -> str:
    """Fold text to bare lowercase words for fuzzy comparison.

    Strips accents, expands ligatures (PDF fonts emit a single 'ﬁ' glyph),
    rejoins words hyphenated across a line break, and drops punctuation. Titles
    wrap mid-word in two-column layouts, so without the de-hyphenation step a
    correct title can score well below its true similarity.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    for glyph, plain in _LIGATURES.items():
        text = text.replace(glyph, plain)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"-\s*\n\s*", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _compact(text: str) -> str:
    """Lowercase with all whitespace removed.

    DOIs and titles routinely break across lines mid-token. Comparing with
    whitespace deleted makes that irrelevant. Punctuation is kept, because a
    DOI is mostly punctuation.
    """
    return re.sub(r"\s+", "", (text or "").lower())


def doi_in_text(doi: str, text: str) -> bool:
    """True if this DOI appears in the text, ignoring line breaks inside it."""
    if not doi:
        return False
    return _compact(doi) in _compact(text)


def find_other_dois(doi: str, text: str) -> list[str]:
    """DOIs in the text that are not the expected one.

    Informational only. Pages 1-2 occasionally reach a reference list, and a
    cited DOI is not evidence of a wrong file -- so this never drives the
    verdict by itself, it only annotates one.
    """
    expected = _compact(doi)
    found = []
    for match in _DOI_PATTERN.findall(text or ""):
        candidate = match.rstrip(".,;)")
        if _compact(candidate) != expected and candidate not in found:
            found.append(candidate)
    return found


def title_similarity(title: str, text: str) -> float:
    """Similarity of a title to the document's front matter, 0-100.

    Two measures, best one wins:
      - token_set_ratio, which tolerates the title being a small island in a
        large page and ignores word order.
      - partial_ratio with whitespace removed, which survives a title broken
        across lines and columns.

    Journals retitle papers between accepted manuscript and published version
    ("Sub-analyses" vs "Subgroup Analyses" was found in this corpus), so this
    is a similarity, never an equality test.
    """
    title_n = normalize(title)
    if not title_n:
        return 0.0
    text_n = normalize(text)
    if not text_n:
        return 0.0
    return max(
        fuzz.token_set_ratio(title_n, text_n),
        fuzz.partial_ratio(title_n.replace(" ", ""), text_n.replace(" ", "")),
    )


def title_position(title: str, text: str) -> float:
    """Where the title turns up, as a fraction (0=top, 1=end). -1 if not found.

    Informational, never part of the verdict -- but decisive when triaging by
    hand. A paper prints its title at the top; a title found two-thirds of the
    way down is usually sitting in a reference list, meaning the PDF is a
    *different* article that merely cites the one Zotero names. Exactly that
    was found in this corpus (AULRV66J: title at char 4012 of 6280, inside the
    references of an unrelated Ophthalmology paper).
    """
    title_n = normalize(title)
    text_n = normalize(text)
    if not title_n or not text_n:
        return -1.0
    # A prefix long enough to be distinctive, short enough to survive the
    # journal's retitling between accepted and published versions.
    probe = title_n[:45]
    index = text_n.find(probe)
    if index < 0:
        return -1.0
    return round(index / len(text_n), 3)


def surname_present(surname: str, text_n: str) -> bool:
    """True if a surname appears as a whole word in already-normalized text.

    Whole-word matching matters: short surnames like 'Li' or 'Ng' would
    otherwise match inside unrelated words and manufacture false agreement.

    Only *letters* are allowed to block a match, not digits. Author lines carry
    affiliation superscripts that extraction glues straight onto the surname --
    "Ye Zhang1,2*, Jianjun Li3*" -- and a plain \\b boundary fails on every one
    of them, because the digit counts as a word character. That silently
    reported 0/13 authors on papers whose authors were all plainly present.
    """
    surname_n = normalize(surname)
    if len(surname_n) < 2:
        return False
    return re.search(rf"(?<![a-z]){re.escape(surname_n)}(?![a-z])", text_n) is not None


def looks_administrative(head_text: str) -> bool:
    """True if the document opens like grant paperwork rather than a paper."""
    opening = re.sub(r"\s+", " ", (head_text or "")[:ADMIN_HEAD_CHARS]).lower()
    return any(marker.search(opening) for marker in _ADMIN_MARKERS)


def compute_signals(head_text: str, meta: dict) -> dict:
    """Measure every identity signal for one PDF against its Zotero record.

    `meta` is a record from data/zotero_meta.jsonl -- it needs every author,
    which the manifest CSV does not carry.
    """
    head_text = head_text or ""
    text_n = normalize(head_text)

    authors = [a for a in (meta.get("authors") or []) if a]
    hits = [a for a in authors if surname_present(a, text_n)]

    doi = meta.get("doi") or ""
    year = str(meta.get("year") or "")

    return {
        "head_chars": len(head_text),
        "admin_doc": looks_administrative(head_text),
        "doi_hit": doi_in_text(doi, head_text),
        "other_dois": find_other_dois(doi, head_text),
        "title_score": round(title_similarity(meta.get("title", ""), head_text), 1),
        "title_pos": title_position(meta.get("title", ""), head_text),
        "first_author_hit": bool(authors) and surname_present(authors[0], text_n),
        "author_hits": len(hits),
        "author_count": len(authors),
        "author_frac": round(len(hits) / len(authors), 3) if authors else 0.0,
        "year_hit": bool(year) and year in head_text,
        "journal_hit": bool(meta.get("journal"))
        and normalize(meta["journal"]) in text_n,
    }


def decide(signals: dict) -> tuple[str, str, str]:
    """Turn signals into (verdict, reason, explanation).

    An ordered ladder, first rule to fire wins. Ordered strongest evidence
    first so the reason attached to a paper is always the best evidence that
    was available for it, not merely the first thing that happened to pass.

      1. No text at all         -> PDF_UNREADABLE. Nothing can be checked.
      2. Grant paperwork        -> MISMATCH. Not a paper, whatever it scores.
      3. DOI found              -> VERIFIED. Objective and unforgeable.
      4. Title >= 95 + author   -> VERIFIED. No DOI printed (common on accepted
                                   manuscripts), but title and authorship agree.
      5. Title >= 85            -> WEAK. Plausibly right, below the bar to trust.
      6. Most authors present   -> WEAK. Title unusable (garbled extraction),
                                   but the authorship lines up.
      7. Otherwise              -> MISMATCH. Blocked.

    Rule 2 sits above the DOI check deliberately. A summary statement that
    happens to cite the DOI of the paper it funded is still not that paper, and
    a wrong document entering the corpus is far more costly than a correct one
    being sent for review.
    """
    if signals["head_chars"] < MIN_HEAD_CHARS:
        return (
            PDF_UNREADABLE,
            REASON_NO_TEXT,
            f"only {signals['head_chars']} characters on pages 1-2; no text layer (likely a scan)",
        )

    if signals.get("admin_doc"):
        return (
            MISMATCH,
            REASON_ADMIN_DOC,
            "document opens as grant paperwork (summary statement / review sheet), not a journal article",
        )

    if signals["doi_hit"]:
        return VERIFIED, REASON_DOI, "Zotero's DOI appears in the document"

    if signals["title_score"] >= TITLE_VERIFIED and signals["first_author_hit"]:
        return (
            VERIFIED,
            REASON_TITLE_AUTHOR,
            f"title matches ({signals['title_score']}) and first author present; no DOI in text",
        )

    if signals["title_score"] >= TITLE_NEAR:
        detail = "first author present" if signals["first_author_hit"] else "first author NOT found"
        return (
            WEAK,
            REASON_TITLE_NEAR,
            f"title similarity {signals['title_score']} below the {TITLE_VERIFIED} bar; {detail}",
        )

    if signals["first_author_hit"] and signals["author_frac"] >= AUTHOR_FRAC_NEAR:
        return (
            WEAK,
            REASON_AUTHORS_ONLY,
            f"title similarity only {signals['title_score']}, but "
            f"{signals['author_hits']}/{signals['author_count']} authors present",
        )

    return (
        MISMATCH,
        REASON_NO_MATCH,
        f"no DOI, title similarity {signals['title_score']}, "
        f"{signals['author_hits']}/{signals['author_count']} authors present",
    )


def verify(head_text: str, meta: dict) -> dict:
    """Measure, then decide. Returns the signals plus verdict/reason/explanation."""
    signals = compute_signals(head_text, meta)
    verdict, reason, explanation = decide(signals)
    return {**signals, "verdict": verdict, "verdict_reason": reason, "explanation": explanation}
