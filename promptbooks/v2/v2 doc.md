# Promptbook v2 — version log

Template: [`_TEMPLATE doc.md`](../_TEMPLATE%20doc.md). **Tables, not prose.**
Machine-readable **reporting** numbers live in
`results/04_classification/promptbook_accuracy_history.csv`; any reportable row
below must match one there. Paid raw-response provenance is separately retained
in its round environment and raw artifacts, even before it qualifies for a
history row.

---

## Version

| | |
|---|---|
| Version | `v2` |
| Created | 2026-08-28 |
| Parent | `v1` |
| Git commit | captured in each run environment; v2 must not be edited in place |
| Model used to build it | none — v1 miss review and references-stripped input |
| Route | Reading Room (`scripts/20_reading_room.py`) |
| Status | **draft**; do not run until v1 batch-1 results are analyzed |

**No DC17 accuracy delta is reportable for this version yet.** `exclusion_r1`
remains the baseline; its accepted `v1` whole-text judgments are not re-run and
round 1 does not restart. This version records stripped-text provenance for all
later runs (DC57), which must be labelled when compared with that baseline.

## What changed

| Change | Why | Baseline consequence |
|---|---|---|
| Input text is references-stripped (`data/extracted_text_stripped/`) | Reference titles can trigger criteria unrelated to the paper's study; stripping changes what the rubric reads | `exclusion_r1` remains the whole-text baseline; report version and preparation alongside comparisons |
| E6 protocol/design exception | Three v1 E6 false exclusions treated protocol status as baseline-only | A protocol/design paper with no effect estimate is kept unless an independent criterion applies |
| P3 evidence checklist; P10 block-design clarification | Four v1 power false positives treated incomplete or block-restricted calculations as adequate | `yes` requires explicit within-manuscript support; balanced block allocation is not simple randomization |
| D5/D7/D8/D10 evidence anchors | Batch 1 data misses show the model over-credits named methods, fixed effects, incomplete nesting, and unrelated covariates | A `yes` now requires the exact correlation unit, random (not fixed) effect, every material clustering level, and the actual restriction or its variables in the primary model |

Power remains byte-identical to `v1`; exclusion adds the E6 exception and data adds
the D5/D7/D8/D10 evidence anchors above. This is a draft until the v1 batch-1
review is complete.

**`v1` is not shaped by a miss.** Every change below comes from Deb's 2026-08-27
rulings on criteria `v0` flagged as contested, plus one environment change from a
harness probe. No change below was written against the later paid round results.

## Parent `v1` history (inherited rules)

| | |
|---|---|
| What happened | An earlier `v1` and `v2` were cut on 2026-08-27, hours apart. Neither was ever run. They were collapsed into this single `v1` the same day |
| Why | Both bumps were made before any paper was judged, so neither has a number attached and neither can be compared to anything. Three directories recording one un-run state is version noise, not provenance |
| What was lost | Nothing. Both are in git history — `91403fa` cut the old `v1`, `37130f4` the old `v2` |
| The rule going forward | Before a first paid/raw request, **a new `promptbooks/vN/` requires a human-verified rubric change** — a criterion a reviewer has ruled on, or a rule written from a pattern of real misses. Wording, formatting, and token trimming may happen in place only in that draft phase. The first paid/raw request makes the version run-frozen; a history row is a later reporting milestone, not the event that freezes paid evidence. See DC53 |

## What changed, and why

Criteria first, then the prompt block. Everything in the first group is a rule
change from Deb's rulings; the last row is environment description that never
decides a paper.

| Rule | Change | Reason | Papers it corrects | Round |
|---|---|---|---|---|
| E3 stepped wedge | **OFF → ON** | Deb ruled stepped wedge is an exclusion (DC48). `v0` kept them because NHLBI excluded 9 but kept and scored 5, and a wrong exclusion is unrecoverable (DC11); Deb settled the criterion rather than the inconsistency | 9 rows NHLBI excluded for it | — |
| E17 random duplicate drop | **wording strengthened** | Deb confirmed 2026-08-27: the model must **never** drop a paper at random, for any reason. Generalized from "not this criterion" to "never randomly, ever" | — | — |
| D14 longitudinality | **CONTESTED → settled, does not count** | Deb: follow Ignore02 rule 6, which counts only clustering and restricted randomization (DC49). Also added explicitly to D13's *must not count* list | — | — |
| P17 longitudinality | **CONTESTED → settled, does not count** | Same ruling, same fold into P16. `v0` left this one contested in parallel with D14 | — | — |
| E5 secondary analysis | unchanged, **marked confirmed** | Deb confirmed self-declared-only is what she wants for now, knowingly incomplete (DC28) | — | — |
| P2 / D3 protocol citation | unchanged, already confirmed | Carried from `v0` (DC40) | — | — |
| **Prompt block: new "Your reading conditions" paragraph** (all three tasks) | **added** | Not a criterion. The room's isolation was true but unstated, so a refusal or a hedge ("I would need to check the protocol") was indistinguishable from a judgment. Stating the conditions makes the abstention rules (`undecidable`, `wrong_text`) mean what they say: no further information is reachable, so a hard call is still a call | — | — |

## Why the prompt block changed at all

| Trigger | Detail |
|---|---|
| Harness probe, 2026-08-27 | CLI 2.1.197 `system/init` returns `"tools":[]` under `--tools ""`. The "no tools" claim in the prompt is **verified**, not asserted — see `ReadingRoom/README.md` |
| Run-environment change | `v1` is the first version run with a **pinned minimal system prompt** replacing Claude Code's ~12,200-token agentic default. Without that persona the model has no implicit statement of its situation left, so the promptbook has to carry it |
| Rule for the future | The reading-conditions paragraph is **environment description, not a criterion.** It is never cited in `promptbook_evidence` and never decides a paper. Changing it after this version has been run is still a version bump, because it changes the bytes sent |

## Run environment pinned by this version

Recorded per round in `run_environment.json`. A configuration change creates a
separate provenance stratum and cannot be pooled for G11/DC17; it requires `v2`
only when the promptbook bytes change.

| | |
|---|---|
| Model | `claude-sonnet-5` (complete ID — no dated snapshot is exposed by the CLI or the API) |
| Effort | Legacy Reading Room round 1 used `high`; all new production calls are pinned to `medium`. They share frozen v1 text but are distinct configuration strata, and mixed reuse is exploratory only |
| Thinking | adaptive, the only on-mode on Sonnet 5. Not separately configurable from the CLI; `budget_tokens` is removed on this model |
| System prompt | `ReadingRoom/prompts/system_prompt.txt`, pinned and `sha256` logged. **Not** the Claude Code default. One line, because a newline in it silently drops later argv flags on Windows |
| Tools | none — `--tools ""`, `permissions.deny`, and an assertion on the CLI's reported `tools` array |
| Turns | `--max-turns 1` |

## Rounds available

Cut 2026-08-26 by `scripts/17_assign_build_rounds.py` into
`results/04_classification/build_rounds.csv`, fixed before any judging so no
round can be re-cut to flatter a number (DC47). Membership is deterministic from
`sha256(seed + paper_id)`.

| Task | Build papers | Rounds | Shape |
|---|---:|---:|---|
| exclusion | 335 | 7 | 6×50 + 38, less the three that run short after script 18 |
| power_analysis | 123 | 3 | 50 / 50 / 23 |
| data_analysis | 123 | 3 | 50 / 50 / 23 |

Run 1 is a proof of concept, so it uses the first rounds only, not all 7.

**Build 338 → 335 and holdout 145 → 142** on 2026-08-27, when
`scripts/18_drop_expert_review.py` moved 6 papers to the expert-review pile
(DC50/DC52). A dropped paper shrinks its round; it never triggers a re-cut
(DC47).

## Rounds run against this version

`v1` has paid Reading Room evidence: exclusion round 1 has 49 accepted
judgments; data-analysis round 1 has 49 raw replies, of which 40 passed the
checker and await persistence, one failed the reasoning-length/schema check,
and eight had process failures. These legacy high-effort results are evidence
of run-freezing, not reportable medium-effort or plateau rows.

| Round | Date | Split | Task | n | Accuracy | Δ vs prev | `undecidable` | `wrong_text` | Parse retries |
|---|---|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — | — | — |

## Misses not generalized

No v1 miss has yet been generalized into a rule after the paid rounds.

| Paper | Task | Human said | Model said | Why it was left alone |
|---|---|---|---|---|

## Known expected misses

Cases where the promptbook is *deliberately* wrong against the human labels, so
they are not mistaken for promptbook faults.

> **The longitudinality caution.** D14/P17 now say repeated measures does not
> make an analysis incorrect (DC49). Any miss where the label says `no` and the
> reviewer's comment names repeated measures, time, or exchangeability is
> expected — check `data_comment` before treating it as a rule fault.

| Task | Papers | Why the label disagrees on purpose |
|---|---|---|
| exclusion | *(none)* | The 5 analyzed stepped-wedge papers NHLBI kept were moved to the expert-review pile by `scripts/18_drop_expert_review.py` (DC52), so `v1` carries **no accepted-miss floor** and a round's Δ is compared against 0 |
| data_analysis | `MQF2Y5AM` Altinger | D14: NHLBI scored it incorrect for longitudinality; Deb ruled longitudinality does not count (DC49) |

`XHFTHUCG` (Cattamanchi) was on `v0`'s list and is **no longer an expected
miss**: it left the corpus entirely on 2026-08-27 (DC50), so it is not scored.

## Plateau check

Plateau = two consecutive rounds each improving accuracy by under 1pp (DC17).

| Task | Last two Δ | Plateaued? | Sonnet check run? | Sonnet accuracy |
|---|---|---|---|---|
| exclusion | — | no | no | — |
| power_analysis | — | no | no | — |
| data_analysis | — | no | no | — |
