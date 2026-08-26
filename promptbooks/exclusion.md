# Exclusion — criteria (v0)

Criteria only. Source: Glueck & Muller (`Ignore02.pdf`), Methods p.3 and Supplemental A.

`yes` = exclude, `no` = keep. Test E1-E16 in order; first hit decides and goes in
`promptbook_evidence`. No hit → `no`.

## Prompt

> Everything in this block is sent to the model verbatim, before the paper text.
> Structure follows ISO-ScreenPrompt (Cao et al. 2024): objective → numbered criteria →
> article → instructions repeated *after* the article. The repeat is not optional — Cao
> found instructions placed only before a full text get lost in long context.

**Objective.** You are screening papers for a systematic review of cluster-randomised trials. You decide whether a paper is eligible to be reviewed at all.

**Task.** Read the paper below and return one decision for **exclusion** only. Judge nothing else.
Judge only the manuscript in hand: you cannot see any other paper, and no other paper's existence
is ever a reason for your answer.

**Criteria.** Test the numbered criteria below in order. The first one that matches decides.

**Think it through step by step** before answering: work through the criteria in order, say what
the paper shows for each, then commit.

**Answer format.** Return exactly these four fields:

| field | value |
|---|---|
| `decision` | `yes` = exclude this paper · `no` = keep it · `undecidable` = text missing, truncated, or unreadable |
| `reasoning` | why, in your own words. **60 words maximum.** |
| `promptbook_evidence` | the criterion number that decided it, e.g. `E5` |
| `confidence` | 0.0-1.0 |

`undecidable` is an abstention for genuinely unreadable text, **not** for a hard call. A difficult
paper still gets a `yes` or a `no`.

---
## Search-stage

NCI's PubMed query removed these, so no NCI paper carries them; NHLBI's reviewers caught them by hand.

1. **E1. Preprint** — no journal version of record.
2. **E2. Methodology journal** — *BMC Med Res Methodol*, *Comput Stat Data Anal*, *Stat Med*,
   *Biometrics*, *J Stat Plan Inference*.
3. **E3. Stepped-wedge design** — *CONTESTED, default OFF.*
4. **E4. "Secondary" in the title** — literal string test, narrower than E5.

> The query's other term blocklist (`"estimates"`, `"two-group"`, `"formulae"`, and eleven more) is
> not reproduced. PubMed matched those against a citation record; against full text they would
> exclude nearly every trial. E8 covers the intent.

## Full text

The seven reasons Ignore02's reviewers recorded.

5. **E5. Secondary analysis — self-declared only.** Exclude when *this paper* says so: it calls
   itself secondary, post-hoc, sub-study, ancillary, exploratory, mediation, cost-effectiveness,
   process evaluation, or long-term follow-up; **or** it points to another publication for the
   primary result; **or** it reports no primary outcome at all.
   *Test: does the text in front of you say the primary analysis is elsewhere or absent?*
   **Never infer it from another paper in the corpus** — you cannot see the corpus.
6. **E6. Baseline-only** — no post-randomization treatment effect estimated.
7. **E7. Implementation study** — studies adoption, reach, fidelity, or scale-up rather than the
   effect on participants.
8. **E8. Methods paper** — a design, estimator, simulation, power formula, or instrument.
9. **E9. Non-randomized** — observational, single-arm, pre-post, quasi-experimental.
10. **E10. Not group randomized** — individuals randomized, no randomization of or within groups.
    *Individuals randomized within existing clusters still counts — keep.*
11. **E11. Qualitative only** — no quantitative treatment-effect estimate.

## NHLBI additions

12. **E13. Pilot or feasibility study** — exclude. Ignore02 is **silent** on pilots (not among its
    eight PRISMA reasons); this is an NHLBI addition. **Confirmed by Deb.**
13. **E14. Cohort study** — E9/E10 renamed.
14. **E15. Review article** — E8 renamed.
15. **E16. Comment, letter, or editorial.**

## Not a criterion

Both of these are **cross-paper** judgments. You see one paper at a time and cannot know what else
is in the set, so neither is ever a reason to exclude. Duplicate authors and superseded papers are
handled in post-hoc data cleaning, not here.

16. **E12. Protocol paper.** NHLBI excluded these because the trial's outcomes paper exists elsewhere
    in the set. That is a fact about the corpus, not the paper — **never exclude for this.** A
    protocol paper is judged on its own text like any other. (Ignore02 kept them and scored the data
    analysis incorrect under D4.)
17. **E17. Random duplicate drop.** Ignore02 used `randuni` to keep one of several same-first-author
    papers. A coin flip, unreproducible from text — **never exclude for this.**

The 41 labelled rows carrying these two reasons were removed from the scored set by
`scripts/10_drop_nonjudgeable_exclusions.py` rather than counted as misses.

## Abstention

18. **E18.** `undecidable` only when the text is missing, truncated, or unreadable. A hard call is
    still a call.

## Contested — see [Deb.md](../research%20design/Deb.md)

- **E3** cuts both ways: NHLBI excluded 9 stepped-wedge papers but kept and fully scored 5 others.
  On costs 5 unrecoverable false exclusions to gain 9 correct ones.
- **E12** was retired to *Not a criterion* above: excluding a protocol paper requires knowing its
  outcomes paper exists, which the model cannot see. **Confirmed by Deb**: the outcomes paper is
  instead marked incorrect if it cites the protocol for its power or data analysis — see P2/D3.
