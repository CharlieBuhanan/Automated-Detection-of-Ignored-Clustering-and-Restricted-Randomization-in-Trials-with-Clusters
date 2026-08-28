# Power analysis — criteria (v1)

> **Documentation rule for this file.** Every rule is one numbered line: the
> criterion, then the test that decides it. No prose paragraphs, no rationale
> inline — rationale goes in [`v1 doc.md`](v1%20doc.md) as a table row naming the
> papers the rule was written against. Two audiences read this file, a human
> editing a rule and a model being handed it as a prompt (DC25), and both do
> better with a table than with an argument.
>
> **Never edit a frozen version.** To change a rule, copy this directory to the
> next `vN/`, edit there, update `promptbooks/CURRENT`, and log the change in
> that version's doc. A judgment records `promptbook_version`, so a rule that
> changed under a fixed version makes every earlier judgment unreproducible.


`yes` = correct, `no` = incorrect. Only gate survivors get a row. Cite the deciding number in
`promptbook_evidence`.

## Prompt

> Everything in this block is sent to the model verbatim, before the paper text.
> Structure follows ISO-ScreenPrompt (Cao et al. 2024): objective → numbered criteria →
> article → instructions repeated *after* the article. The repeat is not optional — Cao
> found instructions placed only before a full text get lost in long context.

**Objective.** You are reviewing a cluster-randomised trial that has already passed screening. You decide whether its power analysis correctly accounted for clustering, and for restricted randomisation if present.

**Task.** Read the paper below and return one decision for **power analysis** only. Judge nothing else.
Judge only the manuscript in hand: you cannot see any other paper, and no other paper's existence
is ever a reason for your answer.

**Your reading conditions.** You are in a sealed room. You have **no tools** — no file access, no
web, no search, no memory of any other paper. Everything you may use is in this one message. You get
**one turn**: no follow-up question, no clarification, no second pass. You cannot see an answer key,
another paper's text, or any judgment made before this one. This is enforced by the harness, not by
your cooperation, so there is no route to more information and asking for one spends the turn.
Decide from the text in hand.

**Criteria.** Test the numbered criteria below in order. The first one that matches decides.

**Think it through step by step** before answering: work through the criteria in order, say what
the paper shows for each, then commit.

**Answer format.** Return exactly these four fields:

| field | value |
|---|---|
| `decision` | `yes` = the power analysis is correct · `no` = it is incorrect or absent · `undecidable` = text missing, truncated, or unreadable |
| `reasoning` | why, in your own words. **200 characters maximum.** |
| `promptbook_evidence` | the criterion number that decided it, e.g. `P3` |
| `confidence` | 0.0-1.0 |

`undecidable` is an abstention for genuinely unreadable text, **not** for a hard call. A difficult
paper still gets a `yes` or a `no`.

---
## Scope

1. **P1. Primary outcomes only** — the sample-size justification for the treatment effect on the
   primary outcome(s). Ignore secondary outcomes, subgroups, safety endpoints.
2. **P2. This manuscript only** — its text plus its own supplement. A calculation described in a
   protocol paper, registry record, or prior report does not count, however confidently cited: if
   this manuscript's power justification is "see our protocol paper," that is `no`, full stop —
   not `undecidable`. **Confirmed by Deb.**
3. **P3. Correct requires all three:** the approach is ascertainable (P4-P6); clustering is
   accounted for at every level (P7-P9); restricted randomization, if present, is too (P10-P13).

## Clarity and presence

4. **P4. Unclear is incorrect** — a sample size with no account of what produced it.
5. **P5. Naming a tool is not a description.** GLIMMPSE, PASS, Donner & Klar: cited alone, not
   enough. Need at minimum an ICC or design effect, an effect size, and a cluster count.
6. **P6. Absent is `no`, not `undecidable`.** The likeliest place to hedge. Do not.

## Clustering

7. **P7. Accounting for clustering** means using a cluster-structure quantity and answering in
   clusters: an ICC; a design effect `1 + (m-1)p`; a coefficient of variation of cluster means; an
   explicit between-cluster variance; a simulation with within-cluster correlation.
8. **P8. Ignoring clustering** is an individual-level calculation — "n = 300 gives 80% power to
   detect d = 0.35" — with no ICC, design effect, or cluster count.
9. **P9. Every level counts.** Patients within physicians within clinics: all of them, or `no`.
   The most common failure in the NHLBI extraction.

## Restricted randomization

10. **P10. Present if** clusters were pair-matched, matched into sets, stratified, block-randomized,
    minimized, or constrained on covariates.
11. **P11. Accounting for it** means using the induced between-cluster correlation: a matching or
    stratum correlation, a reduced between-cluster variance, a matched-pair design effect, or a
    simulation reproducing the scheme.
12. **P12. Clustering handled, restriction ignored, is `no`.** The largest single pattern in the
    labelled data. Both sources of correlation, or neither.
13. **P13. The permissive literature does not apply.** Martin, Diehr, Proschan, Rutterford, and
    Leyrat all allow ignoring matching in sample size (Ignore02 Table S4). This protocol does not —
    citing them, or calling the omission "conservative," is still `no`.
14. **P14. Restriction handled while clustering ignored does not occur.** None of the 96 papers did
    this; reaching that conclusion means re-read.
15. **P15. Post-hoc power is not a power analysis** when offered in place of an a priori one.

## What must not count

16. **P16. Only clustering and restricted randomization decide this.** If both are handled, answer
    `yes` however poor the rest is. Not grounds for `no`: an optimistic effect size, an implausible
    ICC, no attrition allowance, **longitudinality — no allowance for repeated measures over
    time**, the wrong test, a one-sided alpha, no multiplicity adjustment, unequal cluster sizes,
    target power under 0.80.
17. **P17. Longitudinality does not count — settled** (Deb, 2026-08-27; DC49). Ignore02 rule 6
    counts exactly two things, and repeated measures is not one of them. A power analysis that
    handles clustering and restriction but assumes one measurement per subject is **`yes`**. NHLBI
    scored at least one such paper incorrect anyway (`MQF2Y5AM`, Altinger) — a known accepted miss,
    not a fault in this rule.

## Abstention

18. **P18.** `undecidable` only when the methods text is unreadable. Never for a hard call, never
    for a missing analysis — that is P6.
