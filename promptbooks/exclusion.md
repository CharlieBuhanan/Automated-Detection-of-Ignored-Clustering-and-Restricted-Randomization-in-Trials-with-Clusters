# Exclusion — criteria (v0)

Criteria only. Source: Glueck & Muller (`Ignore02.pdf`), Methods p.3 and Supplemental A.

`yes` = exclude, `no` = keep. Test E1-E16 in order; first hit decides and goes in
`promptbook_evidence`. No hit → `no`.

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

5. **E5. Secondary analysis** — the trial's primary results are in another publication. Covers
   post-hoc, sub-study, mediation, cost-effectiveness, process evaluation, long-term follow-up.
   *Test: would a reader need another paper to find the primary result?*
6. **E6. Baseline-only** — no post-randomization treatment effect estimated.
7. **E7. Implementation study** — studies adoption, reach, fidelity, or scale-up rather than the
   effect on participants.
8. **E8. Methods paper** — a design, estimator, simulation, power formula, or instrument.
9. **E9. Non-randomized** — observational, single-arm, pre-post, quasi-experimental.
10. **E10. Not group randomized** — individuals randomized, no randomization of or within groups.
    *Individuals randomized within existing clusters still counts — keep.*
11. **E11. Qualitative only** — no quantitative treatment-effect estimate.

## NHLBI additions

12. **E12. Protocol paper** — *CONTESTED, default ON.* Ignore02 would keep these and score data
    analysis incorrect under D4.
13. **E13. Pilot or feasibility study** — *CONTESTED, default ON.* Ignore02 would keep these.
14. **E14. Cohort study** — E9/E10 renamed.
15. **E15. Review article** — E8 renamed.
16. **E16. Comment, letter, or editorial.**

## Not a criterion

17. **E17. Random duplicate drop.** Ignore02 used `randuni` to keep one of several same-first-author
    papers. A coin flip, unreproducible from text — **never exclude for this.** The 31 labelled rows
    leave the scored set instead of counting as misses.

## Abstention

18. **E18.** `undecidable` only when the text is missing, truncated, or unreadable. A hard call is
    still a call.

## Contested — see [Deb.md](../research%20design/Deb.md)

- **E3** cuts both ways: NHLBI excluded 9 stepped-wedge papers but kept and fully scored 5 others.
  On costs 5 unrecoverable false exclusions to gain 9 correct ones.
- **E12/E13** are the only genuinely new NHLBI criteria, and both select for papers unlikely to
  report good power.
