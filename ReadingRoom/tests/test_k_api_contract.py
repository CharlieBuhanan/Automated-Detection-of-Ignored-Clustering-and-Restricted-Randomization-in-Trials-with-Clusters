"""Offline API transport contract: native JSON Schema at medium effort."""

from __future__ import annotations

import pytest

import api_contract
import db
import reading_room as rr
import schemas


@pytest.mark.parametrize("route", [*db.TASKS, rr.COMBINED_ANALYSIS_ROUTE])
def test_every_api_route_uses_native_json_schema_and_medium_effort(route):
    config = api_contract.output_config_for(route)

    assert config["effort"] == rr.EFFORT == "medium"
    assert config["format"]["type"] == "json_schema"
    assert "schema" in config["format"]
    assert "tools" not in config
    assert "tool_choice" not in config


def test_combined_route_uses_the_two_task_schema_without_shared_mutation():
    first = api_contract.output_config_for(rr.COMBINED_ANALYSIS_ROUTE)
    second = api_contract.output_config_for(rr.COMBINED_ANALYSIS_ROUTE)

    assert first["format"]["schema"] == schemas.combined_analysis_tool_schema()["input_schema"]
    first["format"]["schema"]["properties"]["power_analysis"]["description"] = "mutated"
    assert second["format"]["schema"] != first["format"]["schema"]


def test_api_contract_refuses_an_unknown_route_or_effort_drift():
    with pytest.raises(ValueError, match="unknown API route"):
        api_contract.output_config_for("not-a-task")
    with pytest.raises(ValueError, match="effort"):
        api_contract.output_config_for("exclusion", effort="high")


def test_sdk_pin_guard_is_testable_without_a_provider_import():
    assert api_contract.assert_pinned_anthropic_sdk(
        installed_version=api_contract.ANTHROPIC_SDK_VERSION) == "1.0.0"
    with pytest.raises(RuntimeError, match="version drift"):
        api_contract.assert_pinned_anthropic_sdk(installed_version="0.99.0")
