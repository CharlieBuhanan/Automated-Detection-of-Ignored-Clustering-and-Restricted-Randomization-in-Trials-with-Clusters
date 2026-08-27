# Promptbook v1 — version log

Template: [`_TEMPLATE doc.md`](../_TEMPLATE%20doc.md). **Tables, not prose.**
Machine-readable numbers live in
`results/04_classification/promptbook_accuracy_history.csv`; anything below must
match a row there.

---

## Version

| | |
|---|---|
| Version | `v1` |
| Created | 2026-08-27 |
| Parent | `v0` |
| Git commit | set when v1 is frozen |
| Model used to build it | none — written from Deb's rulings, not from misses |
| Route | — |
| Status | **active**, never run |

**v1 is still not shaped by a miss.** Every change below comes from Deb's
2026-08-27 rulings on criteria v0 flagged as contested, not from a round result.
v2 is the first version that can be written against actual disagreements.

## What changed, and why

| Rule | Change | Reason | Papers it corrects | Round |
|---|---|---|---|---|
| E3 stepped wedge | **OFF → ON** | Deb ruled stepped wedge is an exclusion (DC48). v0 kept them because NHLBI excluded 9 but kept and scored 5, and a wrong exclusion is unrecoverable (DC11); Deb settled the criterion rather than the inconsistency | 9 rows NHLBI excluded for it | — |
| E17 random duplicate drop | **wording strengthened** | Deb confirmed 2026-08-27: the model must **never** drop a paper at random, for any reason. Generalized from "not this criterion" to "never randomly, ever" | — | — |
| D14 longitudinality | **CONTESTED → settled, does not count** | Deb: follow Ignore02 rule 6, which counts only clustering and restricted randomization (DC49). Also added explicitly to D13's *must not count* list | — | — |
| P17 longitudinality | **CONTESTED → settled, does not count** | Same ruling, same fold into P16. v0 left this one contested in parallel with D14 | — | — |
| E5 secondary analysis | unchanged, **marked confirmed** | Deb confirmed self-declared-only is what she wants for now, knowingly incomplete (DC28) | — | — |
| P2 / D3 protocol citation | unchanged, already confirmed | Carried from v0 (DC40) | — | — |

## Rounds available

Cut 2026-08-26 by `scripts/17_assign_build_rounds.py` into
`results/04_classification/build_rounds.csv`, fixed before any judging so no round can be
re-drawn after seeing a result (DC47). Membership is deterministic from `sha256(seed + paper_id)`.

| Task | Build papers | Rounds | Shape |
|---|---:|---:|---|
| exclusion | 338 | 7 | 6×50 + 38, each **18 survivor / 32 excluded** |
| power_analysis | 123 | 3 | 50 / 50 / 23 |
| data_analysis | 123 | 3 | 50 / 50 / 23 |

Run 1 is a proof of concept, so it uses the first rounds only, not all 7.

**Holdout shrank to 144 (52 survivors)** on 2026-08-27 when `XHFTHUCG` was dropped to the
expert-review pile (DC50). Build is untouched at 338, so no round changed size — a dropped paper
shrinks its round, it never triggers a re-cut (DC47).

## Rounds run against this version

None. v1 has never been executed.

| Round | Date | Split | Task | n | Accuracy | Δ vs prev | `undecidable` | `wrong_text` | Parse retries |
|---|---|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — | — | — |

## Misses not generalized

None yet — nothing has been run.

| Paper | Task | Human said | Model said | Why it was left alone |
|---|---|---|---|---|

## Known expected misses

Cases where the promptbook is *deliberately* wrong against the human labels, so they are not
mistaken for promptbook faults.

> **Read this before proposing any promptbook rule from a stepped-wedge miss.** Deb ruled
> 2026-08-27 that stepped wedge **is** an exclusion (DC48), so from v1 on the model excludes them.
> NHLBI applied that criterion inconsistently — 9 excluded, **5 kept and fully scored** — and the 5
> stay in the scored set as accepted misses by decision, *not* dropped (DC51). So a miss whose
> `promptbook_evidence` is `E3` is **presumed correct until checked against the list below**: the
> label is what is wrong, not the rule. Never write, loosen, or revert a rule off one of these five.
> They are also not evidence for DC23's pattern requirement — exclude them before counting a shape
> as repeated, or the loop will "learn" its way back to E3 OFF from five known-bad labels.

> **The same caution applies to longitudinality.** D14/P17 now say repeated measures does not make
> an analysis incorrect (DC49). Any miss where the label says `no` and the reviewer's comment names
> repeated measures, time, or exchangeability is expected — check `data_comment` before treating it
> as a rule fault.

| Shape | Why the promptbook disagrees on purpose | Papers |
|---|---|---|
| Stepped-wedge kept and scored by NHLBI | E3 ON (DC48). These 5 are labelled *keep*; the model excludes them. Accepted misses, kept in the scored set (DC51) | 5 — `3JVAWNIE` Bernabe-Ortiz, `TT7PIVLD` Ciccone, `7NYXSVAI` Douin (build); `QMLU4TM8` Courtright, `8H9BUEWH` Fiscella (holdout) |
| Longitudinality scored incorrect | D14/P17 settled (DC49): follow Ignore02 rule 6. NHLBI scored repeated-measures errors incorrect anyway | 1 known — `MQF2Y5AM` Altinger (holdout); more may surface, 41 labelled rows carry `n_long` ≥ 2 |

**Cost floor, exclusion task:** −0.9pp on build (3 of 338) and −1.4pp on holdout (2 of 144).
Compare a round's Δ against that floor, not against 0 — it is most of one plateau step (DC17).

`XHFTHUCG` (Cattamanchi) was on v0's list and is **no longer an expected miss**: it left the corpus
entirely on 2026-08-27 (DC50), so it is not scored at all.

## Plateau check

Plateau = two consecutive rounds each improving accuracy by under 1pp (DC17).

| Task | Last two Δ | Plateaued? | Sonnet check run? | Sonnet accuracy |
|---|---|---|---|---|
| exclusion | — | no | no | — |
| power_analysis | — | no | no | — |
| data_analysis | — | no | no | — |
