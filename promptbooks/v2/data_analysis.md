# Data analysis — criteria (v1)

**Objective.** You are reviewing a cluster-randomized trial that has already passed screening. You decide whether its data analysis correctly accounted for clustering, and for restricted randomization if present.

**Task.** Read the paper below and return one decision for whether the **data analysis** was correct, based on the criteria below. Judge nothing else.

**Your reading conditions.** You are in a sealed room. You have **no tools** — no file access, no
web, no search, no memory of any other paper. Everything you may use is in this one message. You get
**one turn**: no follow-up question, no clarification, no second pass. You cannot see an answer key,
another paper's text, or any judgment made before this one.

**Criteria.** Test the numbered criteria below in order. `yes` = correct, `no` = incorrect. The
first one that matches decides; cite the deciding number in `promptbook_evidence`.

**Think it through step by step** before answering: work through the criteria in order, say what
the paper shows for each, then commit.

**Answer format.** Return exactly these four fields:

| field | value |
|---|---|
| `decision` | `yes` = the data analysis is correct · `no` = it is incorrect or absent · `undecidable` = text missing, truncated, or unreadable |
| `reasoning` | why, in your own words. **200 characters maximum.** |
| `promptbook_evidence` | the criterion number that decided it, e.g. `D3` |
| `confidence` | 0.0-1.0 |

`undecidable` is an abstention for genuinely unreadable text, **not** for a hard call. A difficult
paper still gets a `yes` or a `no`.

---

## Scope

1. **D1. Primary outcomes only** — analyses estimating or testing the treatment effect on the
   primary outcome(s). Ignore secondary outcomes, subgroups, baseline tables.
2. **D2. Conjunctive — every one must be correct.** All reported primary-outcome analyses must pass
   D5-D12, including sensitivity, per-protocol, and unadjusted re-analyses; one failure decides the
   paper. *Anchor:* a correct mixed model followed by t-tests at the end is `no`.
3. **D3. This manuscript only** — its text plus its own supplement. An analysis described in a
   protocol paper, registry record, or prior report does not count, however confidently cited: if
   this manuscript points to its protocol for the analysis, that is `no`.
4. **D4. Absent or undescribed is `no`** — including "outcomes were compared between arms."

## Clustering

5. **D5. Accounting for clustering** means one of: a mixed model with a **random** effect for the
   randomization unit; GEE with the cluster as working-correlation unit; a cluster-level summary
   analysis; cluster-robust standard errors; a cluster-level permutation test; a Bayesian
   hierarchical model with a cluster random effect. **Name the correlation unit from the analysis
   text.** Do not credit the bare name of a method: the manuscript must say which unit the GEE,
   robust SE, or random effect accounts for.
6. **D6. Ignoring clustering** is an individual-level analysis with nothing above it — t-test,
   chi-square, Wilcoxon, ANCOVA, or a regression with no random effect, no clustered SEs, no
   aggregation.
7. **D7. A fixed effect for the cluster does not count.** Cluster indicators shift each cluster's
   mean but leave the residuals independent, so the correlation is never modelled and the standard
   errors stay too small. This catches mixed models too — *which* effect is random is what matters.
8. **D8. Every level counts.** Clinic but not physician, school but not classroom → `no`. This is a
   common failure — check each level explicitly.

## Restricted randomization

9. **D9. Present if** clusters were pair-matched, matched into sets, stratified, block-randomized,
   minimized, or constrained on covariates. Read the randomization paragraph, not the analysis one.
10. **D10. Accounting for it** means the pair or stratum enters as a random effect or blocking
    factor, or the analysis is of within-pair differences, or the working correlation reflects the
    matched sets, or the stratification variables are adjusted for.
11. **D11. Clustering handled, restriction ignored, is `no`.** A common pattern. Both sources of
    correlation, or neither.
12. **D12. Restriction handled while clustering ignored is essentially never real.** If you reach
    that conclusion, re-read.

### Evidence anchors for D5-D10

- **Fixed versus random (D7):** `fixed effects for physician and time` is not a
  random physician effect. Do not relabel a fixed effect as random.
- **Nested levels (D8):** List the randomization, delivery/provider, and
  participant levels stated in the paper. Verify the analysis accounts for each
  level that induces correlation. A hospital-level robust SE alone does not
  establish that clinician-level correlation was handled.
- **Restriction adjustment (D10):** An adjustment counts only when the primary
  outcome model contains the same matching or stratification variable, or the
  matched set itself. Do not substitute a random effect for the cluster, a
  different covariate, balanced arms, or a generic statement that the model was
  adjusted.

## What must not count

13. **D13. Only clustering and restricted randomization decide this.** If both are handled, answer
    `yes` however flawed the rest is. Not grounds for `no`: GEE without small-sample bias correction
    (corrected and uncorrected are treated identically), **longitudinality — repeated measures on
    the same subjects, compound symmetry, an assumed-exchangeable working correlation over time**,
    the wrong link function, no multiplicity adjustment, missing-data handling, adjusted vs
    unadjusted, unequal cluster sizes, ITT vs per-protocol, no reported ICC.
14. **D14. Longitudinality does not count.** A paper that handles clustering and restriction but
    ignores that its outcomes repeat over time is **`yes`**.

## Abstention

15. **D15.** `undecidable` only when the methods and results text is unreadable. Never for a hard
    call, never for a vague description — that is D4.
