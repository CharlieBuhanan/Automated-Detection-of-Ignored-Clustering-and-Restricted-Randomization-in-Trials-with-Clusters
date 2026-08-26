# Promptbook version log — TEMPLATE

Copy this into each `vX/` as `vX doc.md`. **Tables, not prose.** Every row is one
change; if a change needs a paragraph to justify, it is probably two changes.

The numbers here are the human-readable record. The machine-readable one is
`results/04_classification/promptbook_accuracy_history.csv` — that is what gets
plotted and cited. Anything in a table below must match a row there.

---

## Version

| | |
|---|---|
| Version | `vX` |
| Created | YYYY-MM-DD |
| Parent | `vX-1` (or `—` for v0) |
| Git commit | hash of the commit that froze this version |
| Model used to build it | Claude Opus 5 / Sonnet 5 |
| Route | CLI / Batch API |
| Status | active / superseded / abandoned |

## What changed, and why

One row per rule added, edited, or removed. `Papers` names the specific
paper_ids the change was written against — DC23 requires a **pattern**, so a row
with one paper_id had better be logged as a one-off, not generalized into a rule.

| Rule | Change | Reason | Papers it corrects | Round |
|---|---|---|---|---|
| E9 | added | 6 observational papers judged `no`; promptbook was silent on single-arm | `ABC12345`, `DEF67890`, … | R2 |
| E3 | disabled | contested; NHLBI excluded 9 wedges but scored 5 | — | R0 |

## Rounds run against this version

`n` is papers judged, not calls (a retry is not a paper). Accuracy is over
scored papers only: `undecidable` and `wrong_text` are excluded from the
denominator, and counted separately here so a rising abstention rate is visible
against flat accuracy (DC17).

| Round | Date | Split | Task | n | Accuracy | Δ vs prev | `undecidable` | `wrong_text` | Parse retries |
|---|---|---|---|---|---|---|---|---|---|
| R1 | YYYY-MM-DD | build | exclusion | 50 | 00.0% | — | 0 | 0 | 0 |

## Misses not generalized

DC23's other half: a miss with no pattern behind it is logged, never written
into a rule. If the same shape shows up again, it graduates to the table above.

| Paper | Task | Human said | Model said | Why it was left alone |
|---|---|---|---|---|

## Plateau check

Plateau = two consecutive rounds each improving accuracy by under 1pp (DC17).

| Task | Last two Δ | Plateaued? | Sonnet check run? | Sonnet accuracy |
|---|---|---|---|---|
| exclusion | | | | |
| power_analysis | | | | |
| data_analysis | | | | |
