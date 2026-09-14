"""Group B -- round and split selection (B1-B10).

Guards DC18 (the holdout is touched once, at the end) and DC47 (rounds are cut
once and never re-drawn). Every case here is CSV plus a throwaway SQLite
database -- no model call, no network -- so the suite stays free to run on
every commit.

Case numbers refer to `TEST_PLAN.md`.
"""

from __future__ import annotations

import csv

import pytest

from conftest import label

import db
import reading_room as rr


# ---------------------------------------------------------------- helpers


def write_manifest(tmp_path, rows: dict[str, str]) -> "Path":
    """paper_id -> verdict, written as a minimal manifest CSV."""
    path = tmp_path / "manifest.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["paper_id", "verdict"])
        for paper_id, verdict in rows.items():
            writer.writerow([paper_id, verdict])
    return path


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


def seed_labels(conn, labels: dict[str, dict]) -> None:
    rows = []
    for paper_id, fields in labels.items():
        rows.append({
            "paper_id": paper_id, "source_file": "test.csv", "citation_raw": paper_id,
            "matched_by": "test", "match_score": 100.0,
            "exclusion_reason": fields.get("exclusion_reason"),
            "power": fields.get("power"), "stats": fields.get("stats"),
            "review_category": None,
        })
    db.insert_labels(conn, rows)
    # insert_labels always writes split=NULL for a new paper_id; set it after.
    for paper_id, fields in labels.items():
        conn.execute("UPDATE validation_labels SET split = ? WHERE paper_id = ?",
                     (fields.get("split"), paper_id))
    conn.commit()


# --------------------------------------------------------- B3: round exists


def test_b3_unknown_round_is_refused_and_lists_what_exists(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "exclusion", 1, "survivor"),
                       ("P2", "exclusion", 2, "excluded")])
    with pytest.raises(rr.Refuse) as excinfo:
        rr.load_round("exclusion", 7, labels={}, verdicts={}, rounds_csv=path,
                      cache_dir=cache_dir([]))
    message = str(excinfo.value)
    assert "B3" in message
    assert "1" in message and "2" in message


def test_b3_a_round_that_exists_for_a_different_task_does_not_count(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "power_analysis", 1, "survivor")])
    with pytest.raises(rr.Refuse, match="B3"):
        rr.load_round("exclusion", 1, labels={}, verdicts={}, rounds_csv=path,
                      cache_dir=cache_dir([]))


def test_load_round_refuses_unknown_task(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "exclusion", 1, "survivor")])
    with pytest.raises(rr.Refuse, match="unknown task"):
        rr.load_round("inclusion", 1, labels={}, verdicts={}, rounds_csv=path,
                      cache_dir=cache_dir([]))


def test_load_rounds_csv_refuses_a_missing_file(tmp_path):
    with pytest.raises(rr.Refuse, match="17_assign_build_rounds"):
        rr.load_rounds_csv(tmp_path / "nope.csv")


# ------------------------------------------------------- B10: no duplicates


def test_b10_a_repeated_paper_in_one_round_is_refused(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "exclusion", 1, "survivor"),
                       ("P1", "exclusion", 1, "survivor")])
    with pytest.raises(rr.Refuse) as excinfo:
        rr.load_round("exclusion", 1, labels={"P1": label("P1")}, verdicts={},
                      rounds_csv=path, cache_dir=cache_dir(["P1"]))
    assert "B10" in str(excinfo.value)
    assert "P1" in str(excinfo.value)


def test_b10_the_same_paper_in_two_different_rounds_is_fine(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "exclusion", 1, "survivor"),
                       ("P1", "exclusion", 2, "survivor")])
    cache = cache_dir(["P1"])
    plan = rr.load_round("exclusion", 1, labels={"P1": label("P1")}, verdicts={},
                         rounds_csv=path, cache_dir=cache)
    assert plan.paper_ids == ["P1"]


# ---------------------------------------------------------------- B8: DROPPED


def test_b8_a_dropped_paper_is_skipped_and_logged_not_refused(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "exclusion", 1, "survivor"),
                       ("P2", "exclusion", 1, "survivor")])
    plan = rr.load_round("exclusion", 1, labels={"P2": label("P2")},
                         verdicts={"P1": rr.DROPPED}, rounds_csv=path,
                         cache_dir=cache_dir(["P2"]))
    assert plan.paper_ids == ["P2"]
    assert plan.skipped == [("P1", "manifest verdict=DROPPED")]


def test_b8_dropped_check_is_case_insensitive_and_untrimmed(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "exclusion", 1, "survivor")])
    plan = rr.load_round("exclusion", 1, labels={}, verdicts={"P1": " dropped "},
                         rounds_csv=path, cache_dir=cache_dir([]))
    assert plan.paper_ids == []
    assert plan.skipped[0][0] == "P1"


def test_b8_a_dropped_paper_never_needs_a_label_or_cached_text(rounds_csv, cache_dir):
    """Skipped before B2/B7, so a paper that left the corpus is never refused
    for missing data it was never going to have."""
    path = rounds_csv([("P1", "exclusion", 1, "survivor")])
    plan = rr.load_round("exclusion", 1, labels={}, verdicts={"P1": rr.DROPPED},
                         rounds_csv=path, cache_dir=cache_dir([]))
    assert plan.skipped == [("P1", "manifest verdict=DROPPED")]


# --------------------------------------------------------------- B2: split


def test_b2_no_label_row_is_refused(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "exclusion", 1, "survivor")])
    with pytest.raises(rr.Refuse) as excinfo:
        rr.load_round("exclusion", 1, labels={}, verdicts={}, rounds_csv=path,
                      cache_dir=cache_dir(["P1"]))
    assert "B2" in str(excinfo.value)


def test_b2_split_is_null_is_refused(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "exclusion", 1, "survivor")])
    with pytest.raises(rr.Refuse) as excinfo:
        rr.load_round("exclusion", 1, labels={"P1": label("P1", split=None)},
                      verdicts={}, rounds_csv=path, cache_dir=cache_dir(["P1"]))
    assert "B2" in str(excinfo.value)


def test_b2_split_is_empty_string_is_refused(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "exclusion", 1, "survivor")])
    with pytest.raises(rr.Refuse, match="B2"):
        rr.load_round("exclusion", 1, labels={"P1": label("P1", split="")},
                      verdicts={}, rounds_csv=path, cache_dir=cache_dir(["P1"]))


# --------------------------------------------------------------- B1: holdout


def test_b1_a_holdout_paper_refuses_the_entire_round(rounds_csv, cache_dir):
    """One holdout paper poisons the whole round -- not just skipped."""
    path = rounds_csv([("P1", "exclusion", 1, "survivor"),
                       ("P2", "exclusion", 1, "survivor")])
    labels = {"P1": label("P1", split=db.SPLIT_BUILD),
             "P2": label("P2", split=db.SPLIT_HOLDOUT)}
    with pytest.raises(rr.Refuse) as excinfo:
        rr.load_round("exclusion", 1, labels=labels, verdicts={}, rounds_csv=path,
                      cache_dir=cache_dir(["P1", "P2"]))
    message = str(excinfo.value)
    assert "P2" in message
    assert "B1" in message and "DC18" in message


def test_b1_an_unrecognized_split_value_is_refused(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "exclusion", 1, "survivor")])
    with pytest.raises(rr.Refuse, match="B1"):
        rr.load_round("exclusion", 1, labels={"P1": label("P1", split="test")},
                      verdicts={}, rounds_csv=path, cache_dir=cache_dir(["P1"]))


# --------------------------------------------------------------- B4: the gate


def test_b4_a_gate_excluded_paper_in_power_analysis_is_refused(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "power_analysis", 1, "excluded")])
    labels = {"P1": label("P1", exclusion_reason="not RCT", power="yes")}
    with pytest.raises(rr.Refuse) as excinfo:
        rr.load_round("power_analysis", 1, labels=labels, verdicts={},
                      rounds_csv=path, cache_dir=cache_dir(["P1"]))
    assert "B4" in str(excinfo.value) and "DC10" in str(excinfo.value)


def test_b4_a_gate_excluded_paper_in_data_analysis_is_refused(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "data_analysis", 1, "excluded")])
    labels = {"P1": label("P1", exclusion_reason="not RCT", stats="yes")}
    with pytest.raises(rr.Refuse, match="B4"):
        rr.load_round("data_analysis", 1, labels=labels, verdicts={},
                      rounds_csv=path, cache_dir=cache_dir(["P1"]))


def test_b4_a_gate_excluded_paper_is_fine_for_exclusion_itself(rounds_csv, cache_dir):
    """B4 only restricts power/data -- exclusion is the gate, it sees everyone."""
    path = rounds_csv([("P1", "exclusion", 1, "excluded")])
    labels = {"P1": label("P1", exclusion_reason="not RCT")}
    plan = rr.load_round("exclusion", 1, labels=labels, verdicts={}, rounds_csv=path,
                         cache_dir=cache_dir(["P1"]))
    assert plan.paper_ids == ["P1"]


def test_b4_a_survivor_is_fine_for_power_analysis(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "power_analysis", 1, "survivor")])
    labels = {"P1": label("P1", exclusion_reason=None, power="yes")}
    plan = rr.load_round("power_analysis", 1, labels=labels, verdicts={},
                         rounds_csv=path, cache_dir=cache_dir(["P1"]))
    assert plan.paper_ids == ["P1"]


# --------------------------------------------------------------- B7: cached text


def test_b7_missing_cached_text_is_refused_before_spending(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "exclusion", 1, "survivor")])
    with pytest.raises(rr.Refuse) as excinfo:
        rr.load_round("exclusion", 1, labels={"P1": label("P1")}, verdicts={},
                      rounds_csv=path, cache_dir=cache_dir([]))   # no P1.json
    message = str(excinfo.value)
    assert "P1" in message and "B7" in message


def test_b7_a_paper_with_cached_text_carries_its_path(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "exclusion", 1, "survivor")])
    cache = cache_dir(["P1"])
    plan = rr.load_round("exclusion", 1, labels={"P1": label("P1")}, verdicts={},
                         rounds_csv=path, cache_dir=cache)
    assert plan.papers[0].text_path == cache / "P1.json"


# --------------------------------------------------------------- B9: promptbook


def test_b9_current_names_a_missing_directory(promptbooks):
    root = promptbooks({"v1": ["exclusion"]}, current="v2")
    with pytest.raises(rr.Refuse, match="B9"):
        rr.resolve_promptbook("exclusion", root=root)


def test_b9_current_file_missing_entirely(promptbooks):
    root = promptbooks({"v1": ["exclusion"]}, current=None)
    with pytest.raises(rr.Refuse, match="B9"):
        rr.resolve_promptbook("exclusion", root=root)


def test_b9_current_file_empty(promptbooks):
    root = promptbooks({"v1": ["exclusion"]}, current="v1")
    (root / "promptbooks" / "CURRENT").write_text("", encoding="utf-8")
    with pytest.raises(rr.Refuse, match="B9"):
        rr.resolve_promptbook("exclusion", root=root)


def test_b9_directory_exists_but_lacks_this_tasks_book(promptbooks):
    root = promptbooks({"v1": ["exclusion"]}, current="v1")
    with pytest.raises(rr.Refuse, match="B9"):
        rr.resolve_promptbook("power_analysis", root=root)


def test_b9_a_valid_current_resolves_version_path_and_text(promptbooks):
    root = promptbooks({"v1": ["exclusion"]}, current="v1")
    version, path, text = rr.resolve_promptbook("exclusion", root=root)
    assert version == "v1"
    assert path == root / "promptbooks" / "v1" / "exclusion.md"
    assert "exclusion v1" in text


def test_resolve_promptbook_refuses_unknown_task(promptbooks):
    root = promptbooks({"v1": ["exclusion"]}, current="v1")
    with pytest.raises(rr.Refuse, match="unknown task"):
        rr.resolve_promptbook("inclusion", root=root)


# ------------------------------------------------------------- B6: short round


def test_b6_a_short_round_is_proceeded_with_and_n_reflects_it(rounds_csv, cache_dir):
    """DC47: a dropped paper shrinks n; the round is never topped back up."""
    path = rounds_csv([("P1", "exclusion", 1, "survivor"),
                       ("P2", "exclusion", 1, "survivor"),
                       ("P3", "exclusion", 1, "survivor")])
    labels = {"P2": label("P2"), "P3": label("P3")}
    plan = rr.load_round("exclusion", 1, labels=labels, verdicts={"P1": rr.DROPPED},
                         rounds_csv=path, cache_dir=cache_dir(["P2", "P3"]))
    assert plan.n == 2
    assert plan.skipped == [("P1", "manifest verdict=DROPPED")]


# ------------------------------------------------------------- B5: membership


def test_b5_membership_matching_expected_ids_passes(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "exclusion", 1, "survivor"),
                       ("P2", "exclusion", 1, "survivor")])
    labels = {"P1": label("P1"), "P2": label("P2")}
    plan = rr.load_round("exclusion", 1, labels=labels, verdicts={}, rounds_csv=path,
                         cache_dir=cache_dir(["P1", "P2"]), expected_ids={"P1", "P2"})
    assert set(plan.paper_ids) == {"P1", "P2"}


def test_b5_an_added_paper_is_refused(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "exclusion", 1, "survivor"),
                       ("P2", "exclusion", 1, "survivor")])
    labels = {"P1": label("P1"), "P2": label("P2")}
    with pytest.raises(rr.Refuse) as excinfo:
        rr.load_round("exclusion", 1, labels=labels, verdicts={}, rounds_csv=path,
                      cache_dir=cache_dir(["P1", "P2"]), expected_ids={"P1"})
    message = str(excinfo.value)
    assert "P2" in message and "B5" in message and "DC47" in message


def test_b5_a_missing_paper_is_refused(rounds_csv, cache_dir):
    path = rounds_csv([("P1", "exclusion", 1, "survivor")])
    labels = {"P1": label("P1")}
    with pytest.raises(rr.Refuse) as excinfo:
        rr.load_round("exclusion", 1, labels=labels, verdicts={}, rounds_csv=path,
                      cache_dir=cache_dir(["P1"]), expected_ids={"P1", "P2"})
    assert "P2" in str(excinfo.value) and "B5" in str(excinfo.value)


def test_b5_is_skipped_when_no_expected_ids_given(rounds_csv, cache_dir):
    """No baseline to check against -- e.g. the very first cut of a round."""
    path = rounds_csv([("P1", "exclusion", 1, "survivor")])
    plan = rr.load_round("exclusion", 1, labels={"P1": label("P1")}, verdicts={},
                         rounds_csv=path, cache_dir=cache_dir(["P1"]))
    assert plan.paper_ids == ["P1"]


# --------------------------------------------------------- load_verdicts/labels


def test_load_verdicts_refuses_missing_manifest(tmp_path):
    with pytest.raises(rr.Refuse, match="manifest"):
        rr.load_verdicts(tmp_path / "nope.csv")


def test_load_verdicts_maps_paper_id_to_verdict(tmp_path):
    path = write_manifest(tmp_path, {"P1": "VERIFIED", "P2": rr.DROPPED})
    verdicts = rr.load_verdicts(path)
    assert verdicts == {"P1": "VERIFIED", "P2": rr.DROPPED}


def test_load_verdicts_treats_missing_verdict_column_value_as_empty(tmp_path):
    path = tmp_path / "manifest.csv"
    path.write_text("paper_id,verdict\nP1,\n", encoding="utf-8")
    assert rr.load_verdicts(path) == {"P1": ""}


def test_load_labels_reads_every_row_as_a_dict(conn):
    seed_labels(conn, {"P1": label("P1"), "P2": label("P2", split=db.SPLIT_HOLDOUT)})
    labels = rr.load_labels(conn)
    assert set(labels) == {"P1", "P2"}
    assert labels["P2"]["split"] == db.SPLIT_HOLDOUT


# ------------------------------------------------------------- end-to-end


def test_a_realistic_round_of_three_with_one_drop_one_gate_and_one_clean(
        rounds_csv, cache_dir):
    """One test exercising B1/B4/B8 together, the way an actual round mixes them."""
    path = rounds_csv([
        ("SURVIVOR1", "power_analysis", 3, "survivor"),
        ("EXCLUDED1", "power_analysis", 3, "excluded"),   # B4: gate-excluded
        ("GONE1",     "power_analysis", 3, "survivor"),   # B8: dropped
    ])
    labels = {
        "SURVIVOR1": label("SURVIVOR1", exclusion_reason=None, power="yes"),
        "EXCLUDED1": label("EXCLUDED1", exclusion_reason="not RCT", power="yes"),
    }
    verdicts = {"GONE1": rr.DROPPED}
    with pytest.raises(rr.Refuse, match="B4"):
        rr.load_round("power_analysis", 3, labels=labels, verdicts=verdicts,
                      rounds_csv=path, cache_dir=cache_dir(["SURVIVOR1", "EXCLUDED1"]))
