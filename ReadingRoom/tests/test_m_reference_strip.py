"""Group J: the references-stripping pass, and what the Reading Room sees of it.

`scripts/19_strip_references.py` removes 21.6% of the corpus by character before
a single token is spent, which makes it the cheapest saving available -- and the
most dangerous, because a cut in the wrong place removes a methods section and
the resulting judgment looks exactly like a correct one.

So the cases here are lopsided on purpose. A handful establish that a normal
paper loses its bibliography; the rest establish that everything ambiguous is
left **whole**, with a reason, and that the run log can always say which of the
two happened to any given paper.
"""

from __future__ import annotations

import json

import pytest

import reading_room as rr
import reference_strip as rs


# Sized like a real paper, because the guards are proportional: a body under 30%
# of the document is not treated as a body at all (J5), and a cut over 60% is
# abandoned (J6). A toy two-line paper with a long bibliography would trip both
# and prove nothing about the ordinary case.
BODY = ("Introduction. A cluster randomized trial in 40 clinics.\n"
        "Methods. Sample size was computed for an ICC of 0.02, giving 80% power\n"
        "at alpha 0.05 with 20 clusters per arm.\n"
        "Results. The intervention arm improved.\n"
        "Discussion. Limitations include a stepped implementation timetable.\n") * 4

BIBLIOGRAPHY = "\n".join(
    f"{i}. Author A, Author B. A stepped wedge pilot of something. J Trials. 2020."
    for i in range(1, 9))


def paper(body: str = BODY, heading: str = "References",
          refs: str = BIBLIOGRAPHY, tail: str = "") -> str:
    return f"{body}\n{heading}\n{refs}\n{tail}"


# ------------------------------------------------- J1-J3: the ordinary cut


def test_j1_a_normal_paper_loses_its_bibliography_and_keeps_its_methods():
    result = rs.strip_references(paper())

    assert result.stripped is True
    assert "Sample size was computed" in result.text
    assert "J Trials. 2020" not in result.text
    assert result.chars_removed > 0


def test_j2_the_cut_leaves_a_visible_marker():
    """E2 protection, not decoration.

    A paper with no bibliography reads like an abstract or a conference summary,
    which is exactly what exclusion criterion E2 ("not a full report") is looking
    for. Without the marker the trim would manufacture the exclusion it is
    supposed to be neutral about.
    """
    result = rs.strip_references(paper())

    assert rs.MARKER in result.text


def test_j3_an_appendix_behind_the_references_survives():
    """134 corpus papers carry one, and they are where sample size often lives."""
    tail = ("Appendix A. Sample size calculation\n"
            "We assumed an intracluster correlation of 0.02.\n")
    result = rs.strip_references(paper(tail=tail))

    assert result.stripped is True
    assert "intracluster correlation of 0.02" in result.text
    assert "J Trials. 2020" not in result.text
    assert result.tail_chars > 0


# --------------------------------------- J4-J8: everything ambiguous is kept


def test_j4_a_paper_with_no_heading_goes_out_whole():
    text = BODY + "\n" + BIBLIOGRAPHY

    result = rs.strip_references(text)

    assert result.stripped is False
    assert result.reason == rs.NO_HEADING
    assert result.text == text
    assert result.chars_removed == 0


def test_j5_a_heading_in_the_first_third_is_not_the_bibliography():
    """A key-points box or a running head, not a section break."""
    result = rs.strip_references("Intro\nReferences\n" + "X" * 1000)

    assert result.stripped is False
    assert result.reason == rs.TOO_EARLY
    assert result.heading == "References"          # found, and then declined


def test_j6_an_implausibly_large_cut_is_abandoned():
    """Fires on nothing in this corpus today; it is here for the next one."""
    text = "M" * 400 + "\nReferences\n" + "\n".join("R" * 40 for _ in range(20))

    result = rs.strip_references(text)

    assert result.stripped is False
    assert result.reason == rs.TOO_LARGE
    assert result.text == text


@pytest.mark.parametrize("text", ["", "   \n\n  \n"])
def test_j7_empty_text_is_reported_not_cut(text):
    result = rs.strip_references(text)

    assert result.stripped is False
    assert result.reason == rs.EMPTY


def test_j8_the_last_heading_wins_not_the_first():
    text = (BODY + "\nReferences\nsee below\n" + BODY + "\nReferences\n"
            + BIBLIOGRAPHY + "\n")

    result = rs.strip_references(text)

    assert result.stripped is True
    assert (result.text.count("Sample size was computed")
            == BODY.count("Sample size was computed") * 2)
    assert "J Trials. 2020" not in result.text


def test_j9_the_word_inside_a_sentence_is_not_a_section_break():
    text = (BODY + "As the references above show, this is contested.\n"
            + BIBLIOGRAPHY)

    result = rs.strip_references(text)

    assert result.stripped is False
    assert result.reason == rs.NO_HEADING


@pytest.mark.parametrize("heading", [
    "References", "REFERENCES", "references", "  References  ", "References:",
    "5. References", "6.  REFERENCES", "* References", "Bibliography",
    "Reference List", "Works Cited", "Literature Cited",
])
def test_j10_the_heading_forms_this_corpus_actually_uses_all_match(heading):
    result = rs.strip_references(paper(heading=heading))

    assert result.stripped is True, heading


# ------------------------------------------- J11-J12: the file that is written


def test_j11_the_copy_keeps_every_extraction_field_and_agrees_with_itself():
    payload = {"paper_id": "ABC123", "pdf_md5": "deadbeef", "method": "pymupdf",
               "page_count": 12, "char_count": 999, "text": paper()}

    out, result = rs.strip_payload(payload)

    assert out["paper_id"] == "ABC123"
    assert out["pdf_md5"] == "deadbeef"          # provenance carried through
    assert out["page_count"] == 12
    assert out["char_count"] == len(out["text"])  # never disagrees with its own text
    assert out[rs.RECORD_KEY]["source_chars"] == len(payload["text"])
    assert out[rs.RECORD_KEY]["chars_removed"] == result.chars_removed


def test_j12_a_stripped_copy_knows_when_it_has_gone_stale():
    source = paper()
    out, _ = rs.strip_payload({"paper_id": "ABC123", "text": source})

    assert rs.is_current(out, source) is True
    assert rs.is_current(out, source + "an extra paragraph") is False
    assert rs.is_current({"paper_id": "ABC123", "text": source}, source) is False

    out[rs.RECORD_KEY]["method"] = "reference_heading_v0"
    assert rs.is_current(out, source) is False


# ------------------------------ J13-J15: what the Reading Room does with it


def write_cache(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_j13_read_paper_text_carries_the_cut_into_the_run_log(tmp_path):
    out, result = rs.strip_payload({"paper_id": "ABC123", "text": paper()})
    path = write_cache(tmp_path, "ABC123.json", out)

    body = rr.read_paper_text(path)

    assert body.refs_removed == result.chars_removed
    assert body.refs_method == rs.STRIP_METHOD
    assert f"refs_removed={result.chars_removed}" in body.notes


def test_j14_a_paper_left_whole_says_why_in_the_run_log(tmp_path):
    out, _ = rs.strip_payload({"paper_id": "ABC123", "text": BODY + BIBLIOGRAPHY})
    path = write_cache(tmp_path, "ABC123.json", out)

    body = rr.read_paper_text(path)

    assert body.refs_removed == 0
    assert body.notes == f"refs_kept:{rs.NO_HEADING}"


def test_j15_a_file_that_never_saw_the_stripper_is_visible_as_such(tmp_path):
    """Unprepared is a third state, not a synonym for 'nothing was removed'."""
    path = write_cache(tmp_path, "ABC123.json", {"paper_id": "ABC123", "text": BODY})

    body = rr.read_paper_text(path)

    assert body.refs_method == ""
    assert "refs_unprepared" in body.notes
    # ...and a string that never came from a file makes no claim either way.
    assert rr.clean_paper_text(BODY).refs_method is None
    assert rr.clean_paper_text(BODY).notes == ""


def test_j16_a_round_may_not_mix_prepared_and_unprepared_text():
    """Free, and before the first spawn: two conditions in one accuracy number."""
    rr.check_round_text_preparation([rs.STRIP_METHOD] * 50)      # uniform: fine
    rr.check_round_text_preparation([""] * 50)                   # uniform: fine

    with pytest.raises(rr.Refuse, match="prepared 2 different ways"):
        rr.check_round_text_preparation([rs.STRIP_METHOD] * 49 + [""])
