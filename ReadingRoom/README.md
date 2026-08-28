# The Reading Room

**Status: built and green, but one revision behind the spec (2026-08-27).**
302 offline tests pass, covering 71 of the original 72 cases. The exception is
A12, the live canary, **decided against** — see *Verified two ways, not three*.

**A second live probe has since added 17 cases that are specified and not yet
built** — A13-A17 and the whole of group G. Two of them close real holes: the
room was using the wrong flag to remove tools, and every call was silently
carrying Claude Code's own agentic system prompt. See *What the second probe
found* below. **Do not run a scored round until those are green.**

A sealed room where a reviewer is handed exactly one paper, may not bring
anything else in, and hands back exactly one filled-in form. Full rationale in
[PLAN.md](../research%20design/PLAN.md)'s *The Reading Room*; this file is the
build spec.

---

## Run it

```bash
# 1. See what would run. Costs nothing, spawns nothing, checks every wall.
python scripts/20_reading_room.py --task exclusion --round 1 --dry-run

# 2. Two papers first, to prove the walls hold before spending a round.
python scripts/20_reading_room.py --task exclusion --round 1 --limit 2
python scripts/21_check_responses.py --task exclusion --round 1

# 3. The real round.
python scripts/20_reading_room.py --task exclusion --round 1 --force
python scripts/21_check_responses.py --task exclusion --round 1 --write
```

`--task` is `exclusion | power_analysis | data_analysis`. Every flag is
documented in each script's module docstring — `python scripts/20_reading_room.py
--help` also works. **Nothing reaches `data/review.db` without `--write`.**

Needs the CLI on `PATH` (`npm install -g @anthropic-ai/claude-code`), or pass
`--claude` with a full path. If it is missing, the harness refuses before it
touches a single paper rather than failing halfway through a round.

Run the offline suite any time — it is free and spawns no model:

```bash
python -m pytest ReadingRoom/tests/ -q
```

---

## Why this is not just "call the CLI in a loop"

`claude -p` is **agentic, not a completion endpoint**. Run inside this repo it
has file tools, and `data/ground_truth.csv`, `data/review.db`, and an
auto-loaded `CLAUDE.md` naming both are sitting right there.

**Telling it not to look is not a control. Removing the ability to look is.**

If the model reads the answers, accuracy goes up and nothing in the output says
so. That is the failure this whole directory exists to prevent.

## The five walls

| Wall | How | What it stops |
|---|---|---|
| **Empty room** | `cwd` = a fresh scratch dir **per paper**, outside the repo. Never `--add-dir`. A per-paper `CLAUDE_CONFIG_DIR` too, holding only the credentials | No CLAUDE.md, no memory, no relative path to the answers resolves, no previous paper's session transcript |
| **No hands** | `--tools ""`, plus `permissions.deny`, plus `--max-turns 1`, plus an assertion that the CLI **reported** zero tools | Makes it a pure text completion — it cannot read a file even if it decides to. `--tools ""` is the availability filter and the mechanism; `--allowed-tools ""` is only a permission allowlist and removes nothing |
| **No persona** | `--system-prompt` pointing at one pinned minimal prompt, sha256'd into the run log | The model is a reader, not Claude Code the coding agent. **This is the wall that makes the Reading Room and the Batch API the same experiment** |
| **Paper by hand** | Text on **stdin**, never a path. Output captured from stdout. | One paper's response is not readable by the next |
| **No name** | Send a random token; wrapper keeps token → `paper_id` | A leak is not lookup-able even if one happens |

The **wrapper writes the JSON, not Claude.** That deletes the entire "did it
corrupt the output file" failure class, and the model has no write target to be
confused about.

---

## Two scripts

### `20_reading_room.py` — run one round

```
INPUT   task (exclusion | power_analysis | data_analysis), round number
OUTPUT  one raw response file per paper + a run-log row

  promptbook = read(promptbooks/CURRENT)          # e.g. "v1"
  papers     = build_rounds.csv WHERE task=task AND round=round
  assert every paper is in the BUILD split        # holdout is untouchable (DC18)

  make a fresh scratch dir OUTSIDE the repo
  write a settings.json with no MCP servers, no tools
  point CLAUDE_CONFIG_DIR at an empty dir         # no user CLAUDE.md loads

  run 5-8 papers CONCURRENTLY, but ONE PAPER PER PROCESS:
      token    = random_hex()                     # the paper's blinded name
      remember token -> paper_id                  # only the wrapper knows this
      prompt   = promptbook + "Paper token: {token}" + paper_text
                                                  # instructions repeated AFTER
                                                  # the text (DC26)
      result   = spawn claude -p
                   --max-turns 1
                   --tools ""                     # THE no-hands mechanism
                   --allowed-tools ""             # second layer, not the mechanism
                   --output-format stream-json    # so we can SEE tool attempts
                   --verbose                      # required by stream-json under -p
                   --model claude-sonnet-5
                   --effort high                  # pinned; matches the batch run
                   --system-prompt <pinned minimal, NOT the CLI default>
                   --strict-mcp-config
                   --settings <the file above>
                 with cwd=scratch, stdin=prompt
      save result VERBATIM, before parsing        # raw bytes are the evidence
      assert init.tools == []                     # observed, not assumed
      record request_id, durations, usage, cost   # provenance, group G
```

**Why one paper per process, never batched:** ten papers in one context lets the
model make exactly the cross-paper judgments E12 and E17 forbid, and position
effects inside the batch contaminate the accuracy number. Concurrency buys the
same wall-clock with none of the contamination.

**Why the raw response is saved before parsing:** if parsing is what mangles it,
you need the original to prove that. It is also what DC24's retry rate is
computed from.

### `21_check_responses.py` — validate before anything is scored

Ordered, and the order matters — each step assumes the previous one passed.

```
FOR each raw response:
  1. exit code == 0                     else -> retry ledger
  2. ZERO tool_use blocks in the stream  else -> DISCARD THE WHOLE ROUND
  3. JSON parses (note if a ``` fence had to be stripped)
  4. pydantic Decision validates         (src/schemas.py — same model as the API route)
  5. decision in allowed set; wrong_text ONLY on exclusion
  6. reasoning <= 200 chars
  7. promptbook_evidence cites a rule that EXISTS in the promptbook in force
  8. confidence in [0,1] AND not identical across every paper
  9. the blinded token echoes back unchanged
 10. resolve token -> paper_id, write the judgment

  any failure -> retry ledger (paper_id, attempt, failure kind)
```

**Step 2 is not a per-paper failure — it fails the round.** One tool call means
the walls had a hole; every other paper in that round ran under the same
conditions and none of them can be trusted either.

**Step 8's "not constant" check** catches a model that has stopped reading and
is emitting a template. Constant confidence across 50 papers is not a
confidence score.

---

## What "reproducible" means here

**The CLI exposes neither temperature nor seed, so identical bytes are not
achievable.** Claiming otherwise in the write-up would be false.

What *is* achievable is a reproducible **procedure**, recorded completely enough
that someone else could set the same conditions. Never pass `--resume`,
`--continue`, or a reused `--session-id` — every invocation is a fresh process
with no shared history.

### The conditions, pinned

| | | Why this value |
|---|---|---|
| Model | `claude-sonnet-5` | Pinned to the model the **batch** run uses (`Costs.md`). A promptbook refined against one model and shipped against another is tuned on nothing |
| Effort | `high` | `--effort` on the CLI, `output_config.effort` on the Batch API — **the same level on both sides**, for the same reason. `high` is the API default and the recommended floor for judgment-sensitive work |
| Thinking | adaptive | The only on-mode on Sonnet 5. Not separately settable from the CLI, and `budget_tokens` is removed on this model, so `--effort` is the only lever |
| System prompt | pinned minimal, hashed | Not the CLI default — see the second probe below |
| Tools | none, asserted | `--tools ""` + `permissions.deny` + `init.tools == []` |
| Turns | 1 | `--max-turns 1` |

### Recorded, in two layers

Per round, `run_environment.json` — the invariants: model, effort, thinking mode,
`claude_code_version`, the verbatim argv, sha256 of the system prompt / settings
file / promptbook, `promptbook_version`, git commit (`-dirty` if it is),
`tools_offered` as the CLI reported it, host, OS, python version, start and
finish times.

Per paper, a run-log row — what varies: `request_id`, `session_id`,
`duration_ms`, `duration_api_ms`, `ttft_ms`, `num_turns`, `stop_reason`,
`terminal_reason`, input / output / cache token counts, `total_cost_usd`,
`service_tier`, `inference_geo`, `context_window`, `max_output_tokens`,
`attempt`, `exit_code` — alongside the verbatim raw response.

The full field list and the failure mode for each missing field is group **G** in
[TEST_PLAN.md](tests/TEST_PLAN.md).

### What is not obtainable, and must not be claimed

| Wanted | Reality |
|---|---|
| A dated model snapshot | **There isn't one.** `claude-sonnet-5` *is* the complete ID. `system/init`, `message.model` and `modelUsage` all return the bare alias, and the API rejects a date suffix. The write-up should say "`claude-sonnet-5`, CLI 2.1.197", not imply a pinned snapshot exists |
| Effort echoed back | No stream event reports it. We log what we **passed**; G11 catches a change between rounds |
| Temperature, seed, top_p | Not exposed by the CLI |
| A thinking on/off switch | No flag. Adaptive is the only mode on this model |

## What the first live run found (2026-08-27)

Three papers against the real CLI, after 299 offline tests were green. It found
**five defects the offline suite could not**, two of which meant the room was
not sealed. This is the argument for never trusting a harness that has only
been tested against a fake.

| # | What broke | Why no offline test caught it |
|---|---|---|
| 1 | `"MultiEdit"` in the deny list — CLI 2.1.197 has no such tool and **refuses to start**, every paper exiting non-zero | The name is only validated by the real CLI |
| 2 | **`--allowed-tools ""` does not empty the room.** It is a *permission* allowlist, not an availability filter. 18 tools were still offered — including `TaskCreate`, which spawns a subagent with its own full file toolset, one turn from `data/ground_truth.csv` | The whole design rested on a wrong belief about a flag's meaning. Only the `system/init` event's `tools` array shows the truth |
| 3 | **The room could not log in.** A7 points `CLAUDE_CONFIG_DIR` at an empty directory — which is also where the CLI keeps `.credentials.json`. Every paper returned `Not logged in · Please run /login` | The fake CLI does not authenticate |
| 4 | The CLI writes session transcripts into `CLAUDE_CONFIG_DIR`, so after paper 1 the config dir contained `projects/` and A7 refused every subsequent paper | Needs a real process that writes as a side effect |
| 5 | A `wrong_text` answer was rejected by the E6 check for citing no rule id — but the v1 promptbook **itself** specifies `WRONG_TEXT` as the evidence value there. The model was right and the checker was wrong | Needs a real model reading the real promptbook |

**What changed as a result.** `DENIED_TOOLS` is now the mechanism rather than the
belt-and-braces, and it is no longer trusted on its own: `assert_no_tools_offered()`
checks the tool list the CLI *reports*, so a tool added in a future version is
caught by something nobody has to remember to update. `carry_auth()` copies
exactly one file — the credentials, nothing else — into the room. Every paper
gets its **own** `CLAUDE_CONFIG_DIR` as well as its own cwd, so one paper's
transcript cannot outlive it. And `preflight()` spawns one throwaway two-word
call before the round, because defects 1-4 all break every paper identically:
finding them on paper 1 of 50 wastes 49 papers of quota, finding them on a probe
wastes nothing.

## What the second probe found (2026-08-27)

One throwaway call against CLI 2.1.197, run to answer a narrow question — *what
metadata can we actually log?* — which turned up two design errors and a large
amount of free provenance.

| # | What it found | Consequence |
|---|---|---|
| 1 | **`--tools ""` exists and genuinely empties the room.** `system/init` returned `"tools":[]`. The README previously said no such flag existed and that `permissions.deny` was the only mechanism | `--tools ""` becomes the mechanism (A13); the deny list drops to a second layer. Removes the class of bug where a renamed tool (`MultiEdit`) stops the CLI from starting and breaks every paper |
| 2 | **Every call was carrying ~12,200 tokens of Claude Code's default agentic system prompt** — coding-assistant persona, tool instructions, cwd / git / env / memory-path sections. Visible as `cache_creation_input_tokens: 9140` + `cache_read_input_tokens: 3058` on a two-word prompt | **The room was sealed against files and wide open to a persona.** The promptbook was being tuned against a coding agent and shipped to a bare Batch API classifier. Fixed by `--system-prompt` (A15), guarded by a token ceiling on the preflight probe (A17) |
| 2a | **`--system-prompt` verified to *replace*, not append.** The same two-word probe went from **12,198 → 183 input tokens**, with `tools` still `[]` | A15 is real, not hopeful. **A17's ceiling is a measurement**: the preflight probe must come in near 183 and nowhere near 12,198. It also removes ~12,000 tokens of billed overhead per paper — roughly \$2-3 per 50-paper round, incidental to the point but not nothing |
| 3 | `claude_code_version` is in `system/init`; `request_id` is on the assistant event; `duration_ms`, `duration_api_ms`, `ttft_ms`, `stop_reason`, `terminal_reason`, full token usage, `total_cost_usd`, `service_tier`, `inference_geo`, `context_window`, `speed`, `fast_mode_state` and `permission_denials` are all on the `result` event | All of it is now logged — group **G**. None of it was before |
| 4 | **No dated model snapshot is exposed anywhere.** `system/init.model`, `message.model` and the `modelUsage` key are all the bare alias `claude-sonnet-5` | Not a gap to fix — the alias *is* the complete ID. The write-up says so rather than implying a snapshot |
| 5 | `--effort` exists (`low`/`medium`/`high`/`xhigh`/`max`) and is accepted, but **is not echoed back in any event** | We can pin it; we cannot verify it from the stream. Logged as intent, and G11 refuses to compare two rounds whose pinned effort differs |
| 6 | The CLI read `.claude/settings.json` from cwd and warned about 34 permission entries | Harmless in the real room (cwd is an empty scratch dir) but proves cwd settings *are* read. A8 now refuses a `.claude/` directory in the scratch cwd, not just a `CLAUDE.md` |

**The pattern, twice now:** both live probes found defects that 300 green offline
tests could not, and both times the defect was a *wrong belief about what a flag
means* rather than a coding mistake. The offline suite tests the harness against
the CLI we imagine. Only a real call tests it against the CLI that exists.

## Verified two ways, not three

1. **`stream-json` assertion** — zero `tool_use` and zero `tool_result` blocks
   per paper; any round with one is discarded whole. Asserted on every response
   in `20_reading_room.py` and again in `21_check_responses.py`.
2. **The holdout**, run once through the Batch API, which does not depend on
   trusting this loop at all.

**The canary was cut (2026-08-27).** The plan was ~20 papers against a decoy
`ground_truth.csv` with flipped labels and tools deliberately **on**; if accuracy
tracked the decoy, the model was reading rather than reasoning. It was the only
test that would have proven the walls matter rather than assuming it, and
dropping it is a real reduction in assurance — recorded here rather than quietly
omitted. What stands in for it: the walls are `--allowed-tools ""` and
`--max-turns 1`, so a tool call is not merely discouraged but absent from the
CLI's surface, and wall 1 asserts on the stream anyway. `canary_verdict()` in
`src/reading_room.py` is kept and tested, so running it later costs a script and
not a redesign.

## Files

```
ReadingRoom/
  README.md              this file — design, how to run it, pseudocode
  tests/
    TEST_PLAN.md         72 cases: input -> expected handling
    conftest.py          fixtures; puts the fake CLI on PATH
    fake_claude.py       a fake `claude` that replays canned replies
    test_a_isolation.py  A1-A12   the four walls
    test_b_rounds.py     B1-B10   round and split selection
    test_c_paper_text.py C1-C12   messy extraction output, injection, encoding
    test_d_parsing.py    D1-D14   the src/schemas.py contract
    test_e_semantic.py   E1-E12   valid but wrong
    test_f_retries.py    F1-F12   retries, concurrency, the ledger
    test_g_provenance.py G1-G12   NOT YET WRITTEN — the run record
  prompts/
    system_prompt.txt    NOT YET WRITTEN — the pinned minimal system prompt,
                         sha256'd into every run_environment.json. Changing it
                         is a promptbook version bump, not an edit
```

The runnable scripts are `scripts/20_reading_room.py` and
`scripts/21_check_responses.py`; the logic they call lives in
`src/reading_room.py` so it can be imported and tested (`import
20_reading_room` is not valid Python). This directory is the spec and the suite,
and the repo's script numbering stays unbroken.
