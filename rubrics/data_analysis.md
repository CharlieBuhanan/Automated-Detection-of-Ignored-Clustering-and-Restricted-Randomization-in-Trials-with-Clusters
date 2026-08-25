# Data analysis — criteria (v0)

Criteria only. Source: Glueck & Muller (`Ignore02.pdf`), Methods p.3-4.

`yes` = correct, `no` = incorrect. Only gate survivors get a row. Cite the deciding number in
`rubric_evidence`.

## Scope

1. **D1. Primary outcomes only** — analyses estimating or testing the treatment effect on the
   primary outcome(s). Ignore secondary outcomes, subgroups, baseline tables.
2. **D2. Conjunctive — every one must be correct.** All reported primary-outcome analyses must pass
   D5-D12, including sensitivity, per-protocol, and unadjusted re-analyses; one failure decides the
   paper. *Anchor:* `4B9BMDV7` — a correct mixed model, then t-tests at the end — is `no`.
3. **D3. This manuscript only** — its text plus its own supplement.
4. **D4. Absent or undescribed is `no`** — including "outcomes were compared between arms."

## Clustering

5. **D5. Accounting for clustering** means one of: a mixed model with a **random** effect for the
   randomization unit; GEE with the cluster as working-correlation unit; a cluster-level summary
   analysis; cluster-robust standard errors; a cluster-level permutation test; a Bayesian
   hierarchical model with a cluster random effect.
6. **D6. Ignoring clustering** is an individual-level analysis with nothing above it — t-test,
   chi-square, Wilcoxon, ANCOVA, or a regression with no random effect, no clustered SEs, no
   aggregation.
7. **D7. A fixed effect for the cluster does not count.** Cluster indicators shift each cluster's
   mean but leave the residuals independent, so the correlation is never modelled and the standard
   errors stay too small. Two labelled papers score `no` for this, one of them a mixed model —
   *which* effect is random is what matters.
8. **D8. Every level counts.** Clinic but not physician, school but not classroom → `no`. The most
   common failure in the NHLBI extraction.

## Restricted randomization

9. **D9. Present if** clusters were pair-matched, matched into sets, stratified, block-randomized,
   minimized, or constrained on covariates. Read the randomization paragraph, not the analysis one.
10. **D10. Accounting for it** means the pair or stratum enters as a random effect or blocking
    factor, or the analysis is of within-pair differences, or the working correlation reflects the
    matched sets, or the stratification variables are adjusted for.
11. **D11. Clustering handled, restriction ignored, is `no`.** Roughly forty labelled rows take this
    shape. Both sources of correlation, or neither.
12. **D12. Restriction handled while clustering ignored does not occur.** None of the 96 papers did
    this; reaching that conclusion means re-read.

## What must not count

13. **D13. Only clustering and restricted randomization decide this.** If both are handled, answer
    `yes` however flawed the rest is. Not grounds for `no`: GEE without small-sample bias correction
    (corrected and uncorrected are treated identically), compound symmetry on repeated measures, the
    wrong link function, no multiplicity adjustment, missing-data handling, adjusted vs unadjusted,
    unequal cluster sizes, ITT vs per-protocol, no reported ICC.
14. **D14. Longitudinality** — *CONTESTED, default: does not count.* Ignore02 excludes it, NHLBI
    scored it. `MQF2Y5AM` is a known expected miss. See [Deb.md](Deb.md).

## Abstention

15. **D15.** `undecidable` only when the methods and results text is unreadable. Never for a hard
    call, never for a vague description — that is D4.
