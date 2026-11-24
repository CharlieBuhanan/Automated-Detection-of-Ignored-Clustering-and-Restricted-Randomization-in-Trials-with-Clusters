"""The judgment schemas shared by the CLI and Batch API routes.

Both routes produce the same object, and both are validated here:

    Batch API   sets native JSON Schema structured output with
                `output_config.format`; this module supplies the schema and
                still validates every returned response locally.
    Reading Room (`claude -p`) cannot force anything, so the prompt asks for
                JSON and the wrapper parses it here. A parse failure is a
                re-prompt and a logged retry, never a discarded paper (DC24).

Because one model covers both, the two routes cannot drift apart in what they
accept, which is the whole point of DC14. If a field is optional here it is
optional everywhere; if a value is rejected here it is rejected everywhere.

Nothing in this module knows about Claude, HTTP, or files. It takes text or a
dict and either returns a judgment object or explains why it could not.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# The three tasks, mirroring db.TASKS. Duplicated rather than imported so this
# module stays free of the storage layer -- but a mismatch would be a real bug,
# so db.py's CHECK constraint is the backstop.
TASKS = ("exclusion", "power_analysis", "data_analysis")
ANALYSIS_TASKS = ("power_analysis", "data_analysis")

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


class CombinedAnalysisDecision(BaseModel):
    """The two post-gate judgments returned from one paper call (DC54).

    The two nested decisions deliberately remain ordinary :class:`Decision`
    instances. That makes every per-task constraint identical to a separate
    call, while this enclosing model makes a partial response impossible to
    accept. ``paper_id`` carries the blinded token on the CLI route; it is
    omitted from the Batch API tool schema because that wrapper already owns it.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    paper_id: str | None = None
    power_analysis: Decision
    data_analysis: Decision

    @model_validator(mode="before")
    @classmethod
    def _nested_decisions_cannot_supply_metadata(cls, value):
        """The wrapper owns task binding and the blinded-token echo.

        ``Decision`` exposes those optional fields for the legacy single-task
        CLI parser. They must not become a second, contradictory token or task
        channel inside a combined response.
        """
        if not isinstance(value, dict):
            return value
        for task in ANALYSIS_TASKS:
            nested = value.get(task)
            if not isinstance(nested, dict):
                continue
            forbidden = sorted({"task", "paper_id"}.intersection(nested))
            if forbidden:
                raise ValueError(
                    f"{task} must not supply wrapper-owned field(s): "
                    f"{', '.join(forbidden)}")
        return value

    @model_validator(mode="after")
    def _bind_and_validate_task_decisions(self) -> CombinedAnalysisDecision:
        """Bind both nested objects to their fixed tasks and shared token.

        Binding by re-validating, rather than assigning fields directly, keeps
        the exclusion-only ``wrong_text`` guard in :class:`Decision` active.
        A bad half therefore invalidates the whole combined attempt (DC54).
        """
        for task in ANALYSIS_TASKS:
            nested = getattr(self, task)
            payload = nested.model_dump()
            payload.update({"task": task, "paper_id": self.paper_id})
            setattr(self, task, Decision.model_validate(payload))
        return self

    def task_decisions(self) -> dict[str, Decision]:
        """Return the two persisted task judgments in their stable order."""
        return {task: getattr(self, task) for task in ANALYSIS_TASKS}


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


def parse_combined_analysis(raw: str, *, paper_id: str | None = None
                            ) -> tuple[CombinedAnalysisDecision, bool]:
    """Parse one post-gate reply into both task judgments.

    The return shape mirrors :func:`parse_decision`. Any malformed, missing, or
    task-invalid half raises one ``ParseFailure`` carrying the original response
    so the caller retries the combined call atomically.
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
            f"expected a JSON object, got {type(payload).__name__}", raw=raw,
            paper_id=paper_id)

    payload.setdefault("paper_id", paper_id)
    try:
        return CombinedAnalysisDecision.model_validate(payload), was_fenced
    except Exception as exc:
        raise ParseFailure(str(exc), raw=raw, paper_id=paper_id) from exc


def _decision_input_schema(task: str) -> dict:
    """JSON Schema for one model-supplied, task-bound decision."""
    schema = Decision.model_json_schema()
    properties = {key: deepcopy(value) for key, value in schema["properties"].items()
                  if key not in ("task", "paper_id")}
    allowed = [decision for decision in DECISIONS
               if task == "exclusion" or decision not in EXCLUSION_ONLY_DECISIONS]
    properties["decision"] = {"type": "string", "enum": list(allowed),
                              "description": " | ".join(allowed)}
    properties["reasoning"]["maxLength"] = REASONING_MAX_CHARS
    return {
        "type": "object",
        "properties": properties,
        "required": ["decision", "reasoning", "promptbook_evidence", "confidence"],
        "additionalProperties": False,
    }


def tool_schema(task: str) -> dict:
    """The JSON Schema payload for a Batch API run of one task.

    Built from the same model as the CLI route parses into, so the two cannot
    drift (DC35). `task` and `paper_id` are dropped: the wrapper knows both, and
    asking the model for them invites it to guess an identifier it was
    deliberately never told (the Reading Room blinds it).
    """
    if task not in TASKS:
        raise ValueError(f"unknown task {task!r}; expected one of {TASKS}")

    return {
        "name": f"record_{task}_decision",
        "description": f"Record the {task} judgment for the paper above.",
        "input_schema": _decision_input_schema(task),
    }


def combined_analysis_tool_schema() -> dict:
    """The JSON Schema payload for one post-gate combined API call (DC54)."""
    return {
        "name": "record_combined_analysis_decisions",
        "description": (
            "Record independent power-analysis and data-analysis judgments for "
            "the one gate-surviving paper above."),
        "input_schema": {
            "type": "object",
            "properties": {
                task: _decision_input_schema(task) for task in ANALYSIS_TASKS
            },
            "required": list(ANALYSIS_TASKS),
            "additionalProperties": False,
        },
    }


# ============================================================================
# Ground-truth-shaped output (research design/GROUND_TRUTH_OUTPUT_PLAN.md)
# ============================================================================
#
# The models above are the round-1 contract and stay unchanged so that
# already-paid raw replies still re-check. Everything below is the new contract
# for the 43-column HLS output:
#
#   ExclusionWithReason   the gate call, now also returning `exclusion_reason`
#   FullAnalysis          one post-gate call: study design, then power, then data
#
# Strictness is the point (plan step 2). Every key is required, unknown keys
# are rejected, nothing is coerced ("10" is not 10), and an answer that
# contradicts itself is rejected rather than repaired. A rejected answer is a
# logged retry, never a patched one.
#
# Column names, export rules, and scoring rules live in
# data/field_dictionary.csv; the vocabularies below are the single source for
# its `allowed_values` column (a test checks they agree).

NOT_REPORTED = "not_reported"   # the paper was checked and does not say
UNCLEAR = "unclear"             # the paper says something contradictory or unreadable

# Decision 18: every list is a starting point. A value outside it is written
# `other: <short label>` and logged, so recurring labels can be promoted into
# the list in a later promptbook version (pattern rule, never one paper).
OTHER_LABEL_MAX = 60
_OTHER = re.compile(r"^other: (\S.*)$")

# Units are lowercase singular. `matched_pair` and `stratum` are restriction
# groupings, not sources of correlation: they appear as an outer level when
# clusters were randomized within them (10 of 87 human `ind_samp_unit` values),
# but never in `correlated_units`.
PERSON_UNITS = ("patient", "participant", "student")
CLUSTER_UNITS = ("clinic", "school", "classroom", "practice", "hospital", "ward",
                 "physician", "nursing_home", "village", "community", "household",
                 "family", "worksite", "site")
GROUPING_UNITS = ("matched_pair", "stratum")
UNITS = PERSON_UNITS + CLUSTER_UNITS + GROUPING_UNITS

RESTRICTION_SCHEMES = ("pair_matched", "matched_sets", "stratified", "blocked",
                       "constrained", "minimization")
DATA_METHODS = ("mixed_effects", "gee", "cluster_level", "cluster_robust_se",
                "permutation", "bayesian_hierarchical", "cluster_fixed_effects",
                "individual_level")
POWER_METHODS = ("formula", "simulation")
# No few-clusters tag: its 40-cluster threshold and whether it decides
# data_correct are still open with Deb (Deb.md 3a-3c), so the contract records
# only the fact (`small_sample_correction`) and makes no threshold call.
DATA_COMMENT_TAGS = ("unclear_reporting", "missing_method", "wrong_level",
                     "restriction_ignored", "longitudinality_ignored",
                     "label_inconsistency")

# DC45: the promptbook's E-numbers are the exclusion taxonomy. E12 (protocol)
# and E17 (random duplicate drop) are retired cross-paper rules and E18 is the
# abstention, so none of them can be a reason.
EXCLUSION_REASONS = {
    "E1": "preprint", "E2": "methodology_journal", "E3": "stepped_wedge_design",
    "E4": "secondary_in_title", "E5": "secondary_analysis", "E6": "baseline_only",
    "E7": "implementation_study", "E8": "methods_paper", "E9": "not_randomized",
    "E10": "not_group_randomized", "E11": "qualitative_study", "E13": "pilot_study",
    "E14": "cohort_study", "E15": "review_article", "E16": "comment_or_letter",
}
# Decision 18 applies to reasons too (user, 2026-11-24): a paper that is plainly
# ineligible for a reason no criterion names is excluded under E19 with
# `exclusion_reason: "other: <label>"`. E19 is never itself a reason value, so
# every E19 exclusion carries a label that gets logged for promotion.
OTHER_EXCLUSION_RULE = "E19"

NOTE_MAX_CHARS = 200
VARIABLES_MAX_CHARS = 120
SOURCE_NOTE_MAX_CHARS = 80


def open_choice(value: str, allowed: tuple[str, ...], field: str) -> str:
    """Accept a listed value or `other: <label>`; reject anything else.

    Not a normalizer: `Clinic` or `nursing home` is rejected, not rewritten,
    because a reply that misspells the list is a prompt problem worth seeing.
    """
    if value in allowed:
        return value
    match = _OTHER.match(value)
    if match:
        label = match.group(1).strip()
        if len(label) > OTHER_LABEL_MAX:
            raise ValueError(
                f"{field}: other-label is {len(label)} chars, cap is {OTHER_LABEL_MAX}")
        return f"other: {label}"
    raise ValueError(
        f"{field} must be one of {allowed} or 'other: <label>', got {value!r}")


def is_other(value: str | None) -> bool:
    return bool(value) and value.startswith("other: ")


def other_label(value: str) -> str:
    """The free label of an `other: <label>` value (the paper's own wording)."""
    return value[len("other: "):] if is_other(value) else value


def _unique(values: list[str], field: str) -> list[str]:
    if len(set(values)) != len(values):
        raise ValueError(f"{field} lists a value twice: {values}")
    return values


class _Strict(BaseModel):
    """Base for the new contract: no extra keys, no coercion, no defaults."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class _Judgment(_Strict):
    """The four fields every scored judgment carries (DC13, DC27)."""

    decision: Literal["yes", "no", "undecidable"]
    reasoning: str = Field(min_length=1, max_length=REASONING_MAX_CHARS)
    promptbook_evidence: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)

    def as_decision(self, *, task: str, paper_id: str | None) -> Decision:
        """The legacy per-task row, so storage and rule checks stay shared."""
        return Decision.model_validate({
            "decision": self.decision, "reasoning": self.reasoning,
            "promptbook_evidence": self.promptbook_evidence,
            "confidence": self.confidence, "task": task, "paper_id": paper_id})


# ------------------------------------------------------------ exclusion gate


class ExclusionWithReason(_Strict):
    """The gate call plus a standard reason (plan decision 4).

    `exclusion_reason` duplicates the deciding rule on purpose: it is the field
    the CSV exports, while `promptbook_evidence` may cite several rules. The
    two must agree, so the export never names a rule the model did not cite.
    """

    decision: Literal["yes", "no", "undecidable", "wrong_text"]
    # An E-number from EXCLUSION_REASONS, or `other: <label>` under E19.
    exclusion_reason: str | None
    reasoning: str = Field(min_length=1, max_length=REASONING_MAX_CHARS)
    promptbook_evidence: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    # Wrapper-owned: echoed on the CLI route, absent from the API schema.
    paper_id: str | None = None

    @field_validator("exclusion_reason")
    @classmethod
    def _reason(cls, value: str | None) -> str | None:
        return None if value is None else open_choice(
            value, tuple(EXCLUSION_REASONS), "exclusion_reason")

    @model_validator(mode="after")
    def _reason_matches_decision(self) -> ExclusionWithReason:
        if self.decision != "yes":
            if self.exclusion_reason is not None:
                raise ValueError(
                    f"exclusion_reason must be null unless decision is 'yes' "
                    f"(decision={self.decision!r})")
            return self
        if self.exclusion_reason is None:
            raise ValueError(
                f"an exclusion needs exclusion_reason from {list(EXCLUSION_REASONS)} "
                f"or 'other: <label>'")
        # The rule the reason stands for must be the one the evidence cites.
        rule = (OTHER_EXCLUSION_RULE if is_other(self.exclusion_reason)
                else self.exclusion_reason)
        cited = [f"{letter}{number}" for letter, number
                 in RULE_ID.findall(self.promptbook_evidence)]
        if rule not in cited:
            raise ValueError(
                f"exclusion_reason {self.exclusion_reason!r} needs {rule} cited in "
                f"promptbook_evidence ({self.promptbook_evidence[:80]!r})")
        return self

    def as_decision(self) -> Decision:
        return Decision.model_validate({
            "decision": self.decision, "reasoning": self.reasoning,
            "promptbook_evidence": self.promptbook_evidence,
            "confidence": self.confidence, "task": "exclusion",
            "paper_id": self.paper_id})

    def reason_name(self) -> str | None:
        """The readable export value, e.g. 'secondary_analysis' or 'other: <label>'."""
        if is_other(self.exclusion_reason):
            return self.exclusion_reason
        return EXCLUSION_REASONS.get(self.exclusion_reason or "")


# ------------------------------------------------------------- study design


class ClusterCount(_Strict):
    """How many units sit at one level. `per` marks a per-parent count."""

    kind: Literal["exact", "approximate", "range", "not_reported", "unclear"]
    value: int | None = Field(ge=0)
    low: int | None = Field(ge=0)
    high: int | None = Field(ge=0)
    per: str | None

    @model_validator(mode="after")
    def _shape(self) -> ClusterCount:
        has_value = self.value is not None
        has_range = self.low is not None or self.high is not None
        if self.kind in ("exact", "approximate"):
            if not has_value or has_range:
                raise ValueError(f"a {self.kind} count needs value and no low/high")
        elif self.kind == "range":
            if has_value or self.low is None or self.high is None:
                raise ValueError("a range count needs low and high and no value")
            if self.low >= self.high:
                raise ValueError(f"range low {self.low} must be below high {self.high}")
        elif has_value or has_range or self.per is not None:
            raise ValueError(f"a {self.kind} count carries no numbers and no per")
        return self


class Level(_Strict):
    unit: str
    count: ClusterCount

    @field_validator("unit")
    @classmethod
    def _unit(cls, value: str) -> str:
        return open_choice(value, UNITS, "unit")


class RestrictedRandomization(_Strict):
    status: Literal["restricted", "none", "not_reported", "unclear"]
    schemes: list[str]
    variables: str | None = Field(max_length=VARIABLES_MAX_CHARS)

    @field_validator("schemes")
    @classmethod
    def _schemes(cls, values: list[str]) -> list[str]:
        return _unique([open_choice(v, RESTRICTION_SCHEMES, "scheme") for v in values],
                       "schemes")

    @model_validator(mode="after")
    def _schemes_iff_restricted(self) -> RestrictedRandomization:
        if (self.status == "restricted") != bool(self.schemes):
            raise ValueError("schemes must be non-empty exactly when status is 'restricted'")
        if self.status != "restricted" and self.variables is not None:
            raise ValueError("variables must be null unless status is 'restricted'")
        return self


class IccValue(_Strict):
    kind: Literal["exact", "range"]
    value: float | None = Field(ge=-1.0, le=1.0)
    low: float | None = Field(ge=-1.0, le=1.0)
    high: float | None = Field(ge=-1.0, le=1.0)
    applies_to: str | None = Field(max_length=OTHER_LABEL_MAX)

    @model_validator(mode="after")
    def _shape(self) -> IccValue:
        if self.kind == "exact":
            if self.value is None or self.low is not None or self.high is not None:
                raise ValueError("an exact ICC needs value and no low/high")
        else:
            if self.value is not None or self.low is None or self.high is None:
                raise ValueError("an ICC range needs low and high and no value")
            if self.low >= self.high:
                raise ValueError(f"ICC range low {self.low} must be below high {self.high}")
        return self


class Icc(_Strict):
    status: Literal["reported", "not_reported", "unclear"]
    values: list[IccValue]

    @model_validator(mode="after")
    def _values_iff_reported(self) -> Icc:
        if (self.status == "reported") != bool(self.values):
            raise ValueError("ICC values must be non-empty exactly when status is 'reported'")
        if len(self.values) > 1 and any(not v.applies_to for v in self.values):
            raise ValueError("with several ICCs, each needs applies_to (its level or group)")
        return self


class Longitudinal(_Strict):
    """How often the primary outcome is measured, as two facts (user, 2026-11-24).

    The human `n_long` is ambiguous for the commonest CRT schedule, baseline
    plus one follow-up: of the reviewed papers with a clear schedule, most were
    coded 2 (baseline counted) and a minority 1. Asking for the facts instead of
    the count lets code export either convention, so settling the convention
    with Deb changes only the export, never a paid run.

    `baseline_measured`: the primary outcome itself was measured before the
    intervention (same people or a fresh sample of the same clusters).
    `n_followup`: measurements of it after the intervention started.
    """

    baseline_measured: Literal["yes", "no", "not_reported", "unclear"]
    n_followup: int | Literal["not_reported", "unclear"]

    @field_validator("n_followup")
    @classmethod
    def _followups(cls, value):
        # A kept trial estimates a post-randomization effect (E6), so >= 1.
        if isinstance(value, int) and value < 1:
            raise ValueError(f"n_followup must be at least 1, got {value}")
        return value

    def _unknown(self) -> str | None:
        parts = (self.baseline_measured, self.n_followup)
        if UNCLEAR in parts:
            return UNCLEAR
        if NOT_REPORTED in parts:
            return NOT_REPORTED
        return None

    def n_long(self) -> int | str:
        """Every measurement occasion, baseline included (the export rule).

        Matches the majority human coding and GLIMMPSE's count of repeated
        measures. `not_reported` / `unclear` when either fact is unknown.
        """
        return self._unknown() or self.n_followup + (self.baseline_measured == "yes")

    def n_long_followup_only(self) -> int | str:
        """The minority convention: post-intervention occasions only."""
        return self.n_followup

    def has_repeated_measures(self) -> bool | None:
        """True / False only when every reasonable convention agrees.

        Two or more follow-ups is repeated on any reading; one follow-up and no
        baseline is a single measurement. Baseline plus one follow-up is left
        open: baseline may enter as a repeated outcome, a covariate, or not at
        all, and the right `longitudinality` depends on which.
        """
        if isinstance(self.n_followup, str):
            return None
        if self.n_followup >= 2:
            return True
        return False if self.baseline_measured == "no" else None


class StudyDesign(_Strict):
    """Facts both judgments read. Recorded once, before either judgment."""

    n_trt: int | Literal["not_reported", "unclear"]
    # Innermost (the person measured) first, outermost last.
    levels: list[Level] = Field(min_length=2, max_length=6)
    unit_rand: str
    ind_samp_unit: str
    correlated_units: list[str] = Field(min_length=1)
    restricted_randomization: RestrictedRandomization
    icc: Icc
    longitudinal: Longitudinal
    stepped_wedge: Literal["yes", "no", "unclear", "not_reported"]

    @field_validator("n_trt")
    @classmethod
    def _arms(cls, value):
        if isinstance(value, int) and value < 2:
            raise ValueError(f"n_trt must be at least 2, got {value}")
        return value

    @field_validator("unit_rand", "ind_samp_unit")
    @classmethod
    def _one_unit(cls, value: str, info) -> str:
        return open_choice(value, UNITS, info.field_name)

    @field_validator("correlated_units")
    @classmethod
    def _correlated(cls, values: list[str]) -> list[str]:
        return _unique([open_choice(v, UNITS, "correlated_units") for v in values],
                       "correlated_units")

    def units(self) -> list[str]:
        return [level.unit for level in self.levels]

    def cluster_units(self) -> list[str]:
        """Every unit above the person measured."""
        return self.units()[1:]

    @model_validator(mode="after")
    def _structure(self) -> StudyDesign:
        units = _unique(self.units(), "levels")
        for field in ("unit_rand", "ind_samp_unit"):
            if getattr(self, field) not in units:
                raise ValueError(
                    f"{field} {getattr(self, field)!r} is not one of the levels {units}")
        if units.index(self.ind_samp_unit) < units.index(self.unit_rand):
            raise ValueError("ind_samp_unit must be unit_rand or a unit further out")
        for unit in self.correlated_units:
            if unit not in units[1:]:
                raise ValueError(f"correlated unit {unit!r} is not a level above the person")
            if unit in GROUPING_UNITS:
                raise ValueError(
                    f"{unit!r} is a restriction grouping, recorded under "
                    f"restricted_randomization, not a correlated unit")
        for position, level in enumerate(self.levels):
            per = level.count.per
            if per is not None and per not in units[position + 1:]:
                raise ValueError(
                    f"{level.unit} count is per {per!r}, which is not a level further out")
        if (any(u in GROUPING_UNITS for u in units)
                and self.restricted_randomization.status != "restricted"):
            raise ValueError(
                "a matched_pair/stratum level needs restricted_randomization 'restricted'")
        return self

    def n_levels(self) -> int:
        """Q8 (Deb): levels of clustering above the individual = units - 1."""
        return len(self.levels) - 1

    def n_long(self) -> int | str:
        return self.longitudinal.n_long()

    def has_repeated_measures(self) -> bool | None:
        return self.longitudinal.has_repeated_measures()


# ------------------------------------------------- what a correct one needs


class Should(_Strict):
    """What a correct analysis of this design must account for (the `*_should` columns).

    Asked of the model *and* derived by code from the design, so the two can be
    compared (user, 2026-11-24). Never checked against `done` or the verdict:
    it is a second opinion to compare, not a constraint to enforce.
    """

    units: list[str]
    restricted_rand: bool
    longitudinality: bool

    @field_validator("units")
    @classmethod
    def _units(cls, values: list[str]) -> list[str]:
        return _unique([open_choice(v, UNITS, "should.units") for v in values],
                       "should.units")


# ------------------------------------------------------------ power analysis


class PowerDone(_Strict):
    """What the power calculation accounted for. Not a method pick (plan Q4)."""

    reported: Literal["yes", "no"]
    clustering: Literal["all_levels", "some_levels", "ignored", "unclear"] | None
    units_accounted: list[str]
    restricted_rand: Literal["accounted", "ignored", "not_applicable", "unclear"] | None
    # Q4: longitudinality has no `unclear`.
    longitudinality: Literal["accounted", "ignored", "not_applicable"] | None
    method: str | None
    source_note: str | None = Field(max_length=SOURCE_NOTE_MAX_CHARS)
    timing: Literal["before_trial", "post_hoc", "not_stated"] | None

    @field_validator("units_accounted")
    @classmethod
    def _units(cls, values: list[str]) -> list[str]:
        return _unique([open_choice(v, UNITS, "units_accounted") for v in values],
                       "units_accounted")

    @field_validator("method")
    @classmethod
    def _method(cls, value: str | None) -> str | None:
        return None if value is None else open_choice(
            value, POWER_METHODS + ("not_described",), "power method")

    @model_validator(mode="after")
    def _absent_means_null(self) -> PowerDone:
        parts = (self.clustering, self.restricted_rand, self.longitudinality,
                 self.method, self.timing)
        if self.reported == "no":
            if any(p is not None for p in parts) or self.units_accounted or self.source_note:
                raise ValueError("with no power calculation reported, every other "
                                 "power_done field is null and units_accounted is []")
        elif any(p is None for p in parts):
            raise ValueError("a reported power calculation needs clustering, "
                             "restricted_rand, longitudinality, method and timing")
        return self


class PowerAnalysis(_Judgment):
    should: Should
    done: PowerDone


# ------------------------------------------------------------- data analysis


class DataDone(_Strict):
    """The one main primary-outcome analysis (plan decision 12)."""

    method: str
    planned_only: bool | None  # Q7: a planned-only analysis can still be correct
    levels_modeled: list[str]
    clustering: Literal["all_levels", "some_levels", "ignored", "unclear"] | None
    restricted_rand: Literal["accounted", "ignored", "not_applicable", "unclear"] | None
    longitudinality: Literal["accounted", "ignored", "not_applicable"] | None
    small_sample_correction: Literal["yes", "no", "unclear"] | None

    @field_validator("method")
    @classmethod
    def _method(cls, value: str) -> str:
        return open_choice(value, DATA_METHODS + (NOT_REPORTED,), "data method")

    @field_validator("levels_modeled")
    @classmethod
    def _levels(cls, values: list[str]) -> list[str]:
        return _unique([open_choice(v, UNITS, "levels_modeled") for v in values],
                       "levels_modeled")

    @model_validator(mode="after")
    def _absent_means_null(self) -> DataDone:
        parts = (self.planned_only, self.clustering, self.restricted_rand,
                 self.longitudinality, self.small_sample_correction)
        if self.method == NOT_REPORTED:
            if any(p is not None for p in parts) or self.levels_modeled:
                raise ValueError("with no analysis method reported, every other "
                                 "data_done field is null and levels_modeled is []")
        elif any(p is None for p in parts):
            raise ValueError("a reported analysis needs planned_only, clustering, "
                             "restricted_rand, longitudinality and small_sample_correction")
        return self


class DataComment(_Strict):
    tags: list[str]
    note: str | None = Field(max_length=NOTE_MAX_CHARS)

    @field_validator("tags")
    @classmethod
    def _tags(cls, values: list[str]) -> list[str]:
        return _unique([open_choice(v, DATA_COMMENT_TAGS, "data_comment tag")
                        for v in values], "tags")


class DataAnalysis(_Judgment):
    should: Should
    done: DataDone
    comment: DataComment


# --------------------------------------------------------- the whole answer


def _accounting_problems(task: str, done, design: StudyDesign,
                         units: list[str]) -> list[str]:
    """Contradictions between one task's `done` record and the shared design."""
    problems = []
    stray = [u for u in units if u not in design.cluster_units()]
    if stray:
        problems.append(f"{task}: {stray} are not levels above the person")
    needed = set(design.correlated_units)
    if done.clustering == "all_levels" and not needed <= set(units):
        problems.append(f"{task}: clustering 'all_levels' but "
                        f"{sorted(needed - set(units))} of correlated_units not accounted for")
    if done.clustering == "some_levels" and (not units or needed <= set(units)):
        problems.append(f"{task}: clustering 'some_levels' needs some, not all, "
                        f"correlated units accounted for")
    if done.clustering == "ignored" and units:
        problems.append(f"{task}: clustering 'ignored' but units listed {units}")

    status = design.restricted_randomization.status
    if status in ("none", NOT_REPORTED) and done.restricted_rand != "not_applicable":
        problems.append(f"{task}: the design has no restriction, so restricted_rand "
                        f"must be 'not_applicable'")
    if status == "restricted" and done.restricted_rand == "not_applicable":
        problems.append(f"{task}: the design is restricted, so restricted_rand "
                        f"cannot be 'not_applicable'")

    repeated = design.has_repeated_measures()
    if repeated is False and done.longitudinality != "not_applicable":
        problems.append(f"{task}: one follow-up and no baseline, so longitudinality "
                        f"must be 'not_applicable'")
    if repeated is True and done.longitudinality == "not_applicable":
        problems.append(f"{task}: two or more follow-ups, so longitudinality cannot "
                        f"be 'not_applicable'")
    return problems


def _verdict_problems(task: str, decision: str, done) -> list[str]:
    """P3 / D-rules: a `yes` needs every level and any restriction handled.

    Only the direction the rubric fixes is checked. A `no` with everything
    handled is legal (P4, P5, P15, D2-D4 can still fail a paper).
    """
    if decision != "yes":
        return []
    if done.clustering != "all_levels":
        return [f"{task}: 'yes' requires clustering 'all_levels', got {done.clustering!r}"]
    if done.restricted_rand not in ("accounted", "not_applicable"):
        return [f"{task}: 'yes' requires restriction accounted or not applicable, "
                f"got {done.restricted_rand!r}"]
    return []


class FullAnalysis(_Strict):
    """One post-gate call: design, then power, then data (DC54, plan step 3).

    The two judgments stay independent: each is checked against the shared
    design, never against the other judgment. A contradiction anywhere rejects
    the whole answer, so no half is ever stored without its sibling.
    """

    design: StudyDesign
    power_analysis: PowerAnalysis
    data_analysis: DataAnalysis
    # Wrapper-owned: echoed on the CLI route, absent from the API schema.
    paper_id: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> FullAnalysis:
        design, power, data = self.design, self.power_analysis, self.data_analysis
        problems: list[str] = []

        if power.done.reported == "no":
            if power.decision == "yes":
                problems.append("power_analysis: 'yes' with no power calculation reported (P6)")
        else:
            problems += _accounting_problems("power_analysis", power.done, design,
                                             power.done.units_accounted)
            problems += _verdict_problems("power_analysis", power.decision, power.done)

        if data.done.method == NOT_REPORTED:
            if data.decision == "yes":
                problems.append("data_analysis: 'yes' with no analysis reported (D4)")
        else:
            problems += _accounting_problems("data_analysis", data.done, design,
                                             data.done.levels_modeled)
            problems += _verdict_problems("data_analysis", data.decision, data.done)
            if data.decision == "yes" and data.done.method in ("individual_level",
                                                               "cluster_fixed_effects"):
                problems.append(f"data_analysis: 'yes' with method "
                                f"{data.done.method!r} (D6/D7)")

        tags = set(data.comment.tags)
        if "restriction_ignored" in tags and data.done.restricted_rand != "ignored":
            problems.append("data_comment: restriction_ignored but restricted_rand "
                            "is not 'ignored'")
        if "longitudinality_ignored" in tags and data.done.longitudinality != "ignored":
            problems.append("data_comment: longitudinality_ignored but longitudinality "
                            "is not 'ignored'")

        # `should` is structural only: real levels, never a restriction grouping.
        for task, judgment in (("power_analysis", power), ("data_analysis", data)):
            stray = [u for u in judgment.should.units if u not in design.cluster_units()]
            if stray:
                problems.append(f"{task}.should: {stray} are not levels above the person")
            grouping = [u for u in judgment.should.units if u in GROUPING_UNITS]
            if grouping:
                problems.append(f"{task}.should: {grouping} is a restriction grouping; "
                                f"use restricted_rand")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def task_decisions(self) -> dict[str, Decision]:
        """The two legacy per-task rows, for the existing judgments table."""
        return {task: getattr(self, task).as_decision(task=task, paper_id=self.paper_id)
                for task in ANALYSIS_TASKS}


# ------------------------------------------------------------------ parsing


def _load_object(raw: str, paper_id: str | None) -> tuple[dict, bool]:
    text, was_fenced = _strip_fences(raw)
    if not text:
        raise ParseFailure("empty reply", raw=raw, paper_id=paper_id)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseFailure(f"not valid JSON: {exc}", raw=raw, paper_id=paper_id) from exc
    if not isinstance(payload, dict):
        raise ParseFailure(f"expected a JSON object, got {type(payload).__name__}",
                           raw=raw, paper_id=paper_id)
    return payload, was_fenced


def parse_exclusion_with_reason(raw: str, *, paper_id: str | None = None
                                ) -> tuple[ExclusionWithReason, bool]:
    """Parse a gate reply under the new contract. Raises ParseFailure."""
    payload, was_fenced = _load_object(raw, paper_id)
    payload.setdefault("paper_id", paper_id)
    try:
        return ExclusionWithReason.model_validate(payload), was_fenced
    except Exception as exc:
        raise ParseFailure(str(exc), raw=raw, paper_id=paper_id) from exc


def parse_full_analysis(raw: str, *, paper_id: str | None = None
                        ) -> tuple[FullAnalysis, bool]:
    """Parse one post-gate reply. Any bad part rejects the whole answer."""
    payload, was_fenced = _load_object(raw, paper_id)
    payload.setdefault("paper_id", paper_id)
    try:
        return FullAnalysis.model_validate(payload), was_fenced
    except Exception as exc:
        raise ParseFailure(str(exc), raw=raw, paper_id=paper_id) from exc


# Free-text fields: an "other: ..." inside one is prose, not a vocabulary miss.
_FREE_TEXT_FIELDS = frozenset({"reasoning", "promptbook_evidence", "note",
                               "variables", "source_note", "applies_to", "paper_id"})


def other_labels(answer: BaseModel) -> list[tuple[str, str]]:
    """Every `other: <label>` in a validated answer, as (field path, label).

    Decision 18: a recurring label is promoted into its list in a later
    promptbook version, so each one is logged. Paths look like
    `design.levels[2].unit`, so a reader can find it in the stored JSON.
    """
    found: list[tuple[str, str]] = []

    def walk(node, path: str, key: str = "") -> None:
        if isinstance(node, dict):
            for name, value in node.items():
                walk(value, f"{path}.{name}" if path else name, name)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]", key)
        elif isinstance(node, str) and key not in _FREE_TEXT_FIELDS and is_other(node):
            found.append((path, other_label(node)))

    walk(answer.model_dump(), "")
    return found


# ----------------------------------------------------- provider JSON Schema


def _inline_refs(node, defs: dict):
    """Inline `$ref`s so the schema needs no `$defs` support from a provider."""
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline_refs(deepcopy(defs[node["$ref"].rsplit("/", 1)[-1]]), defs)
        return {key: _inline_refs(value, defs) for key, value in node.items()
                if key not in ("$defs", "title", "default")
                and not (key == "description" and isinstance(value, str))}
    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]
    return node


def _close_objects(node):
    """Every object: all keys required, no extra keys (the provider's half)."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"])
        for value in node.values():
            _close_objects(value)
    elif isinstance(node, list):
        for item in node:
            _close_objects(item)
    return node


def _output_schema(model: type[BaseModel]) -> dict:
    """Provider syntax constraint for one model. Never replaces local checks.

    `paper_id` is dropped for the same reason as in :func:`tool_schema`: the
    wrapper owns it, and asking for it invites a guessed identifier.
    """
    schema = model.model_json_schema()
    inlined = _inline_refs(schema, schema.get("$defs", {}))
    inlined["properties"].pop("paper_id", None)
    return _close_objects(inlined)


def exclusion_with_reason_output_schema() -> dict:
    return _output_schema(ExclusionWithReason)


def full_analysis_output_schema() -> dict:
    return _output_schema(FullAnalysis)
