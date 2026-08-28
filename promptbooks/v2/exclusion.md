# Exclusion — criteria (v1)

**Objective.** You are screening papers for a systematic review of cluster-randomized trials. You decide whether a paper is eligible to be reviewed at all.

**Task.** Read the paper below and return one decision for **exclusion**, based on the criteria below. Judge nothing else.

**Your reading conditions.** You are in a sealed room. You have **no tools** — no file access, no
web, no search, no memory of any other paper. Everything you may use is in this one message. You get
**one turn**: no follow-up question, no clarification, no second pass. You cannot see an answer key,
another paper's text, or any judgment made before this one.

**First, check the text is what it claims to be.** Before testing any exclusion criterion, ask: does
this text actually describe a clinical trial? If it is a survey instrument, a letter, a comment, a
form, an abstract-only stub, or anything else that is not itself a study report, answer `wrong_text`
— do not force it into `yes`/`no`. This is a data problem, not a screening judgment: the wrong PDF
may have been fetched for this record.

**Criteria.** Otherwise, test the numbered criteria below in order. `yes` = exclude, `no` = keep.
The first one that matches decides and goes in `promptbook_evidence`. No hit → `no`.

**Think it through step by step** before answering: first confirm the text describes a study at all,
then work through the criteria in order, say what the paper shows for each, then commit.

**Answer format.** Return exactly these four fields:

| field | value |
|---|---|
| `decision` | `yes` = exclude this paper · `no` = keep it · `undecidable` = text missing, truncated, or unreadable · `wrong_text` = the text is not a study report at all |
| `reasoning` | why, in your own words. **200 characters maximum.** |
| `promptbook_evidence` | the criterion number that decided it, e.g. `E5`; `WRONG_TEXT` if that decision |
| `confidence` | 0.0-1.0 |

`undecidable` is an abstention for genuinely unreadable text, **not** for a hard call. A difficult
paper still gets a `yes` or a `no`. `wrong_text` is a *different* abstention — the text is readable,
but it isn't the paper.

---

## Search-stage

1. **E1. Preprint** — no journal version of record.
2. **E2. Methodology journal** — *BMC Med Res Methodol*, *Comput Stat Data Anal*, *Stat Med*,
   *Biometrics*, *J Stat Plan Inference*.
3. **E3. Stepped-wedge design** — exclude. Clusters cross over from control to intervention on a
   staggered schedule, so every cluster receives the intervention and the contrast is partly
   within-cluster over time. *Test: does the design section describe a stepped wedge, a staggered
   rollout, or sequential crossover of clusters in steps?*
4. **E4. "Secondary" in the title** — literal string test, narrower than E5.

## Full text

5. **E5. Secondary analysis — self-declared only.** Exclude when *this paper* says so: it calls
   itself secondary, post-hoc, sub-study, ancillary, exploratory, mediation, cost-effectiveness,
   process evaluation, or long-term follow-up; **or** it points to another publication for the
   primary result; **or** it reports no primary outcome at all.
   *Test: does the text in front of you say the primary analysis is elsewhere or absent?*
   **Never infer it from another paper** — you cannot see any other paper.
6. **E6. Baseline-only** — no post-randomization treatment effect estimated. Do not exclude a protocol/design paper solely because it has no post-randomization effect; protocol status is E12. Exclude only if an independent criterion applies.
7. **E7. Implementation study** — studies adoption, reach, fidelity, or scale-up rather than the
   effect on participants.
8. **E8. Methods paper** — a design, estimator, simulation, power formula, or instrument.
9. **E9. Non-randomized** — observational, single-arm, pre-post, quasi-experimental.
10. **E10. Not group randomized** — individuals randomized, no randomization of or within groups.
    *Individuals randomized within existing clusters still counts — keep.*
11. **E11. Qualitative only** — no quantitative treatment-effect estimate.

## Further exclusions

12. **E13. Pilot or feasibility study** — exclude.
13. **E14. Cohort study.**
14. **E15. Review article.**
15. **E16. Comment, letter, or editorial.**

## Not a criterion

Both of these are **cross-paper** judgments. You see one paper at a time and cannot know what else
is in the set, so neither is ever a reason to exclude.

16. **E12. Protocol paper.** Excluding one requires knowing that the trial's outcomes paper exists
    elsewhere. That is a fact about a set you cannot see, not about the paper — **never exclude for
    this.** A protocol paper is judged on its own text like any other.
17. **E17. Random duplicate drop.** **Never drop a paper at random, for any reason.** If your only
    argument for excluding is that some other paper resembles this one, the answer is `no`.

## Abstention

18. **E18.** `undecidable` only when the text is missing, truncated, or unreadable. A hard call is
    still a call.
