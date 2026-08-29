# Data analysis — criteria (v2)

**Objective.** You are reviewing a cluster-randomized trial that has already passed screening. You decide whether its data analysis correctly accounted for clustering, and for restricted randomization if present.

**Task.** Read the paper below and return one decision for whether the **data analysis** was correct, based on the criteria below. Judge nothing else.

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
3. **D3. This manuscript only** — use its text and supplement, not a protocol, registry, or prior
   report. Pointing to one for the analysis is `no`.
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
7. **D7. A fixed effect for the cluster does not count.** It shifts means but does not model
   correlation; `fixed effects for physician and time` is not a random physician effect.
8. **D8. Every correlation-inducing level counts.** List the randomization, provider/delivery, and
   participant levels stated in the paper; clinic but not physician is `no`. Hospital-level robust
   SEs alone do not establish clinician-level correlation was handled.

## Restricted randomization

9. **D9. Present if** clusters were pair-matched, matched into sets, stratified, block-randomized,
   minimized, or constrained on covariates. Read the randomization paragraph, not the analysis one.
10. **D10. Accounting for it** means the primary model contains the matched set or the same
    matching/stratification variable, a blocking/random effect, within-pair differences, or a
    working correlation reflecting matched sets. A cluster random effect, different covariate,
    balanced arms, or generic adjustment is not enough.
11. **D11. Clustering handled but restriction ignored is `no`.**
12. **D12. Restriction handled while clustering is ignored is `no`.**

## What must not count

13. **D13. Only clustering and restricted randomization decide this.** If both are handled, answer
    `yes`. Do not count GEE small-sample correction, longitudinality, link choice, multiplicity,
    missing-data handling, adjustment, cluster size, ITT/per-protocol, or reported ICC.
14. **D14. Longitudinality does not count.** A paper that handles clustering and restriction but
    ignores that its outcomes repeat over time is **`yes`**.

## Abstention

15. **D15.** `undecidable` only when the methods and results text is unreadable.
