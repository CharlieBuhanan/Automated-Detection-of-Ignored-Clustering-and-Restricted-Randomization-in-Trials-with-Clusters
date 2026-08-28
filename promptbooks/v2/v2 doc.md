# Promptbook v2 — version log

Template: [`_TEMPLATE doc.md`](../_TEMPLATE%20doc.md). **Tables, not prose.**
Machine-readable numbers live in
`results/04_classification/promptbook_accuracy_history.csv`; anything below must
match a row there.

---

## Version

| | |
|---|---|
| Version | `v2` |
| Created | 2026-08-27 |
| Parent | `v1` |
| Git commit | set when v2 is frozen |
| Model used to build it | none — written from a harness finding, not from misses |
| Route | Reading Room (`scripts/20_reading_room.py`) |
| Status | **active**, never run |

**No accuracy delta is reportable for this bump.** `v1` was frozen and never
scored — `promptbook_accuracy_history.csv` does not exist yet, so there is no
`v1` row for a `v2` row to be compared against. The repo rule's "commit the
version bump with the accuracy delta" is satisfied vacuously here and resumes at
`v3`. **v2 is the first version that will be run.**

## What changed, and why

| Rule | Change | Reason | Papers it corrects | Round |
|---|---|---|---|---|
| *(none — no criterion changed)* | — | Every numbered rule is byte-identical to `v1` | — | — |
| **Prompt block: new "Your reading conditions" paragraph** (all three tasks) | **added** | The room's isolation was true but unstated. Under `v1` the model was told nothing about its environment, so a refusal or a hedge ("I would need to check the protocol") was indistinguishable from a judgment. Stating the conditions makes the abstention rules (`undecidable`, `wrong_text`) mean what they say: no further information is reachable, so a hard call is still a call | — | — |

## Why the prompt changed at all

| Trigger | Detail |
|---|---|
| Harness probe, 2026-08-27 | CLI 2.1.197 `system/init` returns `"tools":[]` under `--tools ""`. The "no tools" claim in the prompt is now **verified**, not asserted — see `ReadingRoom/README.md` |
| Run-environment change | `v2` is the first version run with a **pinned minimal system prompt** replacing Claude Code's ~12,200-token agentic default. Without the default persona the model no longer has any implicit statement of its situation, so the promptbook has to carry it |
| Rule for the future | The reading-conditions paragraph is **environment description, not a criterion.** It is never cited in `promptbook_evidence` and never decides a paper. A change to it is still a version bump, because it changes the bytes sent |

## Run environment pinned by this version

Recorded per round in `run_environment.json`; a change to any row is a `v3`.

| | |
|---|---|
| Model | `claude-sonnet-5` (complete ID — no dated snapshot is exposed by the CLI or the API) |
| Effort | `high` — pinned identically on the Reading Room (`--effort high`) and the Batch API (`output_config.effort`) |
| Thinking | adaptive, the only on-mode on Sonnet 5. Not separately configurable from the CLI; `budget_tokens` is removed on this model |
| System prompt | pinned minimal, stored in the repo, `sha256` logged. **Not** the Claude Code default |
| Tools | none — `--tools ""`, `permissions.deny`, and an assertion on the CLI's reported `tools` array |
| Turns | `--max-turns 1` |

## Rounds available

Unchanged from `v1`. Cut 2026-08-26 by `scripts/17_assign_build_rounds.py` into
`results/04_classification/build_rounds.csv`, fixed before any judging so no
round can be re-cut to flatter a number (DC47).

| Task | Rounds | Sizes |
|---|---|---|
| exclusion | 7 | 6×50 + 38, less the three that run short after script 18 |
| power_analysis | 3 | 50 / 50 / 23 |
| data_analysis | 3 | 50 / 50 / 23 |

## Known expected misses

| Task | Papers | Why the label disagrees on purpose |
|---|---|---|
| exclusion | *(none)* | The 5 analyzed stepped-wedge papers NHLBI kept were moved to the expert-review pile by `scripts/18_drop_expert_review.py` (DC52), so `v2` carries no accepted-miss floor |
| data_analysis | `MQF2Y5AM` Altinger | D14: NHLBI scored it incorrect for longitudinality; Deb ruled longitudinality does not count (DC49) |
