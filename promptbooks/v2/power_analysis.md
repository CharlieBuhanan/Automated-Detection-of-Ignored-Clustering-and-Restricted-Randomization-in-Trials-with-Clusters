# Power analysis — criteria (v2)

**Objective.** You are reviewing a cluster-randomized trial that has already passed screening. You decide whether its power analysis correctly accounted for clustering, and for restricted randomization if present.

**Task.** Decide whether the paper's **power analysis** was correct. Judge nothing else.

**Your reading conditions.** You are in a sealed room. You have **no tools** — no file access, no
web, no search, no memory of any other paper. Everything you may use is in this one message. You get
**one turn**: no follow-up question, no clarification, no second pass. You cannot see an answer key,
another paper's text, or any judgment made before this one.

**Criteria.** Test the numbered criteria below in order. `yes` = correct, `no` = incorrect. The
first one that matches decides; cite the deciding number in `promptbook_evidence`.

**Work through the criteria in order, then commit.**

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
2. **P2. This manuscript only** — use its text and supplement, not a protocol, registry, or prior
   report. “See our protocol paper” is `no`, not `undecidable`.
3. **P3. Correct requires all three, stated in this manuscript:** the approach is ascertainable
   (P4-P6); clustering is accounted for at every level (P7-P9); restricted randomization, if
   present, is too (P10-P13). Before answering `yes`, identify text supporting the effect/approach,
   cluster count, and ICC/design effect (or equivalent); do not infer a missing element from
   balanced arms or a cited method.

## Clarity and presence

4. **P4. Unclear is incorrect** — a sample size with no account of what produced it.
5. **P5. Naming a tool is not a description.** GLIMMPSE, PASS, Donner & Klar: cited alone, not
   enough. Need at minimum an ICC or design effect, an effect size, and a cluster count.
6. **P6. Absent is `no`, not `undecidable`.**

## Clustering

7. **P7. Accounting for clustering** means using a cluster-structure quantity and answering in
   clusters: an ICC; a design effect `1 + (m-1)p`; a coefficient of variation of cluster means; an
   explicit between-cluster variance; a simulation with within-cluster correlation.
8. **P8. Ignoring clustering** is an individual-level calculation — "n = 300 gives 80% power to
   detect d = 0.35" — with no ICC, design effect, or cluster count.
9. **P9. Every level counts.** Patients within physicians within clinics: all of them, or `no`.
   This is a common failure — check each level explicitly.

## Restricted randomization

10. **P10. Present if** clusters were pair-matched, matched into sets, stratified, block-randomized,
    minimized, or constrained on covariates. A reported block design still counts even if arms are
    balanced; call randomization simple only when the manuscript says it was unblocked and
    unstratified.
11. **P11. Accounting for it** means using the induced between-cluster correlation: a matching or
    stratum correlation, a reduced between-cluster variance, a matched-pair design effect, or a
    simulation reproducing the scheme.
12. **P12. Clustering handled but restriction ignored is `no`.**
13. **P13. Permissive literature does not apply.** Citing it, or calling the omission
    “conservative,” does not make ignored matching correct.
14. **P14. Restriction handled while clustering is ignored is `no`.**
15. **P15. Post-hoc power is not a power analysis** when offered in place of an a priori one.

## What must not count

16. **P16. Only clustering and restricted randomization decide this.** If both are handled, answer
    `yes`. Do not count effect-size or ICC plausibility, attrition, longitudinality, test choice,
    alpha, multiplicity, unequal cluster sizes, or target power.
17. **P17. Longitudinality does not count.** A power analysis that handles clustering and
    restriction but assumes one measurement per subject is **`yes`**.

## Abstention

18. **P18.** `undecidable` only when the methods text is unreadable.
