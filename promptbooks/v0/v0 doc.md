# Promptbook v0 — version log

Template: [`_TEMPLATE doc.md`](../_TEMPLATE%20doc.md). **Tables, not prose.**
Machine-readable numbers live in
`results/04_classification/promptbook_accuracy_history.csv`; anything below must
match a row there.

---

## Version

| | |
|---|---|
| Version | `v0` |
| Created | 2026-08-26 |
| Parent | — (first version) |
| Git commit | set when v0 is frozen |
| Model used to build it | none yet — written from Ignore02, not from misses |
| Route | — |
| Status | **active**, never run |

**v0 is the hand-written baseline.** It transcribes Glueck & Muller's stated
criteria (`Ignore02.pdf`, Methods p.3 + Supplemental A) plus NHLBI's additions.
No round has been run against it, so every accuracy cell below is empty by
design — v1 is the first version shaped by an actual miss.

## What changed, and why

Not "changed" here, since there is no parent — these are the decisions taken
while transcribing Ignore02 into rules, and the ones deliberately left out.

| Rule | Change | Reason | Papers it corrects | Round |
|---|---|---|---|---|
| E1-E16 | added | direct transcription of Ignore02's criteria + NHLBI's additions | — | — |
| E3 stepped wedge | **added, default OFF** | contested: NHLBI excluded 9 wedges but kept and scored 5. A wrong exclusion is unrecoverable (DC11), so the gate keeps them. **Superseded — Deb ruled ON, 2026-08-27 (DC48); v1 flips it.** v0's own rule stays OFF, which is what v0 was | — | — |
| E5 secondary analysis | rewritten **self-declared only** | largest category (164 papers). "Is a secondary analysis" is a corpus fact; "says it is one" is in the text (DC28). **Confirmed by Deb, 2026-08-27**, knowingly incomplete | — | — |
| E12 protocol paper | **retired** | requires knowing the outcomes paper exists elsewhere — cross-paper, model cannot see the corpus (DC28). Its 9 papers left the scored set | — | — |
| E17 random duplicate drop | **retired** | a coin flip among same-first-author papers; unreproducible from text (DC28). Its 34 papers left the scored set | — | — |
| E13 pilot/feasibility | added | NHLBI addition, not in Ignore02; confirmed by Deb (DC39) | — | — |
| `wrong_text` | added as a fourth decision | exclusion only; separates "the call is unclear" from "this is not the paper" (DC41) | — | — |
| `reasoning` cap | 60 words → **200 characters** | 2026-08-26. A character cap is checkable by the validator without tokenizing; 200 chars is roughly the same length and removes the word-counting ambiguity (DC27) | — | — |

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

## Rounds run against this version

None. v0 has never been executed.

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
> 2026-08-27 that stepped wedge **is** an exclusion (DC48). The five NHLBI rows kept and scored
> despite that criterion were moved to expert review by DC52 and are not in the scored set. Never
> loosen or revert E3 based on them.

| Shape | Why the promptbook disagrees on purpose | Papers |
|---|---|---|
| Longitudinality scored incorrect | Settled 2026-08-27 (DC49): follow Ignore02 rule 6 — only clustering and restricted randomization count. NHLBI scored repeated-measures errors incorrect anyway | 1 known — `MQF2Y5AM` Altinger (holdout); more may surface, 41 labelled rows carry `n_long` ≥ 2 |

## Plateau check

Plateau = two consecutive rounds each improving accuracy by under 1pp (DC17).

| Task | Last two Δ | Plateaued? | Sonnet check run? | Sonnet accuracy |
|---|---|---|---|---|
| exclusion | — | no | no | — |
| power_analysis | — | no | no | — |
| data_analysis | — | no | no | — |
