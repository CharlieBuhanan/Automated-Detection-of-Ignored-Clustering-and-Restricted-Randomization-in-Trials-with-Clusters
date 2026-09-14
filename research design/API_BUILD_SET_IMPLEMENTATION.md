# Build-set API implementation and offline-validation handoff

Status: design handoff, 2026-08-28. Implement this plan without making any live
Anthropic request. A synchronous preflight, batch creation, polling, result
download, cancellation, and deletion are all out of scope until the user gives
a separate explicit approval after reviewing a frozen manifest and cost ceiling.

This document is deliberately sturdy enough to hand to a fresh coding agent.
Read `research design/PLAN.md`, `research design/Design_Choices.md`,
`ReadingRoom/tests/TEST_PLAN.md`, `src/reading_room.py`, `src/schemas.py`,
`src/db.py`, and `scripts/21_check_responses.py` before editing. Preserve the
user's dirty worktree and do not rewrite existing raw evidence.

## Objective

Build a resumable, idempotent Anthropic Message Batches pipeline for the Human
Labelled Set build split. It must:

1. reuse every already accepted paper/task judgment;
2. run exclusion separately;
3. use one combined power-plus-data call when both analysis judgments are
   missing;
4. use a single-task legacy call when exactly one analysis judgment is missing;
5. pin Claude Sonnet 5 and `output_config.effort: medium` for every new call;
6. produce a complete offline request plan, provenance record, token/cost
   estimate, and validation report before anything can be submitted;
7. ingest results exactly once, preserving raw responses and request-level
   usage; and
8. evaluate power, data, and exclusion separately against build labels.

The implementation is complete only when the offline tests and dry-run
acceptance checks below pass. Do not submit a batch as part of this handoff.

## Current inventory and definitions

As of 2026-08-28:

| Artifact | State | Reuse consequence |
|---|---:|---|
| Exclusion round 1 | 49 checked and persisted v1 primary judgments | Accepted; never purchase these paper/task pairs again for the reuse-first build plan |
| Data-analysis round 1 | 49 raw responses: 40 checker-passing candidates awaiting `--write`; 1 schema/parse failure; 8 process failures | Only persisted, fully validated responses become accepted/reusable; the nine failures remain missing until a narrow retry or human review resolves them |
| Power-analysis responses | none | Missing |
| Evaluation | `src/evaluate.py` + `scripts/22_evaluate.py` | Read-only dashboard/CSV/JSON report now available |

Use these terms precisely:

- **raw**: provider or CLI output exists;
- **candidate**: the process/provider says it succeeded, but local validation has
  not completed;
- **accepted**: transport, schema, semantic, rule-ID, token binding, promptbook
  version/hash, and provenance checks all passed, and the judgment is persisted;
- **reusable**: accepted and selected by the explicit reuse policy;
- **missing**: no reusable judgment exists for that paper/task/config policy.

Never treat exit code 0, HTTP 200, batch result `succeeded`, or parseable JSON as
synonyms for accepted.

### Compatibility decision

The user explicitly chose to reuse the existing high-effort judgments while all
new requests use medium effort. Preserve that decision without hiding it:

- retain model, effort, promptbook hash, route, source run, and response ID for
  every judgment;
- output metrics stratified by configuration;
- permit an additional `reuse_first_mixed` development summary;
- label that pooled summary as mixed-configuration and exploratory;
- do not use the pooled summary for the DC17 plateau rule or claim it is a clean
  medium-effort estimate; and
- keep the final holdout wholly medium effort and untouched until the end.

### API transport and SDK pin

The sole API classification-output transport is native JSON Schema structured
output:

```python
output_config = {
    "effort": "medium",
    "format": {"type": "json_schema", "schema": schema},
}
```

Use `anthropic==1.0.0` (Python >=3.10) for implementation and CI. This version
matches the current supported `output_config.format` API contract; it is pinned
so a generated batch-request shape cannot drift under an unreviewed SDK update.
API classification requests must not declare a result tool, use `tool_choice`,
or silently fall back to free-form JSON. Local Pydantic, token-binding,
rule-prefix, and scientific semantic validation remain mandatory after the
provider returns schema-constrained JSON.

## Required architecture

```text
labels + manifest + cached text + promptbooks + accepted judgments
                              |
                              v
                    offline eligibility planner
                    /          |             \
              reuse       exclusion       analysis matrix
                            missing       /       |       \
                                      both     power     data
                                      missing  missing   missing
                                         |        |         |
                                      combined  power-only data-only
                                           \       |       /
                                            frozen requests
                                                  |
                                     plan hash + cost ceiling
                                                  |
                         STOP: explicit user approval is required here
                                                  |
                                  Message Batch create/collect
                                                  |
                                 raw immutable JSONL results
                                                  |
                                  validate -> atomic persist
                                                  |
                             per-task, per-config evaluation
```

Keep planning, network I/O, response validation, persistence, and evaluation as
separate layers. A bug in evaluation must never trigger a call; a bug in result
parsing must never destroy raw output; a rerun must never double-purchase or
double-insert a successful judgment.

## Proposed modules and commands

Names may be adjusted to match the repository, but preserve the separation.

### `src/api_batch.py`

Pure or nearly pure domain functions:

- `accepted_judgment_inventory(conn)`: one normalized record per accepted
  paper/task judgment with provenance;
- `build_eligibility(...)`: active build paper IDs only, excluding holdout and
  manifest `DROPPED` rows;
- `plan_missing_requests(...)`: apply the reuse matrix and return typed request
  plans without importing or constructing an API client;
- `build_exclusion_request(...)`, `build_single_analysis_request(...)`, and
  `build_combined_analysis_request(...)`;
- canonical JSON serialization and SHA-256 request/plan hashes;
- deterministic opaque `custom_id` generation;
- offline token/cost estimation;
- provider-result normalization;
- response parsing through `src/schemas.py`; and
- retry classification that distinguishes invalid request, transient provider
  error, expired, canceled, truncation, schema failure, and semantic failure.

No function in this module should read `ANTHROPIC_API_KEY` at import time.

### `src/batch_store.py`

SQLite migrations and idempotent persistence:

- a `classification_runs` table for configuration and hashes;
- a `classification_requests` table keyed by deterministic request ID/hash;
- a response table or equivalent immutable response metadata record;
- nullable run/response foreign keys on new judgment rows; and
- a uniqueness constraint that prevents the same provider response/task from
  becoming two judgments.

Migrations must preserve the current 49 judgments. Backfill their source as a
legacy Reading Room run using `raw/exclusion_r1/run_environment.json` and the
checked report; never rewrite their scientific fields.

Recommended run fields:

| Field group | Required values |
|---|---|
| identity | local `run_id`, provider batch ID if submitted, phase, split |
| model | model ID, effort, thinking mode if reported, max tokens |
| prompt | promptbook version and per-file hashes, system-prompt hash, prompt-template/schema version |
| code | git commit including dirty marker, Python and SDK versions |
| planning | plan SHA-256, request count, reuse count by task, estimated tokens and maximum cost |
| lifecycle | created/submitted/ended/collected/ingested timestamps and request-state counts |

### `scripts/30_plan_api_build.py`

Default and only behavior in this handoff: offline dry run.

Suggested interface:

```text
py -3 scripts/30_plan_api_build.py \
  --split build \
  --promptbook-version v1 \
  --model claude-sonnet-5 \
  --effort medium \
  --reuse-valid \
  --out results/04_classification/api/<run_id>/plan.json
```

It must print and write:

- eligible counts by task;
- accepted/reused counts by source model and effort;
- candidate-but-not-accepted counts;
- missing counts;
- planned route counts (`exclusion`, `combined_analysis`, `power_analysis`,
  `data_analysis`);
- skipped holdout/DROPPED counts;
- per-request and total characters/token estimate;
- max-output allowance;
- best estimate and conservative maximum cost from a versioned pricing input;
- prompt, schema, system prompt, and plan hashes; and
- a prominent `NO API REQUEST WAS MADE` line.

The plan artifact must contain no API key. If it contains full paper text, keep
it in an ignored local directory; prefer a request manifest containing text
hashes and materialize full request JSON only immediately before submission.

### `scripts/31_submit_api_batch.py`

Implement and test with a fake client, but do not invoke live in this handoff.
Safety contract:

- no default submission behavior;
- require `--submit` and `--confirm-plan-sha <full sha256>` together;
- refuse a dirty or changed plan hash;
- refuse if any planned request now has an accepted judgment;
- refuse if model is not exactly the planned model or effort is not `medium`;
- refuse if the predicted upper-bound cost exceeds `--max-cost-usd`;
- refuse if a provider batch ID is already attached to the plan;
- write the provider batch ID atomically before returning success; and
- never print or persist the API key.

### `scripts/32_collect_api_batch.py`

Implement against a fake client. Live use comes later.

- retrieve status without resubmitting;
- poll only when explicitly requested;
- stream JSONL results to a temporary file and atomically rename it;
- match only by `custom_id`, never result order;
- preserve all four provider states: `succeeded`, `errored`, `canceled`, and
  `expired`;
- store message ID, model, stop reason, and every usage counter exactly as
  returned; and
- retry only retryable missing requests in a new batch. Invalid request errors
  require a code/config fix, not blind retry.

Anthropic says batches may take up to 24 hours, results may arrive out of order,
and results are retained for 29 days. Local collection therefore must be
resumable and must save raw results promptly.

### `scripts/33_check_api_results.py`

Read-only report mode by default; `--write` performs an atomic transaction.

- validate request identity and request hash;
- require the expected response transport and stop reason;
- validate structured JSON locally even when the provider constrained it;
- bind wrapper-owned paper ID and task names after parsing;
- run existing task-specific semantic and rule-prefix checks;
- for a combined response, reject the whole response if either half fails;
- persist both combined judgments in one transaction with one response ID;
- make a second `--write` a no-op or explicit refusal, never two new judgments;
- never fabricate an undecidable judgment for a failed request; and
- emit retry manifests rather than making calls itself.

### `src/evaluate.py` and `scripts/22_evaluate.py`

The current evaluator is read-only and already writes a Markdown/CSV/JSON
snapshot. It reports the requested classification metrics, but it cannot yet
establish a G11-comparable history row because legacy `judgments` do not retain
request-level effort, route, response, and run identity. The provenance
migration above must supply those fields before a configuration-stratified
evaluator can enforce G11. Suggested command:

```text
py -3 scripts/22_evaluate.py --split build --promptbook-version v1 --task all
```

Required output per task and configuration stratum:

- eligible labeled papers;
- accepted judgment coverage and missing count;
- yes/no confusion matrix with `yes` as the positive class;
- accuracy, precision, recall/sensitivity, specificity, and F1;
- abstentions and wrong-text responses outside the scored denominator;
- unlabelled count;
- confidence distribution and low-confidence count;
- source route/model/effort counts; and
- a visible warning on any mixed-configuration summary.

The snapshot evaluator must never append history implicitly. A later explicit
history command/flag must refuse mixed-configuration input, missing required
provenance, or an environment mismatch for a DC17 plateau row.

## Reuse planner contract

### Exclusion

For each active build paper eligible for exclusion:

1. accepted reusable exclusion exists -> `REUSE`, no request;
2. only raw/candidate response exists -> `MISSING`, no automatic trust;
3. no accepted response -> plan one exclusion request.

### Analysis

Use the human gate label for build-set promptbook evaluation eligibility. Do not
let a model exclusion error remove a labeled survivor from analysis calibration.
For each eligible human gate survivor:

| Reusable power | Reusable data | Action |
|---|---|---|
| yes | yes | Reuse both; no call |
| yes | no | One data-only legacy call |
| no | yes | One power-only legacy call |
| no | no | One combined call |

For production on the unlabelled corpus, eligibility is different: analysis is
planned only after the accepted production exclusion decision says keep. Do not
reuse the build-set human gate rule there.

If a combined response requires review or retry, keep its halves atomic. The
single-task exception above exists only to avoid repurchasing a valid half that
predates the combined route.

## Prompt and request construction

### Transport choice

Use native JSON structured output on Claude Sonnet 5:

```python
output_config = {
    "effort": "medium",
    "format": {
        "type": "json_schema",
        "schema": schemas.combined_analysis_tool_schema()["input_schema"],
    },
}
```

For a single task, use `schemas.tool_schema(task)["input_schema"]`. This reuses
the already-tested schema while avoiding a client tool declaration and its
tool-use prompt overhead. The wrapper owns the paper/task identity; after
parsing, bind it exactly as the current schema parsers do. Continue local
Pydantic and semantic validation because constrained syntax does not prove that
the scientific decision cited the correct rule.

Do not silently fall back to free-form JSON or forced tool use. A serializer
test must demonstrate that the pinned SDK can encode `output_config.format` in
each Message Batch request before a plan is eligible for submission. If it
cannot, stop offline, correct the version/implementation, rerun the offline
suite, and create a new frozen plan. Add no beta header unless the current
official API requires one.

### Prompt equivalence

The API and Reading Room may differ in response transport, but their scientific
content must match:

- same minimal system prompt bytes;
- same promptbook version and rule text;
- same paper text bytes;
- same paper markers and prompt-injection boundary;
- same rule isolation and ordering;
- same allowed decisions and reasoning cap; and
- same medium effort.

Build API messages as content blocks so the stable first promptbook/scaffolding
prefix can carry identical `cache_control` across requests. Add an offline test
that concatenating the text blocks reproduces the canonical prompt content.
Do not cache or log an answer key with the prompt. Prompt caching in Message
Batches is best effort, so estimated cost must show both zero-cache and expected
cache scenarios rather than assuming a hit.

### Request identity

Use a random or deterministic opaque token in the model-visible paper markers.
Use a separate deterministic opaque `custom_id` no longer than 64 characters
and matching `[A-Za-z0-9_-]+`. It must map locally to exactly one request plan
row but should not contain the real paper ID.

Canonical request hash inputs must include at least:

- paper text SHA-256;
- route and required tasks;
- promptbook and system-prompt hashes;
- schema/template version;
- model, effort, and max tokens; and
- split and pass name.

Changing any input creates a different request hash. Re-running identical code
against identical inputs recreates the same plan hash.

## Persistence and idempotency

The current `judgments` uniqueness key protects one explicit judgment index,
but `scripts/21_check_responses.py --write` can still append the same response
again under a new index. The API path must close that gap.

Required invariants:

1. one provider message ID maps to one local response;
2. one accepted response/task pair maps to at most one judgment row;
3. a combined response writes zero or two judgment rows in one transaction;
4. a crash after raw-result save but before DB commit is safely resumable;
5. a crash after DB commit is detected as already ingested;
6. a retry preserves the earlier failed response and links to it;
7. provider results never overwrite local raw evidence; and
8. reuse selection is made from accepted rows, never filesystem presence.

## Cost and token controls

Implement these optimizations in order:

1. **Reuse accepted judgments.** This is a 100% saving for those paper/task
   pairs and has already been chosen by the user.
2. **Use the missing-half matrix.** Do not buy a combined response when one
   valid half already exists.
3. **Combine power and data when both are missing.** Full paper text is sent
   once instead of twice.
4. **Use Message Batches.** Keep synchronous Messages calls to a separately
   approved one-request transport preflight only.
5. **Pin medium effort explicitly.** The API default is high; omission is a
   budget bug and a comparability bug.
6. **Enable stable-prefix prompt caching.** Treat hits as best effort and record
   cache read/creation usage rather than assuming savings.
7. **Set a measured output ceiling.** Start conservatively enough to avoid
   truncating adaptive reasoning, then lower only after the approved smoke test
   shows the observed maximum with headroom.
8. **Retry narrowly.** Resubmit only retryable errored/expired requests and only
   if the task is still missing at retry-plan time.
9. **Do not run Opus review indiscriminately.** The threshold is tuned on build;
   only the selected low-confidence cases enter review.
10. **Version pricing inputs.** Do not hardcode prose prices from `Costs.md` in
    code. Record provider, effective date, input/output/cache/batch rates, and
    print the price-source version in every estimate.

Do not optimize by truncating papers, reducing the build denominator, changing
models, lowering effort below medium, merging exclusion with analysis, or
silently increasing abstention. Those change the experiment rather than merely
its cost.

The current `Costs.md` analysis-call estimate is stale because it assumes two
post-gate calls per survivor and no reuse. Refresh it only after the offline plan
reports actual route counts and after a separately approved two-paper smoke test
provides measured usage.

## Offline test cases

Use fake clients and temporary SQLite databases. Tests must not require an API
key or network access.

### A. Eligibility and reuse

1. Persisted accepted exclusion -> no exclusion request.
2. Exit-0 raw exclusion without validation -> request remains missing.
3. Checked report without persistence -> request remains missing.
4. Existing power and data -> no analysis request.
5. Existing data only -> power-only request.
6. Existing power only -> data-only request.
7. Neither half -> exactly one combined request.
8. Human-excluded build paper -> no analysis request.
9. Holdout paper in a build plan -> hard refusal.
10. Manifest `DROPPED` paper -> skipped with reason, not replaced.
11. Duplicate accepted rows -> deterministic latest/reuse rule and visible
    provenance, never two planned states.
12. Existing high-effort judgment reused -> accepted under reuse policy but
    flagged mixed-config in the plan.

### B. Prompt and schema

13. Paper text appears exactly once in every prompt.
14. Combined prompt contains isolated P and D blocks in fixed order.
15. Exclusion prompt contains neither analysis promptbook.
16. Power-only request contains no data promptbook; converse for data-only.
17. Concatenated API text blocks equal canonical prompt text.
18. Combined output schema requires both halves and forbids extras.
19. Single-task schema excludes wrapper-owned task/paper metadata.
20. Every request carries `output_config.effort == "medium"` and native
    `output_config.format` explicitly; no request contains a result tool or
    `tool_choice`.
21. Unknown route/task refuses before request materialization.

### C. Determinism and paid-call guards

22. Same inputs -> byte-identical request JSON and plan hash.
23. Paper/prompt/config change -> request and plan hash change.
24. All custom IDs are unique, opaque, <=64 characters, and regex-valid.
25. Dry run constructs no Anthropic client and reads no API key.
26. Submit without `--submit` refuses.
27. Submit without the exact full plan SHA refuses.
28. Submit above the approved max cost refuses.
29. Submit after a newly accepted judgment changes the anti-join refuses.
30. Existing provider batch ID prevents a second create call.
31. Fake-client submit receives exactly the frozen request objects.

### D. Result collection

32. Out-of-order results map correctly by custom ID.
33. Unknown or duplicate custom ID is a hard failure.
34. `succeeded`, `errored`, `canceled`, and `expired` remain distinct.
35. Invalid-request errors are not marked automatically retryable.
36. Server error/expired requests produce a narrow retry plan.
37. Partial collection resumes without duplicating saved result lines.
38. Raw result is durable before validation begins.
39. Usage fields absent from the provider remain null, never zero.

### E. Validation and atomic persistence

40. Valid exclusion response creates one task-bound judgment.
41. Valid combined response creates two rows sharing one response ID.
42. Missing or malformed combined half creates zero judgment rows and leaves a
    terminal retry/review-required record, never a fabricated `undecidable`.
43. Wrong-text in either analysis half creates zero rows.
44. P rule cited by data or D rule cited by power rejects the response.
45. Cross-task conclusion reference rejects the response; test both directions.
46. Max-token stop reason is truncation, not parse failure.
47. Second ingestion of the same response is a no-op/refusal with row count
    unchanged.
48. Crash between first and second combined insert rolls back both.
49. Existing 49 legacy exclusion rows survive migration byte-for-byte in their
    scientific fields.

### F. Evaluation

50. Accuracy denominator excludes undecidable and wrong-text but reports both.
51. Missing judgments reduce coverage, not accuracy denominator silently.
52. Confusion matrix uses model `yes` as the positive prediction.
53. Power/data evaluation includes only human gate survivors on build.
54. Mixed high/medium summary prints a warning and cannot append a plateau row.
55. Homogeneous medium stratum can be reported independently.
56. Running evaluation twice is read-only and byte-identical.

### G. Cost accounting

57. Reused judgments contribute zero planned input/output tokens.
58. Missing-half call is counted once with one promptbook.
59. Combined call is counted once with both promptbooks and one paper body.
60. Cost report shows zero-cache and cache-hit scenarios.
61. Provider usage reconciliation sums input, cache creation, cache read, and
    output fields without inventing missing values.
62. Actual cost never silently replaces a configured rate-version mismatch;
    the report names the mismatch.

## Offline acceptance sequence

The implementing agent should finish with this sequence, adapted to the final
filenames:

```text
py -3 -m pytest ReadingRoom/tests -q
py -3 -m pytest ReadingRoom/tests/test_j_evaluate.py -q
py -3 scripts/30_plan_api_build.py --split build --promptbook-version v1 --model claude-sonnet-5 --effort medium --reuse-valid
py -3 scripts/30_plan_api_build.py --split build --promptbook-version v1 --model claude-sonnet-5 --effort medium --reuse-valid --verify-deterministic
```

Then report:

- tests passed;
- current accepted/candidate/missing counts;
- exact request counts by route;
- number of calls and paper/task judgments saved by reuse;
- estimated tokens and cost range;
- plan path and full SHA-256;
- any mixed-configuration warning; and
- confirmation that no API request was made.

Stop there. Do not run a synchronous preflight and do not submit the batch.

## Later live sequence (reference only; not authorized by this handoff)

After separate user approval:

1. one synchronous request using the exact frozen request shape;
2. validate it end to end and compare measured usage to the estimate;
3. a two-paper Message Batch smoke test;
4. validate and ingest the smoke results;
5. refresh the plan and cost ceiling;
6. obtain approval for the full build batch;
7. submit, collect, validate, persist, and evaluate; and
8. only then consider thresholded review calls.

## Official API references checked 2026-08-28

- [Message Batch creation](https://platform.claude.com/docs/en/api/http/messages/batches/create)
- [Batch processing lifecycle, results, caching, and limits](https://platform.claude.com/docs/en/build-with-claude/batch-processing)
- [Structured JSON outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Anthropic Python SDK](https://platform.claude.com/docs/en/api/sdks/python) and the pinned [1.0.0 release](https://pypi.org/project/anthropic/1.0.0/)
- [Effort configuration](https://platform.claude.com/docs/en/build-with-claude/effort)

Relevant current constraints to re-check immediately before implementation and
again before live use: maximum 100,000 requests per batch; `custom_id` length and
character rules; 256 MB request size; up to 24-hour processing; out-of-order
JSONL results; 29-day result retention; best-effort batch cache hits; and
request-level `output_config.effort`.
