"""Current, versioned pricing must not inherit a stale CLI estimate."""

import json
from decimal import Decimal

import pytest

import pricing
import reading_room as rr


def test_sonnet_5_current_base_prices():
    usage = {"inputTokens": 1_000_000, "outputTokens": 1_000_000}
    assert pricing.estimate_usage_cost("claude-sonnet-5", usage) == Decimal("12")


def test_cache_multipliers_match_published_rates():
    usage = {
        "inputTokens": 0,
        "outputTokens": 0,
        "cacheReadInputTokens": 1_000_000,
        "cacheCreationInputTokens": 2_000_000,
    }
    cost = pricing.estimate_usage_cost(
        "claude-sonnet-5", usage,
        cache_write_5m_tokens=1_000_000,
        cache_write_1h_tokens=1_000_000,
    )
    assert cost == Decimal("6.7")  # 0.2 read + 2.5 five-min + 4 one-hour


def test_batch_is_half_of_standard():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    standard = pricing.estimate_usage_cost("claude-sonnet-5", usage)
    batch = pricing.estimate_usage_cost("claude-sonnet-5", usage, batch=True)
    assert batch == standard / 2


def test_cache_ttl_must_not_be_guessed():
    usage = {"cacheCreationInputTokens": 100}
    with pytest.raises(pricing.PricingError, match="without a 5m/1h split"):
        pricing.estimate_usage_cost("claude-sonnet-5", usage)


def test_result_repricing_ignores_stale_provider_total():
    result = {
        "total_cost_usd": 99.99,
        "usage": {
            "cache_creation": {
                "ephemeral_5m_input_tokens": 0,
                "ephemeral_1h_input_tokens": 1_000_000,
            }
        },
        "modelUsage": {
            "claude-sonnet-5": {
                "inputTokens": 0,
                "outputTokens": 100_000,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 1_000_000,
            },
            "claude-haiku-4-5-20251001": {
                "inputTokens": 1_000_000,
                "outputTokens": 0,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
            },
        },
    }
    estimate = pricing.estimate_result_cost(result)
    assert estimate is not None
    assert estimate.by_model["claude-sonnet-5"] == Decimal("5")
    assert estimate.by_model["claude-haiku-4-5-20251001"] == Decimal("1")
    assert estimate.total_usd == Decimal("6")
    assert estimate.pricing_version == "anthropic-2026-08-10"


def test_unknown_model_refuses_instead_of_using_a_wrong_rate():
    with pytest.raises(pricing.PricingError, match="no price card"):
        pricing.estimate_usage_cost("claude-unknown-9", {"inputTokens": 1})


def test_batch_one_accepted_sonnet_usage_at_current_prices():
    """The accepted Batch 1 classifier tokens reprice to $17.065834."""
    usage = {
        "inputTokens": 146,
        "outputTokens": 74_999,
        "cacheReadInputTokens": 0,
        "cacheCreationInputTokens": 4_078_888,
    }
    cost = pricing.estimate_usage_cost(
        "claude-sonnet-5", usage,
        cache_write_5m_tokens=0,
        cache_write_1h_tokens=4_078_888,
    )
    assert cost == Decimal("17.065834")


def test_reading_room_keeps_provider_cost_and_adds_current_estimate():
    result = {
        "type": "result",
        "total_cost_usd": 9.99,
        "usage": {
            "cache_creation": {
                "ephemeral_5m_input_tokens": 0,
                "ephemeral_1h_input_tokens": 1_000_000,
            }
        },
        "modelUsage": {
            "claude-sonnet-5": {
                "inputTokens": 0,
                "outputTokens": 100_000,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 1_000_000,
            }
        },
    }
    row = rr.paper_provenance(json.dumps(result))
    assert row["total_cost_usd"] == 9.99
    assert row["estimated_cost_usd_current"] == 5.0
    assert row["pricing_version"] == pricing.PRICING_VERSION
