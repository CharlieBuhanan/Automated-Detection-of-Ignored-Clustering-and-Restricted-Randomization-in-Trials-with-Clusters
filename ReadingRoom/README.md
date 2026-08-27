# The Reading Room

**Status: design + test plan only. No implementation yet, on purpose.**
Tests are being written first (`tests/`), because a leak here is silent — a
contaminated accuracy number looks exactly like a good one.

A sealed room where a reviewer is handed exactly one paper, may not bring
anything else in, and hands back exactly one filled-in form. Full rationale in
[PLAN.md](../research%20design/PLAN.md)'s *The Reading Room*; this file is the
build spec.

---

## Why this is not just "call the CLI in a loop"

`claude -p` is **agentic, not a completion endpoint**. Run inside this repo it
has file tools, and `data/ground_truth.csv`, `data/review.db`, and an
auto-loaded `CLAUDE.md` naming both are sitting right there.

**Telling it not to look is not a control. Removing the ability to look is.**

If the model reads the answers, accuracy goes up and nothing in the output says
so. That is the failure this whole directory exists to prevent.

## The four walls

| Wall | How | What it stops |
|---|---|---|
| **Empty room** | `cwd` = scratch dir outside the repo. Never `--add-dir`. | No CLAUDE.md, no memory, no relative path to the answers resolves |
| **No hands** | `--max-turns 1`, empty `--allowed-tools` | Makes it a pure text completion — it cannot read a file even if it decides to |
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
                   --allowed-tools ""             # empty = no hands
                   --output-format stream-json    # so we can SEE tool attempts
                   --model <full pinned id>
                   --strict-mcp-config
                   --settings <the file above>
                 with cwd=scratch, stdin=prompt
      save result VERBATIM, before parsing        # raw bytes are the evidence
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

What *is* achievable is a reproducible **procedure**: log the model ID, CLI
version, promptbook version (git commit), and the verbatim raw response. Never
pass `--resume`, `--continue`, or a reused `--session-id` — every invocation is
a fresh process with no shared history.

## Verified three ways

1. **`stream-json` assertion** — zero `tool_use` blocks per paper; discard any
   round with one.
2. **Canary run** — ~20 papers against a *decoy* `ground_truth.csv` with flipped
   labels, tools deliberately **on**. If accuracy tracks the decoy, the model is
   reading rather than reasoning. This is the only test that proves the walls
   matter rather than assuming it.
3. **The holdout**, run once through the Batch API, which does not depend on
   trusting this loop at all.

## Files

```
ReadingRoom/
  README.md              this file — design + pseudocode
  tests/
    TEST_PLAN.md         72 cases: input -> expected handling
```

Scripts land in `scripts/20_*.py` and `scripts/21_*.py` when written, not here —
this directory is the spec, the repo's script numbering stays unbroken.
