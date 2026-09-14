"""Pure, offline contract shared by future Anthropic Batch request builders.

The build-set API path deliberately keeps the provider transport choice in one
small module.  It sends native JSON Schema structured output, not a tool call:
the returned text is still parsed and semantically checked locally before it
can become a judgment.

This module constructs no client and makes no network call.  It is safe to use
from the offline planner and its tests.
"""

from __future__ import annotations

from copy import deepcopy
from importlib.metadata import PackageNotFoundError, version

import db
import reading_room as rr
import schemas


# Keep this synchronized with requirements.txt.  Submission code must call
# ``assert_pinned_anthropic_sdk`` before it materializes a paid request.
ANTHROPIC_SDK_VERSION = "1.0.0"
STRUCTURED_OUTPUT_TYPE = "json_schema"


def output_config_for(route: str, *, effort: str = rr.EFFORT) -> dict:
    """Return the exact native structured-output block for one API request.

    ``route`` is one ordinary database task or the opt-in combined-analysis
    route.  Medium is intentionally the only accepted effort: a caller cannot
    accidentally create an incomparable paid condition by overriding it.
    """
    if effort != rr.EFFORT:
        raise ValueError(
            f"API effort must remain pinned to {rr.EFFORT!r}, not {effort!r}")

    if route == rr.COMBINED_ANALYSIS_ROUTE:
        schema = schemas.combined_analysis_tool_schema()["input_schema"]
    elif route in db.TASKS:
        schema = schemas.tool_schema(route)["input_schema"]
    else:
        raise ValueError(
            f"unknown API route {route!r}; expected one of "
            f"{(*db.TASKS, rr.COMBINED_ANALYSIS_ROUTE)!r}")

    # deepcopy makes each request independently immutable to its caller.  A
    # planner that annotates one schema must not silently alter a later request.
    return {
        "effort": rr.EFFORT,
        "format": {"type": STRUCTURED_OUTPUT_TYPE, "schema": deepcopy(schema)},
    }


def assert_pinned_anthropic_sdk(*, installed_version: str | None = None) -> str:
    """Refuse an API submission when its installed SDK drifts from the lock.

    Passing ``installed_version`` keeps the guard unit-testable without
    importing the provider package.  Normal submission code leaves it omitted.
    """
    if installed_version is None:
        try:
            installed_version = version("anthropic")
        except PackageNotFoundError as exc:
            raise RuntimeError(
                "Anthropic SDK is not installed; install the pinned "
                f"anthropic=={ANTHROPIC_SDK_VERSION} before submitting") from exc
    if installed_version != ANTHROPIC_SDK_VERSION:
        raise RuntimeError(
            "Anthropic SDK version drift: expected "
            f"{ANTHROPIC_SDK_VERSION}, found {installed_version}. Refusing to "
            "submit an untested request shape.")
    return installed_version
