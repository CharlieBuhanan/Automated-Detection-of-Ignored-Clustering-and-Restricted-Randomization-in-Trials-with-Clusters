# Power analysis — criteria (v0)

Criteria only. Source: Glueck & Muller (`Ignore02.pdf`), Methods p.3-4.

`yes` = correct, `no` = incorrect. Only gate survivors get a row. Cite the deciding number in
`rubric_evidence`.

## Scope

1. **P1. Primary outcomes only** — the sample-size justification for the treatment effect on the
   primary outcome(s). Ignore secondary outcomes, subgroups, safety endpoints.
2. **P2. This manuscript only** — its text plus its own supplement. A calculation described in a
   protocol paper, registry record, or prior report does not count, however confidently cited.
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
    ICC, no attrition allowance, the wrong test, a one-sided alpha, no multiplicity adjustment,
    unequal cluster sizes, target power under 0.80.
17. **P17. Longitudinality** — *CONTESTED, default: does not count.* Ignore02 excludes it, NHLBI
    scored it. `MQF2Y5AM` is a known expected miss. See [Deb.md](Deb.md).

## Abstention

18. **P18.** `undecidable` only when the methods text is unreadable. Never for a hard call, never
    for a missing analysis — that is P6.
