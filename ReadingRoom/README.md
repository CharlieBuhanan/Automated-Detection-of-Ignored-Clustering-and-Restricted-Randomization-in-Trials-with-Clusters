# The Reading Room

A sealed room where a reviewer is handed exactly one paper, may not bring
anything else in, and hands back exactly one filled-in form.

**Status: built, green, and ready for a scored round (2026-08-27).**
397 offline tests cover 88 of the 89 cases in [TEST_PLAN.md](tests/TEST_PLAN.md).
The exception is A12, the live canary, **decided against** — see *Verified two
ways, not three*.

Full rationale in [PLAN.md](../research%20design/PLAN.md)'s *The Reading Room*;
this file is the build spec.

---

## Run it

```bash
# 0. Prepare the text. Offline, free, idempotent. Do this before any round.
python scripts/19_strip_references.py

# 1. Plan only. Costs nothing, spawns nothing, checks every wall.
python scripts/20_reading_room.py --task exclusion --round 1 --dry-run

# 2. One throwaway probe. Re-checks every LIVE wall after any config change.
python scripts/20_reading_room.py --task exclusion --round 1 --preflight-only

# 3. Two papers, to prove the walls hold before spending a round.
python scripts/20_reading_room.py --task exclusion --round 1 --limit 2
python scripts/21_check_responses.py --task exclusion --round 1

# 4. The real round.
python scripts/20_reading_room.py --task exclusion --round 1 --force
python scripts/21_check_responses.py --task exclusion --round 1 --write
```

`--task` is `exclusion | power_analysis | data_analysis | combined_analysis`.
Every flag is in each script's `--help`. **Nothing reaches `data/review.db`
without `--write`.**

**Rounds run one paper at a time.** `--parallel` restores the old six-way pool,
and you almost never want it: the pool commits six papers of the 5-hour window
before the first result is readable, and a round that has gone wrong cannot then
be stopped (DC58). Serially, a sealing breach ends the round on the paper it
happened on, and the per-paper line carries a running billed-token total.

## Evaluate persisted judgments

The evaluator is read-only: it neither calls a model nor changes SQLite. It
writes a Markdown dashboard plus CSV and JSON artifacts containing coverage,
the confusion matrix, accuracy, sensitivity, specificity, precision, F1, and
Cohen's kappa.

```bash
py -3 scripts/22_evaluate.py --task all --split build --promptbook-version v1
```

Use `--no-write` to display the same table without creating artifacts. Open
`summary.csv` or `cases.csv` in Excel/R for plotting and paper-level review.

Needs the CLI on `PATH` (`npm install -g @anthropic-ai/claude-code`), or pass
`--claude` with a full path. If it is missing the harness refuses before touching
a single paper.

The offline suite is free and spawns no model:

```bash
python -m pytest ReadingRoom/tests/ -q
```

---

## Why this is not just "call the CLI in a loop"

`claude -p` is **agentic, not a completion endpoint**. Run inside this repo it
has file tools, and `data/ground_truth.csv`, `data/review.db` and an auto-loaded
`CLAUDE.md` naming both are sitting right there.

**Telling it not to look is not a control. Removing the ability to look is.**

If the model reads the answers, accuracy goes up and nothing in the output says
so. That is the failure this directory exists to prevent.

## The five walls

| Wall | How | What it stops |
|---|---|---|
| **Empty room** | `cwd` = a fresh scratch dir **per paper**, outside the repo. Never `--add-dir`. A per-paper `CLAUDE_CONFIG_DIR` holding only the credentials | No CLAUDE.md, no memory, no relative path to the answers, no previous paper's transcript |
| **No hands** | `--tools ""`, plus `permissions.deny`, plus `--max-turns 1`, plus an assertion that the CLI **reported** zero tools | Makes it a pure text completion. `--tools ""` is the availability filter and the mechanism; `--allowed-tools ""` is only a permission allowlist and removes nothing |
| **No persona** | `--system-prompt` carrying one pinned minimal prompt, sha256'd into the run log | The model is a reader, not Claude Code the coding agent. **This is the wall that makes the Reading Room and the Batch API the same experiment** |
| **Paper by hand** | Text on **stdin**, never a path. Output captured from stdout | One paper's response is not readable by the next |
| **No name** | Send a random token; the wrapper keeps token → `paper_id` | A leak is not lookup-able even if one happens |

**The wrapper writes the JSON, not Claude.** That deletes the whole "did it
corrupt the output file" failure class, and the model has no write target to be
confused about.

## Two scripts

### `20_reading_room.py` — run one round

Reads `promptbooks/CURRENT`, resolves the round from `build_rounds.csv`, and
refuses if any paper is in the holdout (DC18), lacks cached text, or has left the
corpus. Then it spawns one sealed process per paper, **one at a time by
default**, and saves each response **verbatim before parsing** — if parsing is
what mangles it, you need the original to prove that.

It reads `data/extracted_text_stripped/`, the references-stripped copy written by
`scripts/19_strip_references.py` (DC56) — 21.6% smaller than the extraction cache
and decided by no criterion. A round whose papers were prepared two different
ways is refused before anything spawns.

**One paper per process, never batched:** ten papers in one context lets the
model make exactly the cross-paper judgments E12 and E17 forbid, and position
effects inside the batch contaminate the accuracy number. Running them serially
costs wall-clock and buys the ability to stop.

Before any paper, one throwaway two-word probe (`preflight`) checks every wall
that only a real process can test: that the room can log in, that zero tools were
offered, and that the system prompt actually took effect. Every failure it
catches breaks *every* paper identically, so finding one on paper 1 of 50 wastes
49 papers of quota and finding it on the probe wastes nothing.

Outputs, per round, into `results/04_classification/raw/<task>_r<round>/`:

| File | What it is |
|---|---|
| `<token>.attemptN.jsonl` | the verbatim stream-json — the evidence |
| `index.csv` | token → `paper_id`, **the only deblinding key.** Do not delete it |
| `run_log.csv` | one row per paper: text notes, timing, tokens, cost, exit |
| `run_environment.json` | the round's invariants (see *Reproducibility*) |

### `21_check_responses.py` — validate before anything is scored

Ordered, and the order matters — each step assumes the previous one passed.

```
0. run_environment.json exists, and the promptbook has not changed since  (G1)
FOR each raw response:
  1. exit code == 0                        else -> retry ledger
  2. ZERO tool_use blocks in the stream     else -> DISCARD THE WHOLE ROUND
  3. provenance: right model, right CLI, no permission denials, standard
     serving path, a result event, a request_id, not truncated        (group G)
  4. JSON parses (note if a ``` fence had to be stripped)
  5. pydantic Decision validates      (src/schemas.py — same model as the API)
  6. decision in allowed set; wrong_text ONLY on exclusion
  7. reasoning <= 200 chars
  8. promptbook_evidence cites a rule that EXISTS in the promptbook in force
  9. confidence in [0,1] AND not identical across every paper
 10. the blinded token echoes back unchanged
 11. resolve token -> paper_id, write the judgment

  any failure -> retry ledger (paper_id, attempt, failure kind)
```

**Step 2 is not a per-paper failure — it fails the round.** One tool call means
the walls had a hole; every other paper ran under the same conditions and none of
them can be trusted either. Same for a wrong model, a permission denial, a
non-standard serving path, or a CLI that auto-updated mid-round.

**Step 9's "not constant" check** catches a model that has stopped reading and is
emitting a template. Constant confidence across 50 papers is not a confidence
score.

---

## Reproducibility

**The CLI exposes neither temperature nor seed, so identical bytes are not
achievable.** Claiming otherwise in the write-up would be false. What *is*
achievable is a reproducible **procedure**, recorded completely enough that
someone else could set the same conditions. Never pass `--resume`, `--continue`,
or a reused `--session-id`.

### The conditions, pinned

| | | Why this value |
|---|---|---|
| Model | `claude-sonnet-5` | Pinned to the model the **batch** run uses. A promptbook refined against one model and shipped against another is tuned on nothing |
| Effort | `medium` | `--effort` here, `output_config.effort` on the Batch API — the same level on both sides, for the same reason |
| Thinking | adaptive | The only on-mode on Sonnet 5. Not settable from the CLI, and `budget_tokens` is removed on this model |
| System prompt | pinned minimal, hashed | `prompts/system_prompt.txt`. **One line** — see live finding 7 |
| Tools | none, asserted | `--tools ""` + `permissions.deny` + `init.tools == []` |
| Turns | 1 | `--max-turns 1` |

### Recorded, in two layers

`run_environment.json` per round holds the invariants: model, effort, thinking
mode, `claude_code_version`, the verbatim argv, sha256 of the system prompt /
settings / promptbook, `promptbook_version`, git commit (`-dirty` if it is),
observed tool list, host, OS, python version, start and finish times.

The `run_log.csv` row per paper holds what varies: `request_id`, `session_id`,
durations, `stop_reason`, `terminal_reason`, full token counts,
`total_cost_usd`, `service_tier`, `inference_geo`, `context_window`, `attempt`,
`exit_code`.

**A field the CLI did not send is written as an empty cell, never as a zero.** A
fabricated `0` for `total_cost_usd` is indistinguishable from a free call, and
the round's cost would silently be a lie. Full field list and the failure mode
for each is group **G** in [TEST_PLAN.md](tests/TEST_PLAN.md).

### What is not obtainable, and must not be claimed

| Wanted | Reality |
|---|---|
| A dated model snapshot | **There isn't one.** `claude-sonnet-5` *is* the complete ID; `system/init`, `message.model` and `modelUsage` all return the bare alias, and the API rejects a date suffix. Say "`claude-sonnet-5`, CLI 2.1.197" |
| Effort echoed back | No stream event reports it. We log what we **passed**; G11 catches a change between rounds |
| Temperature, seed, top_p | Not exposed by the CLI |
| A thinking on/off switch | No flag. Adaptive is the only mode on this model |

---

## What the live runs found

Three probes against the real CLI 2.1.197, all on 2026-08-27, after the offline
suite was green each time. **Every one of these was a wrong belief about what a
flag means, not a coding mistake** — which is the argument for never trusting a
harness that has only been tested against a fake.

| # | What broke | Why no offline test caught it |
|---|---|---|
| 1 | `"MultiEdit"` in the deny list — no such tool in 2.1.197, and the CLI **refuses to start**, every paper exiting non-zero | The name is only validated by the real CLI |
| 2 | **`--allowed-tools ""` does not empty the room.** It is a *permission* allowlist, not an availability filter. 18 tools were still offered — including `TaskCreate`, which spawns a subagent with its own full file toolset, one turn from `data/ground_truth.csv` | The design rested on a wrong belief about a flag. Only `system/init.tools` shows the truth |
| 3 | **The room could not log in.** A7 points `CLAUDE_CONFIG_DIR` at an empty dir — which is also where the CLI keeps `.credentials.json` | The fake CLI does not authenticate |
| 4 | The CLI writes session transcripts into `CLAUDE_CONFIG_DIR`, so after paper 1 that dir contained `projects/` and A7 refused every later paper | Needs a real process that writes as a side effect |
| 5 | A `wrong_text` answer was rejected for citing no rule id — but the promptbook **itself** specifies `WRONG_TEXT` as the evidence there. The model was right and the checker was wrong | Needs a real model reading the real promptbook |
| 6 | **Every call was carrying ~12,200 tokens of Claude Code's agentic system prompt** — coding persona, tool instructions, cwd/git/env/memory sections. Visible as `cache_creation 9140` + `cache_read 3058` on a two-word prompt. The room was sealed against **files** and wide open to a **persona**, and the promptbook was being tuned against a coding agent then shipped to a bare Batch API classifier | Nothing in the harness looked at token counts |
| 7 | **A newline in `--system-prompt` silently removes walls.** On Windows `claude` is a `.cmd` shim and cmd.exe's `%*` ends the command line at the first newline: a three-paragraph prompt arrived as its opening sentence, and `--strict-mcp-config` and `--settings` never arrived at all. Exit code 0, tools still empty, nothing in any log | `verify_argv` inspects the argv we *built*, not the one the child received. Caught only because `fake_claude.py` is a **real shim on `PATH`**, not a monkeypatched `subprocess.run` |

**What changed as a result.** `--tools ""` is the mechanism and `permissions.deny`
the second layer; neither is trusted alone, because `assert_no_tools_offered()`
checks the list the CLI *reports*, so a tool added in a future version is caught
by something nobody has to remember to update. `carry_auth()` copies exactly one
file — the credentials — into the room, and every paper gets its own
`CLAUDE_CONFIG_DIR` as well as its own cwd. `--system-prompt` replaces the
persona (verified: the same two-word probe went **12,198 → 183 input tokens**,
tools still `[]`), the pinned prompt is one line and `load_system_prompt()`
refuses a newline, and `--system-prompt` is now the **last** argument so nothing
load-bearing sits downstream of the only free-text value. `preflight()` spawns
one throwaway call before every round, because findings 1-4, 6 and 7 all break
every paper identically.

## Verified two ways, not three

1. **`stream-json` assertion** — zero `tool_use` and zero `tool_result` blocks
   per paper, plus zero tools *offered*; any round with one is discarded whole.
   Asserted in both scripts.
2. **The holdout**, run once through the Batch API, which does not depend on
   trusting this loop at all.

**The canary was cut (2026-08-27).** The plan was ~20 papers against a decoy
`ground_truth.csv` with flipped labels and tools deliberately **on**; if accuracy
tracked the decoy, the model was reading rather than reasoning. It was the only
test that would have proven the walls matter rather than assuming it, and
dropping it is a real reduction in assurance — recorded here rather than quietly
omitted. What stands in for it: the walls are `--tools ""` and `--max-turns 1`,
so a tool call is not merely discouraged but absent from the CLI's surface, and
the stream is asserted on anyway. `canary_verdict()` is kept and tested, so
running it later costs a script and not a redesign.

## Files

```
ReadingRoom/
  README.md              this file — design, how to run it
  prompts/
    system_prompt.txt    the pinned minimal system prompt, sha256'd into every
                         run_environment.json. ONE LINE (live finding 7).
                         Changing it is a promptbook version bump, not an edit
  tests/
    TEST_PLAN.md         132 cases: input -> expected handling
    conftest.py          fixtures; puts the fake CLI on PATH
    fake_claude.py       a fake `claude` that replays the real 2.1.197 stream
    test_a_isolation.py  A1-A17   the walls
    test_b_rounds.py     B1-B10   round and split selection
    test_c_paper_text.py C1-C12   messy extraction output, injection, encoding
    test_d_parsing.py    D1-D14   the src/schemas.py contract
    test_e_semantic.py   E1-E12   valid but wrong
    test_f_retries.py    F1-F12   retries, concurrency, the ledger
    test_g_provenance.py G1-G12   the run record
    test_h_combined_schema.py     test_i_combined_route.py      test_j_evaluate.py            test_k_api_contract.py    H1-H6    the post-gate route and the API boundary
    test_l_runner.py     I1-I19   serial by default, and serial actually stops
    test_m_reference_strip.py                          J1-J16   21.6% off the input without cutting a method
```

The file letter is a sequence number and the case letter is the group; they
stopped lining up at H, which is asserted across four files.

The runnable scripts are `scripts/20_reading_room.py` and
`scripts/21_check_responses.py`; the logic they call lives in
`src/reading_room.py` so it can be imported and tested (`import 20_reading_room`
is not valid Python). This directory is the spec and the suite, and the repo's
script numbering stays unbroken.
