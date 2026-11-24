# Promptbook v3 — version log

Machine-readable reporting metrics live in
`results/04_classification/promptbook_accuracy_history.csv`. Run environments
and raw responses retain the corresponding provenance.

## Version

| | |
|---|---|
| Version | `v3` |
| Created | 2026-11-24 |
| Parent | `v2` (run-frozen 2026-11-24 by the 2-paper smoke test) |
| Git commit | captured in each run environment |
| Model used to build it | none |
| Route | Reading Room (`scripts/20_reading_room.py`) |
| Status | **un-run draft** |

## Delta from v2

The E, P and D criteria are unchanged. `exclusion.md` is byte-identical to v2.

| Change | Reason | Comparison rule |
|---|---|---|
| **Prompt layout `system`**: the promptbook and the answer instructions go in the system prompt (passed with `--system-prompt-file`), once. The user message is only the paper between BEGIN/END PAPER markers, plus a short closing that names the `paper_id` and points back to the system prompt | v2 smoke test: cache reads were 0 on all 6 calls and every input token was written to the 1-hour cache, which was never read. In the system prompt, the fixed part is cached and read back from paper 2 on. User, 2026-11-24 | Replaces the DC26 "sandwich" (a second full copy of the promptbook after the paper). User chose one copy: the system prompt already outranks paper text, and the paper is still fenced as data. Not comparable to v2 as a configuration |
| `combined_analysis.md`: when `ind_samp_unit` is `matched_pair` or `stratum`, it must also be the last entry in `levels` | v2 smoke test: 3 of 4 combined attempts (`WCA66X4I` ×2, `6XFGQN39` ×1) set `ind_samp_unit: stratum` without `stratum` in `levels`, and the checker rejected them. A pattern, not one paper. The check stays strict | Wording only; the rule it states was already enforced by `schemas.StudyDesign` |

Not changed in v3 (seen, not yet a pattern): bare unit words such as
`clinician` without `other: ` (Charlie.md #3, retry and count first);
`small_sample_correction: "not_reported"` (seen once). E19 limits stay
60 / 200 characters (user, 2026-11-24).

## How the layout is recorded

`reading_room.prompt_layout(version)` is an explicit table: v0–v2 are
`sandwich`, every later version is `system`. For a `system` round the runner
writes the exact system prompt to `<raw dir>/system_prompt.txt`, and
`run_environment.json` records its sha256 and `prompt_layout`. The checker
rebuilds the system prompt from the frozen book and refuses if the hash moved.

The preflight probe runs with the same system-prompt file, so it also proves
the file was loaded (its billed tokens must sit inside a range set by the file's
length; the CLI's default persona measured 12,198) and warms the cache for
paper 1.

## Run and reporting state

| Round | Date | Split | Task | n | Accuracy | Δ vs previous | `undecidable` | `wrong_text` | Parse retries |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| — | — | — | — | — | — | — | — | — | — |

## Expected misses

Inherited from v2: `MQF2Y5AM` (Altinger) on data_analysis (DC49).
