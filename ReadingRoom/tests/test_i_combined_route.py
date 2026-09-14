"""Combined post-gate prompt construction and Reading Room routing (DC54/DC55)."""

from __future__ import annotations

import pytest

import reading_room as rr
from conftest import label


def test_combined_prompt_sends_the_paper_once_and_brackets_both_rule_blocks():
    prompt = rr.build_combined_analysis_prompt(
        power_promptbook="P17. UNIQUE_POWER_RULE",
        data_promptbook="D15. UNIQUE_DATA_RULE",
        token="blind-token", text="UNIQUE_PAPER_BODY")

    assert prompt.count("UNIQUE_PAPER_BODY") == 1
    assert prompt.count("UNIQUE_POWER_RULE") == 2
    assert prompt.count("UNIQUE_DATA_RULE") == 2
    assert prompt.count("BEGIN POWER_ANALYSIS PROMPTBOOK") == 2
    assert prompt.count("BEGIN DATA_ANALYSIS PROMPTBOOK") == 2
    assert prompt.rfind('"power_analysis"') < prompt.rfind('"data_analysis"')


def test_combined_prompt_requires_two_isolated_complete_judgments():
    prompt = rr.build_combined_analysis_prompt(
        power_promptbook="P1. power", data_promptbook="D1. data",
        token="blind-token", text="paper")

    assert "Decide each task independently" in prompt
    assert "Neither reasoning nor evidence may refer to" in prompt
    assert "exactly four keys in each judgment" in prompt
    assert '"wrong_text"' not in prompt
    assert '"paper_id": "blind-token"' in prompt


def test_combined_route_resolves_both_promptbooks_from_one_version(promptbooks):
    root = promptbooks(
        {"v1": ["power_analysis", "data_analysis"]}, current="v1")
    version, paths, texts = rr.resolve_combined_analysis_promptbooks(root=root)

    assert version == "v1"
    assert list(paths) == ["power_analysis", "data_analysis"]
    assert paths["power_analysis"].name == "power_analysis.md"
    assert "# data_analysis v1" in texts["data_analysis"]


def test_combined_route_reuses_only_the_identical_survivor_sample(rounds_csv,
                                                                  cache_dir):
    rows = [
        ("P1", "power_analysis", 1, "survivor"),
        ("P2", "power_analysis", 1, "survivor"),
        ("P1", "data_analysis", 1, "survivor"),
        ("P2", "data_analysis", 1, "survivor"),
    ]
    labels = {paper_id: label(paper_id) for paper_id in ("P1", "P2")}
    plan = rr.load_combined_analysis_round(
        1, labels=labels, verdicts={}, rounds_csv=rounds_csv(rows),
        cache_dir=cache_dir(["P1", "P2"]))

    assert plan.task == rr.COMBINED_ANALYSIS_ROUTE
    assert plan.paper_ids == ["P1", "P2"]
    assert {paper.task for paper in plan.papers} == {rr.COMBINED_ANALYSIS_ROUTE}


def test_combined_route_refuses_different_power_and_data_membership(rounds_csv,
                                                                    cache_dir):
    rows = [
        ("P1", "power_analysis", 1, "survivor"),
        ("P2", "data_analysis", 1, "survivor"),
    ]
    labels = {paper_id: label(paper_id) for paper_id in ("P1", "P2")}
    with pytest.raises(rr.Refuse, match="membership differs"):
        rr.load_combined_analysis_round(
            1, labels=labels, verdicts={}, rounds_csv=rounds_csv(rows),
            cache_dir=cache_dir(["P1", "P2"]))


def test_combined_route_is_opt_in_and_pinned_to_medium():
    assert rr.READING_ROOM_ROUTES[:-1] == rr.db.TASKS
    assert rr.READING_ROOM_ROUTES[-1] == rr.COMBINED_ANALYSIS_ROUTE
    assert rr.EFFORT == "medium"
