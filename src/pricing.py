"""Versioned Anthropic token-price calculations.

The Claude Code CLI includes ``total_cost_usd`` in its result stream, but that
number is produced by the installed CLI and can retain an obsolete price card.
Keep it as provider provenance; use this module for current estimates.

Prices are USD per million tokens and reflect Anthropic's published prices on
2026-08-10. Prompt-cache multipliers are 1.25x for a five-minute write, 2x for
a one-hour write, and 0.1x for a cache read. Message Batches are 50% off.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


PRICING_VERSION = "anthropic-2026-08-10"
MILLION = Decimal("1000000")
BATCH_MULTIPLIER = Decimal("0.5")


class PricingError(ValueError):
    """Usage cannot be priced without guessing."""


@dataclass(frozen=True)
class ModelPrice:
    base_input: Decimal
    output: Decimal

    @property
    def cache_write_5m(self) -> Decimal:
        return self.base_input * Decimal("1.25")

    @property
    def cache_write_1h(self) -> Decimal:
        return self.base_input * Decimal("2")

    @property
    def cache_read(self) -> Decimal:
        return self.base_input * Decimal("0.1")


# Keep aliases here rather than scattered through runners and planning scripts.
# A dated Haiku ID is emitted by Claude Code even though Sonnet 5 is returned as
# a bare alias.
MODEL_PRICES = {
    "claude-sonnet-5": ModelPrice(Decimal("2"), Decimal("10")),
    "claude-haiku-4-5": ModelPrice(Decimal("1"), Decimal("5")),
}


@dataclass(frozen=True)
class CostEstimate:
    total_usd: Decimal
    by_model: Mapping[str, Decimal]
    pricing_version: str = PRICING_VERSION


def _count(usage: Mapping, snake: str, camel: str) -> int:
    """Read either API snake_case or Claude Code camelCase usage fields."""
    value = usage.get(snake, usage.get(camel, 0))
    if value is None:
        return 0
    if not isinstance(value, (int, float)) or value < 0:
        raise PricingError(f"invalid token count for {snake}: {value!r}")
    return int(value)


def price_for_model(model: str) -> ModelPrice:
    for alias, price in MODEL_PRICES.items():
        if model == alias or model.startswith(alias + "-"):
            return price
    raise PricingError(f"no price card for model {model!r}")


def estimate_usage_cost(
    model: str,
    usage: Mapping,
    *,
    cache_write_5m_tokens: int | None = None,
    cache_write_1h_tokens: int | None = None,
    unspecified_cache_ttl: str | None = None,
    batch: bool = False,
) -> Decimal:
    """Price one model's usage without treating cache writes as base input.

    Claude Code's per-model block gives one aggregate cache-creation count.
    Callers should pass the 5m/1h split when the result event supplies it. If
    it does not, ``unspecified_cache_ttl`` must be explicit; otherwise this
    function refuses instead of silently choosing the cheaper rate.
    """
    price = price_for_model(model)
    ordinary = _count(usage, "input_tokens", "inputTokens")
    output = _count(usage, "output_tokens", "outputTokens")
    cache_read = _count(
        usage, "cache_read_input_tokens", "cacheReadInputTokens")
    cache_created = _count(
        usage, "cache_creation_input_tokens", "cacheCreationInputTokens")

    write_5m = cache_write_5m_tokens
    write_1h = cache_write_1h_tokens
    if write_5m is None and write_1h is None:
        if cache_created == 0:
            write_5m = write_1h = 0
        elif unspecified_cache_ttl == "5m":
            write_5m, write_1h = cache_created, 0
        elif unspecified_cache_ttl == "1h":
            write_5m, write_1h = 0, cache_created
        else:
            raise PricingError(
                f"{model} reports {cache_created} cache-write tokens without "
                "a 5m/1h split")
    else:
        write_5m = write_5m or 0
        write_1h = write_1h or 0
        if write_5m < 0 or write_1h < 0:
            raise PricingError("cache-write token counts cannot be negative")
        if write_5m + write_1h != cache_created:
            raise PricingError(
                "cache-write split does not equal cache_creation_input_tokens")

    dollars = (
        Decimal(ordinary) * price.base_input
        + Decimal(output) * price.output
        + Decimal(cache_read) * price.cache_read
        + Decimal(write_5m) * price.cache_write_5m
        + Decimal(write_1h) * price.cache_write_1h
    ) / MILLION
    if batch:
        dollars *= BATCH_MULTIPLIER
    return dollars


def estimate_result_cost(
    result: Mapping,
    *,
    batch: bool = False,
    unspecified_cache_ttl: str | None = None,
) -> CostEstimate | None:
    """Reprice a Claude Code ``result`` event from its ``modelUsage`` block.

    The top-level usage block identifies the primary model's cache-write TTL.
    Auxiliary models generally have no cache writes. When the stream lacks a
    TTL split, the caller must provide ``unspecified_cache_ttl`` explicitly.
    """
    all_usage = result.get("modelUsage")
    if not isinstance(all_usage, Mapping) or not all_usage:
        return None

    top_usage = result.get("usage") if isinstance(result.get("usage"), Mapping) else {}
    cache_detail = top_usage.get("cache_creation", {})
    if not isinstance(cache_detail, Mapping):
        cache_detail = {}
    top_5m = _count(
        cache_detail, "ephemeral_5m_input_tokens", "ephemeral5mInputTokens")
    top_1h = _count(
        cache_detail, "ephemeral_1h_input_tokens", "ephemeral1hInputTokens")
    detailed_total = top_5m + top_1h
    detail_claimed = False

    by_model: dict[str, Decimal] = {}
    for model, usage in all_usage.items():
        if not isinstance(usage, Mapping):
            raise PricingError(f"usage for {model!r} is not an object")
        created = _count(
            usage, "cache_creation_input_tokens", "cacheCreationInputTokens")
        kwargs = {"unspecified_cache_ttl": unspecified_cache_ttl}
        if detailed_total and created == detailed_total and not detail_claimed:
            kwargs.update(cache_write_5m_tokens=top_5m,
                          cache_write_1h_tokens=top_1h)
            detail_claimed = True
        by_model[model] = estimate_usage_cost(
            model, usage, batch=batch, **kwargs)

    return CostEstimate(sum(by_model.values(), Decimal("0")), by_model)
