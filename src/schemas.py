"""The Decision schema: the one object every task returns, on every route.

Both routes produce the same object, and both are validated here:

    Batch API   forces the shape with `tool_choice`, so a malformed reply is
                impossible -- this model is then the tool's input schema.
    Reading Room (`claude -p`) cannot force anything, so the prompt asks for
                JSON and the wrapper parses it here. A parse failure is a
                re-prompt and a logged retry, never a discarded paper (DC24).

Because one model covers both, the two routes cannot drift apart in what they
accept, which is the whole point of DC14. If a field is optional here it is
optional everywhere; if a value is rejected here it is rejected everywhere.

Nothing in this module knows about Claude, HTTP, or files. It takes text or a
dict and either returns a Decision or explains why it could not.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# The three tasks, mirroring db.TASKS. Duplicated rather than imported so this
# module stays free of the storage layer -- but a mismatch would be a real bug,
# so db.py's CHECK constraint is the backstop.
TASKS = ("exclusion", "power_analysis", "data_analysis")

# `wrong_text` is exclusion-only (DC41). Power and data analysis only ever see
# gate survivors, which have already passed that check, so offering it there
# would invite the model to abstain on a question it has no business asking.
DECISIONS = ("yes", "no", "undecidable", "wrong_text")
EXCLUSION_ONLY_DECISIONS = ("wrong_text",)

# DC27. Characters, not words: a character count is exactly checkable, where
# "60 words" needs a tokenizer nobody agrees on and produces a cap the model
# can breach without either side noticing.
REASONING_MAX_CHARS = 200

# A promptbook rule id: E1-E18 for exclusion, P-something for power, D- for
# data. Used to check that `promptbook_evidence` cites a rule that exists,
# rather than paraphrasing one.
RULE_ID = re.compile(r"\b([EPD])(\d{1,2})\b")


class Decision(BaseModel):
    """One model judgment of one paper on one task."""

    model_config = ConfigDict(
        # A key we did not ask for means the model invented a field, which is a
        # prompt problem worth seeing rather than silently dropping.
        extra="forbid",
        str_strip_whitespace=True,
    )

    decision: str = Field(description="yes | no | undecidable | wrong_text")
    reasoning: str = Field(description=f"why, in the model's own words, <= {REASONING_MAX_CHARS} chars")
    promptbook_evidence: str = Field(description="which promptbook rule(s) drove it")
    confidence: float = Field(ge=0.0, le=1.0)

    # Not returned by the model -- set by the wrapper from the blinded token it
    # sent, so a Decision is self-describing once it is out of the harness.
    task: str | None = None
    paper_id: str | None = None

    @field_validator("decision")
    @classmethod
    def _known_decision(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}, got {value!r}")
        return value

    @field_validator("task")
    @classmethod
    def _known_task(cls, value: str | None) -> str | None:
        if value is not None and value not in TASKS:
            raise ValueError(f"task must be one of {TASKS}, got {value!r}")
        return value

    @field_validator("reasoning")
    @classmethod
    def _reasoning_within_cap(cls, value: str) -> str:
        if not value:
            raise ValueError("reasoning is required on every judgment (DC13)")
        if len(value) > REASONING_MAX_CHARS:
            raise ValueError(
                f"reasoning is {len(value)} chars, cap is {REASONING_MAX_CHARS}")
        return value

    @field_validator("promptbook_evidence")
    @classmethod
    def _evidence_present(cls, value: str) -> str:
        if not value:
            raise ValueError(
                "promptbook_evidence is required (DC13): naming the rule is what makes "
                "a miss diagnosable as misapplied vs. missing vs. wrong")
        return value

    @model_validator(mode="after")
    def _wrong_text_is_exclusion_only(self) -> Decision:
        if (self.decision in EXCLUSION_ONLY_DECISIONS
                and self.task is not None and self.task != "exclusion"):
            raise ValueError(
                f"{self.decision!r} is exclusion-only (DC41); got task={self.task!r}")
        return self

    # -------------------------------------------------------------- helpers

    def cited_rules(self) -> list[str]:
        """Rule ids named in `promptbook_evidence`, e.g. ['E5', 'E12']."""
        return [f"{letter}{number}" for letter, number in RULE_ID.findall(self.promptbook_evidence)]

    def is_abstention(self) -> bool:
        """True when this judgment carries no answer to score.

        Both routes to the human review queue, for different reasons, and
        neither counts as a miss: `undecidable` says the call is unclear,
        `wrong_text` says the document is probably not the paper.
        """
        return self.decision in ("undecidable", "wrong_text")


class ParseFailure(Exception):
    """The model's reply could not be read as a Decision.

    Carries `raw` so the retry ledger can record what actually came back. A
    failure is never a discarded paper: it is a re-prompt and a logged retry,
    and the rate is reportable because retries concentrate on borderline papers
    (DC24).
    """

    def __init__(self, message: str, raw: str = "", paper_id: str | None = None):
        super().__init__(message)
        self.raw = raw
        self.paper_id = paper_id


def _strip_fences(text: str) -> tuple[str, bool]:
    """Pull JSON out of a ```json ... ``` block. Returns (text, was_fenced).

    The Reading Room's prompt asks for bare JSON, but models wrap it in a fence
    often enough that failing on it would inflate the retry rate with something
    that is not a real disagreement. `was_fenced` is returned rather than
    swallowed so the checker can count how often it happens -- a rising rate
    means the prompt's format instruction is losing.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped, False
    body = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    if body.rstrip().endswith("```"):
        body = body.rstrip()[: -len("```")]
    return body.strip(), True


def parse_decision(raw: str, *, task: str | None = None,
                   paper_id: str | None = None) -> tuple[Decision, bool]:
    """Parse a model reply into a Decision. Returns (decision, was_fenced).

    Raises ParseFailure on anything unreadable, with the raw text attached.
    """
    text, was_fenced = _strip_fences(raw)
    if not text:
        raise ParseFailure("empty reply", raw=raw, paper_id=paper_id)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseFailure(f"not valid JSON: {exc}", raw=raw, paper_id=paper_id) from exc

    if not isinstance(payload, dict):
        raise ParseFailure(
            f"expected a JSON object, got {type(payload).__name__}", raw=raw, paper_id=paper_id)

    payload.setdefault("task", task)
    payload.setdefault("paper_id", paper_id)

    try:
        return Decision.model_validate(payload), was_fenced
    except Exception as exc:
        raise ParseFailure(str(exc), raw=raw, paper_id=paper_id) from exc


def tool_schema(task: str) -> dict:
    """The forced `tool_choice` schema for a Batch API run of one task.

    Built from the same model as the CLI route parses into, so the two cannot
    drift (DC35). `task` and `paper_id` are dropped: the wrapper knows both, and
    asking the model for them invites it to guess an identifier it was
    deliberately never told (the Reading Room blinds it).
    """
    if task not in TASKS:
        raise ValueError(f"unknown task {task!r}; expected one of {TASKS}")

    schema = Decision.model_json_schema()
    properties = {k: v for k, v in schema["properties"].items()
                  if k not in ("task", "paper_id")}

    allowed = [d for d in DECISIONS
               if task == "exclusion" or d not in EXCLUSION_ONLY_DECISIONS]
    properties["decision"] = {"type": "string", "enum": list(allowed),
                              "description": " | ".join(allowed)}
    properties["reasoning"]["maxLength"] = REASONING_MAX_CHARS

    return {
        "name": f"record_{task}_decision",
        "description": f"Record the {task} judgment for the paper above.",
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": ["decision", "reasoning", "promptbook_evidence", "confidence"],
            "additionalProperties": False,
        },
    }
