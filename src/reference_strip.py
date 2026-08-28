"""Cut the bibliography off a cached paper, offline, before anything is spent.

WHY THIS EXISTS
    References are the largest block of text in the corpus that no criterion
    reads. Measured over all 1783 cached papers on 2026-08-28: a standalone
    references heading is detectable in 1747 of them (98%), and what follows it
    is a mean 22.3% of the document. That is 22% of every paid request spent on
    text that decides nothing.

    Worse than free, in fact. A bibliography is dense with the exact phrases the
    gate looks for -- "stepped wedge", "pilot", "secondary analysis", "cluster
    randomized" -- attached to papers that are not the paper under review. Every
    one of those is a false-positive surface for E1-E18, and the model has no way
    to tell a cited title from a claim the paper is making about itself.

WHY IT IS A SEPARATE PASS AND NOT PART OF `clean_paper_text`
    DC6 says a PDF is parsed exactly once and the cache is authoritative. This
    does not touch that cache: it reads `data/extracted_text/` and writes an
    independent, regenerable copy to `data/extracted_text_stripped/` under the
    same filenames. The Reading Room reads the stripped copy; the original is
    never modified, never deleted, and is what this pass is re-derived from if
    the rules below ever change.

    Doing it here rather than at send time also means the exact bytes the model
    saw are on disk, hashed, and diffable against the source -- which is what
    makes a judgment auditable after the fact.

WHAT IT WILL NOT DO
    Guess. Three guards, each of which leaves the paper whole rather than risk
    removing a method:

      * only a heading *on its own line* counts. "see the references above" in a
        paragraph is not a section break;
      * the heading must sit past `MIN_HEADING_POSITION` of the document. The
        measured minimum in this corpus is 0.465, so 0.30 is a wide margin;
      * a cut removing more than `MAX_STRIP_FRACTION` is abandoned. The measured
        maximum here is 0.535 over 1747 papers, so this fires on nothing today
        and is there for the paper that breaks the pattern later.

    A paper that trips any guard is copied through **unchanged**, with the reason
    recorded. The output directory always holds one file per input file, so the
    Reading Room's B7 check keeps its meaning: a missing file is a missing file,
    not a paper the stripper quietly declined.

APPENDICES SURVIVE
    134 papers carry an appendix or supplementary section *after* the references.
    Those routinely hold the sample-size calculation and the analysis model --
    exactly what power and data analysis are looking for -- so the tail from the
    first post-reference heading onward is spliced back on.

THE MARKER IS DELIBERATE
    Stripped text carries a `[REFERENCES SECTION REMOVED]` line where the cut
    was. Without it a paper with no bibliography reads like an abstract or a
    conference summary, which is precisely what exclusion criterion E2 ("not a
    full report") is looking for -- the trim would manufacture the exclusion it
    was supposed to be neutral about. One visible line says a section was removed
    by us, not missing from the paper.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone

# The heading forms that actually appear in this corpus, anchored to a whole
# line. Leading numerals/bullets are tolerated ("5. References", "* REFERENCES")
# and a trailing colon or period is tolerated; anything else on the line is not.
REFERENCE_HEADING = re.compile(
    r"^[\s\d\.\)\*•#]*"
    r"(references?|reference list|bibliography|works cited|literature cited)"
    r"\s*[:\.]?\s*$",
    re.IGNORECASE)

# What may follow the bibliography and must be kept. Prefix match, not a whole
# line: "Appendix A: Sample size calculation" is one line and is the thing we
# most want back.
POST_REFERENCE_HEADING = re.compile(
    r"^[\s\d\.\)\*•#]*"
    r"(appendix|appendices|supplement(ary|al)?|additional file|"
    r"supporting information|online supplement|web appendix|e-?appendix|"
    r"annex)\b",
    re.IGNORECASE)

# Guards. See the module docstring for the measurements these are set against.
MIN_HEADING_POSITION = 0.30
MAX_STRIP_FRACTION = 0.60

MARKER = "[REFERENCES SECTION REMOVED]"

# Bumped whenever the rules above change, so a stripped file states which rules
# produced it and a mixed directory is detectable rather than invisible.
STRIP_METHOD = "reference_heading_v1"

# The key the whole record lands under in the copied JSON. One nested block
# rather than loose keys: everything the extractor wrote stays exactly where it
# was, and one `in` test tells you whether a file has been through this pass.
RECORD_KEY = "references_strip"

# Reasons a paper is copied through whole. Codes, not booleans: "no heading" and
# "the cut was implausibly large" are different stories about the corpus and the
# summary counts them separately. Short slugs because this reason also lands in a
# `text_notes` CSV cell beside `bom_stripped` and `crlf_normalized`; the sentence
# for a human lives in REASON_TEXT.
NO_HEADING = "no_heading"
TOO_EARLY = "heading_too_early"
TOO_LARGE = "cut_too_large"
EMPTY = "empty"

REASON_TEXT = {
    NO_HEADING: "no standalone references heading found",
    TOO_EARLY: "references heading sits too early to be the bibliography",
    TOO_LARGE: "cut would remove more than the safety fraction",
    EMPTY: "no text to strip",
}


def explain(reason: str) -> str:
    """The human sentence for a reason code, or the code itself if unknown."""
    return REASON_TEXT.get(reason, reason)


@dataclass(frozen=True)
class StripResult:
    """The stripped text, and everything needed to audit the cut."""

    text: str
    stripped: bool
    reason: str = ""
    heading: str = ""
    heading_line: int = -1
    source_chars: int = 0
    result_chars: int = 0
    tail_chars: int = 0          # appendix text kept from after the references

    @property
    def chars_removed(self) -> int:
        return self.source_chars - self.result_chars

    @property
    def removed_fraction(self) -> float:
        return self.chars_removed / self.source_chars if self.source_chars else 0.0

    def record(self, *, source_text: str) -> dict:
        """The `references_strip` block written into the copied JSON."""
        return {
            "stripped": self.stripped,
            # The ruleset that RAN, not the outcome. A paper left whole was
            # still examined by these rules, and `is_current` has to be able to
            # re-examine it when they change.
            "method": STRIP_METHOD,
            "reason": self.reason,
            "heading": self.heading,
            "heading_line": self.heading_line,
            "source_chars": self.source_chars,
            "result_chars": self.result_chars,
            "chars_removed": self.chars_removed,
            "removed_fraction": round(self.removed_fraction, 4),
            "appendix_chars_kept": self.tail_chars,
            "source_text_sha256": sha256_text(source_text),
            "stripped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


def sha256_text(text: str) -> str:
    """Hash of the *source* text, so a stale copy is detectable, not assumed."""
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def find_reference_heading(lines: list[str]) -> int:
    """Index of the LAST standalone references heading, or -1.

    The last, not the first: a paper may print "References" under an abstract's
    key-points box, and journals increasingly repeat the word in running heads.
    The bibliography is the one nothing comes after, so scanning from the end is
    both simpler and right.
    """
    for i in range(len(lines) - 1, -1, -1):
        if REFERENCE_HEADING.match(lines[i].strip()):
            return i
    return -1


def find_post_reference_heading(lines: list[str]) -> int:
    """Index of the first appendix-like heading within the tail, or -1."""
    for i, line in enumerate(lines):
        if POST_REFERENCE_HEADING.match(line.strip()):
            return i
    return -1


def strip_references(text: str) -> StripResult:
    """Remove the bibliography, keep any appendix behind it, or refuse to cut."""
    source_chars = len(text)
    if not text.strip():
        return StripResult(text=text, stripped=False, reason=EMPTY,
                           source_chars=source_chars, result_chars=source_chars)

    lines = text.split("\n")
    index = find_reference_heading(lines)
    if index < 0:
        return StripResult(text=text, stripped=False, reason=NO_HEADING,
                           source_chars=source_chars, result_chars=source_chars)

    heading = lines[index].strip()
    body = "\n".join(lines[:index])
    if len(body) / source_chars < MIN_HEADING_POSITION:
        return StripResult(text=text, stripped=False, reason=TOO_EARLY,
                           heading=heading, heading_line=index,
                           source_chars=source_chars, result_chars=source_chars)

    tail_lines = lines[index:]
    appendix = find_post_reference_heading(tail_lines)
    kept_tail = "\n".join(tail_lines[appendix:]) if appendix > 0 else ""

    parts = [body.rstrip(), MARKER]
    if kept_tail:
        parts.append(kept_tail.lstrip("\n"))
    stripped_text = "\n\n".join(parts) + "\n"

    result = StripResult(text=stripped_text, stripped=True, heading=heading,
                         heading_line=index, source_chars=source_chars,
                         result_chars=len(stripped_text),
                         tail_chars=len(kept_tail))
    if result.removed_fraction > MAX_STRIP_FRACTION:
        return StripResult(text=text, stripped=False, reason=TOO_LARGE,
                           heading=heading, heading_line=index,
                           source_chars=source_chars, result_chars=source_chars)
    return result


def strip_payload(payload: dict) -> tuple[dict, StripResult]:
    """One cache entry in, one stripped cache entry out.

    Every key the extractor wrote is carried through untouched except `text` and
    `char_count`. `char_count` is updated because a file whose stated length
    disagrees with its own `text` is a trap; the extraction's original count is
    preserved as `references_strip.source_chars`, so nothing is lost.
    """
    source_text = payload.get("text") or ""
    result = strip_references(source_text)
    out = dict(payload)
    out["text"] = result.text
    out["char_count"] = len(result.text)
    out[RECORD_KEY] = result.record(source_text=source_text)
    return out, result


def strip_record(payload: dict) -> dict:
    """The `references_strip` block of a loaded file, or `{}` if it has none."""
    record = payload.get(RECORD_KEY)
    return record if isinstance(record, dict) else {}


def is_current(payload: dict, source_text: str) -> bool:
    """True when a stripped file was produced from this source by these rules.

    Both halves matter. A source hash alone would keep a file that the current
    rules would now cut differently; a method check alone would keep a file whose
    source has since been re-extracted.
    """
    record = strip_record(payload)
    if not record:
        return False
    if record.get("source_text_sha256") != sha256_text(source_text):
        return False
    return record.get("method") == STRIP_METHOD
