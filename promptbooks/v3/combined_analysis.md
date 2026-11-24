**Objective.** You are reviewing one cluster-randomized trial that has already passed screening.
You do three things, in this order: **(A)** record the study design, **(B)** judge the power
analysis, **(C)** judge the data analysis.

**Your reading conditions.** You are in a sealed room. You have **no tools** — no file access, no
web, no search, no memory of any other paper. Everything you may use is in this one message. You get
**one turn**: no follow-up question, no clarification, no second pass. You cannot see an answer key,
another paper's text, or any judgment made before this one.

**How the parts relate.** Part A records facts. Parts B and C both read Part A, but are otherwise
independent: apply only the P rules in Part B and only the D rules in Part C. Neither judgment may
cite or depend on the other's conclusion.

**Missing information has three values.** Never write 0, `no`, or a blank for something the paper
does not tell you.

| value | meaning |
|---|---|
| `not_reported` | you checked and the paper does not say |
| `unclear` | the paper says something contradictory or unreadable |
| `null` | does not apply — only where a field below says so |

**Lists are starting points.** Every list below is incomplete. If nothing fits, write
`other: <short label>` in the paper's own words (60 characters maximum). Do not force a near miss
into a listed value. Listed values are lowercase and spelled exactly as shown.

**Units** (lowercase, singular): `patient`, `participant`, `student`, `clinic`, `school`,
`classroom`, `practice`, `hospital`, `ward`, `physician`, `nursing_home`, `village`, `community`,
`household`, `family`, `worksite`, `site`, `matched_pair`, `stratum`.

---

## Part A — Study design

Record the design of the primary-outcome comparison.

- **`n_trt`** — number of arms randomized. A 2×2 factorial is 4.
- **`levels`** — every level of nesting, **innermost first** (the person measured), outermost
  last. `patient within physician within clinic` is `[patient, physician, clinic]`. When clusters
  were randomized within matched pairs or strata, add `matched_pair` or `stratum` as the outermost
  level. Each level has a `unit` and a `count`.
- **`count`** — how many units at that level, in total across arms:
  - `kind`: `exact` · `approximate` (the paper says "about") · `range` · `not_reported` · `unclear`
  - `value` for exact/approximate; `low` and `high` for a range; otherwise `null`.
  - `per`: when the paper gives the count per parent unit ("about 20 patients per clinic"), name
    that outer unit here; otherwise `null`.
- **`unit_rand`** — the unit assigned to arms. One of your `levels` units.
- **`ind_samp_unit`** — the independent sampling unit: the units that are independent of one
  another. It is `unit_rand` (clinics in a simple trial), or the pair or stratum the randomization
  unit was randomized within. **If it is `matched_pair` or `stratum`, that same unit must also be
  the last entry in `levels`**, e.g. `levels: [patient, clinic, stratum]`, `ind_samp_unit: stratum`.
  An `ind_samp_unit` missing from `levels` is rejected.
- **`correlated_units`** — every level above the person whose members share correlated outcomes
  and must be accounted for: the randomization unit and any provider or delivery unit (a
  physician, a ward). Never `matched_pair` or `stratum`; restriction is recorded below.
- **`restricted_randomization`**:
  - `status`: `restricted` · `none` (the paper says simple/unrestricted, or describes no
    restriction) · `not_reported` · `unclear`
  - `schemes` (only when restricted): `pair_matched`, `matched_sets`, `stratified`, `blocked`,
    `constrained`, `minimization`. Otherwise `[]`.
  - `variables`: what it was restricted on, e.g. `clinic size and region`; `null` if not restricted.
- **`icc`** — the intraclass correlation(s) the paper reports, assumed or observed:
  - `status`: `reported` · `not_reported` · `unclear`
  - `values`: each `{kind: exact | range, value | low+high, applies_to}`. `applies_to` names the
    level or group (e.g. `clinic`); it is required when there are several. `[]` if not reported.
- **`longitudinal`** — when the primary outcome is measured. Two facts, not a total:
  - `baseline_measured`: `yes` if the primary outcome itself was measured before the
    intervention began, on the same people or on a fresh sample from the same clusters · `no` ·
    `not_reported` · `unclear`. Baseline demographics or other variables do not count.
  - `n_followup`: how many times the primary outcome is measured after the intervention began,
    counting every scheduled occasion the paper reports, not only the primary time point.
    Baseline, 6 and 12 months is `baseline_measured: yes`, `n_followup: 2`. A whole number, at
    least 1, or `not_reported` / `unclear`.
- **`stepped_wedge`** — `yes` · `no` · `unclear` · `not_reported`.

**Longitudinality** — how the two `done` records judge repeated measurement of the primary outcome:

- One follow-up and no baseline: `not_applicable`.
- Two or more follow-ups: `accounted` (the within-person or within-unit correlation over time is
  modeled) or `ignored`. Never `not_applicable`.
- Baseline plus one follow-up: `accounted` if baseline enters as a covariate, a change score, or a
  repeated measure with its correlation modeled; `ignored` if baseline and follow-up are pooled as
  independent observations; `not_applicable` if only the follow-up is used.

---

## Part B — Power analysis

You decide whether the power analysis correctly accounted for clustering, and for restricted
randomization if present. First record what a correct one needs (`should`), then what it did
(`done`), then judge it.

**`should`** — what a correct sample-size calculation for this design must account for, from
Part A alone, before you look at what the paper did:

- `units`: every level whose correlation it must account for (from `levels`); `[]` if none
- `restricted_rand`: `true` if the restricted randomization must be accounted for, else `false`
- `longitudinality`: `true` if the primary outcome is measured more than once, baseline
  included, so the repeated measurements must be accounted for; else `false`

**`done`** — what the sample-size calculation accounted for. If there is no power or sample-size
calculation, `reported` is `no` and every other field is `null` (`units_accounted` is `[]`).

- `reported`: `yes` · `no`
- `clustering`: `all_levels` (every `correlated_units` level) · `some_levels` · `ignored` · `unclear`
- `units_accounted`: the levels it accounted for (from `levels`); `[]` if ignored
- `restricted_rand`: `accounted` · `ignored` · `not_applicable` (design not restricted) · `unclear`
- `longitudinality`: `accounted` · `ignored` · `not_applicable` (see **Longitudinality**, Part A)
- `method`: `formula` · `simulation` · `not_described`
- `source_note`: a cited method or tool, e.g. `Donner & Klar`; `null` if none
- `timing`: `before_trial` · `post_hoc` · `not_stated`

**Criteria.** Test the numbered criteria below in order. `yes` = correct, `no` = incorrect. The
first one that matches decides; cite the deciding number in `promptbook_evidence`.

### Scope

1. **P1. Primary outcomes only** — the sample-size justification for the treatment effect on the
   primary outcome(s). Ignore secondary outcomes, subgroups, safety endpoints.
2. **P2. This manuscript only** — use its text and supplement, not a protocol, registry, or prior
   report. “See our protocol paper” is `no`, not `undecidable`.
3. **P3. Correct requires all three, stated in this manuscript:** the approach is ascertainable
   (P4-P6); clustering is accounted for at every level (P7-P9); restricted randomization, if
   present, is too (P10-P13). Before answering `yes`, identify text supporting the effect/approach,
   cluster count, and ICC/design effect (or equivalent); do not infer a missing element from
   balanced arms or a cited method.

### Clarity and presence

4. **P4. Unclear is incorrect** — a sample size with no account of what produced it.
5. **P5. Naming a tool is not a description.** GLIMMPSE, PASS, Donner & Klar: cited alone, not
   enough. Need at minimum an ICC or design effect, an effect size, and a cluster count.
6. **P6. Absent is `no`, not `undecidable`.**

### Clustering

7. **P7. Accounting for clustering** means using a cluster-structure quantity and answering in
   clusters: an ICC; a design effect `1 + (m-1)p`; a coefficient of variation of cluster means; an
   explicit between-cluster variance; a simulation with within-cluster correlation.
8. **P8. Ignoring clustering** is an individual-level calculation — "n = 300 gives 80% power to
   detect d = 0.35" — with no ICC, design effect, or cluster count.
9. **P9. Every level counts.** Patients within physicians within clinics: all of them, or `no`.
   This is a common failure — check each level explicitly.

### Restricted randomization

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

### What must not count

16. **P16. Only clustering and restricted randomization decide this.** If both are handled, answer
    `yes`. Do not count effect-size or ICC plausibility, attrition, longitudinality, test choice,
    alpha, multiplicity, unequal cluster sizes, or target power.
17. **P17. Longitudinality does not count.** A power analysis that handles clustering and
    restriction but assumes one measurement per subject is **`yes`**.

### Abstention

18. **P18.** `undecidable` only when the methods text is unreadable.

---

## Part C — Data analysis

You decide whether the data analysis correctly accounted for clustering, and for restricted
randomization if present. First record what a correct one needs (`should`), then what it did
(`done`, `comment`), then judge it.

**`should`** — what a correct primary analysis for this design must account for, from Part A
alone, before you look at what the paper did. Same three fields as Part B: `units`,
`restricted_rand`, `longitudinality`.

**`done`** — the **one** main analysis of the primary outcome. If the paper describes no analysis
method, `method` is `not_reported` and every other field is `null` (`levels_modeled` is `[]`).

- `method`: `mixed_effects` · `gee` · `cluster_level` (analysis of cluster summaries) ·
  `cluster_robust_se` · `permutation` · `bayesian_hierarchical` · `cluster_fixed_effects` ·
  `individual_level` (nothing above the person) · `not_reported`
- `planned_only`: `true` when the paper describes a planned analysis and reports no results from it
- `levels_modeled`: the levels whose correlation the analysis accounts for; `[]` if none
- `clustering`: `all_levels` (every `correlated_units` level) · `some_levels` · `ignored` · `unclear`
- `restricted_rand`: `accounted` · `ignored` · `not_applicable` (design not restricted) · `unclear`
- `longitudinality`: `accounted` · `ignored` · `not_applicable` (see **Longitudinality**, Part A)
- `small_sample_correction`: `yes` · `no` · `unclear` — a bias-corrected sandwich estimator,
  Kenward-Roger, Satterthwaite, or a between-within df adjustment

**`comment`** — `tags` (any that apply, or `[]`) and a short `note` (200 characters maximum, or
`null`):

- `unclear_reporting` — the analysis is hard to pin down from the text
- `missing_method` — no analysis method is described for the primary outcome
- `wrong_level` — the analysis accounts for a level other than the one that needed it
- `restriction_ignored` — restricted randomization not reflected in the analysis
- `longitudinality_ignored` — repeated measures not reflected in the analysis
- `label_inconsistency` — the paper describes the design or analysis inconsistently

**Criteria.** Test the numbered criteria below in order. `yes` = correct, `no` = incorrect. The
first one that matches decides; cite the deciding number in `promptbook_evidence`.

### Scope

1. **D1. Primary outcomes only** — analyses estimating or testing the treatment effect on the
   primary outcome(s). Ignore secondary outcomes, subgroups, baseline tables.
2. **D2. Conjunctive — every one must be correct.** All reported primary-outcome analyses must pass
   D5-D12, including sensitivity, per-protocol, and unadjusted re-analyses; one failure decides the
   paper. *Anchor:* a correct mixed model followed by t-tests at the end is `no`.
3. **D3. This manuscript only** — use its text and supplement, not a protocol, registry, or prior
   report. Pointing to one for the analysis is `no`.
4. **D4. Absent or undescribed is `no`** — including "outcomes were compared between arms." A
   planned analysis this manuscript describes is judged like a performed one.

### Clustering

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

### Restricted randomization

9. **D9. Present if** clusters were pair-matched, matched into sets, stratified, block-randomized,
   minimized, or constrained on covariates. Read the randomization paragraph, not the analysis one.
10. **D10. Accounting for it** means the primary model contains the matched set or the same
    matching/stratification variable, a blocking/random effect, within-pair differences, or a
    working correlation reflecting matched sets. A cluster random effect, different covariate,
    balanced arms, or generic adjustment is not enough.
11. **D11. Clustering handled but restriction ignored is `no`.**
12. **D12. Restriction handled while clustering is ignored is `no`.**

### What must not count

13. **D13. Only clustering and restricted randomization decide this.** If both are handled, answer
    `yes`. Do not count GEE small-sample correction, longitudinality, link choice, multiplicity,
    missing-data handling, adjustment, cluster size, ITT/per-protocol, or reported ICC.
14. **D14. Longitudinality does not count.** A paper that handles clustering and restriction but
    ignores that its outcomes repeat over time is **`yes`**.

### Abstention

15. **D15.** `undecidable` only when the methods and results text is unreadable.

---

## Answer format

Return **one JSON object** with exactly these keys, in this order. Every key is required; an
extra or missing key is rejected.

```
{
  "design": {
    "n_trt": 2,
    "levels": [{"unit": "...", "count": {"kind": "...", "value": null, "low": null, "high": null, "per": null}}, ...],
    "unit_rand": "...", "ind_samp_unit": "...", "correlated_units": ["..."],
    "restricted_randomization": {"status": "...", "schemes": [], "variables": null},
    "icc": {"status": "...", "values": [{"kind": "...", "value": null, "low": null, "high": null, "applies_to": null}]},
    "longitudinal": {"baseline_measured": "...", "n_followup": 1}, "stepped_wedge": "..."
  },
  "power_analysis": {
    "decision": "yes | no | undecidable", "reasoning": "...", "promptbook_evidence": "P..", "confidence": 0.0,
    "should": {"units": ["..."], "restricted_rand": false, "longitudinality": false},
    "done": {"reported": "...", "clustering": "...", "units_accounted": [], "restricted_rand": "...",
             "longitudinality": "...", "method": "...", "source_note": null, "timing": "..."}
  },
  "data_analysis": {
    "decision": "yes | no | undecidable", "reasoning": "...", "promptbook_evidence": "D..", "confidence": 0.0,
    "should": {"units": ["..."], "restricted_rand": false, "longitudinality": false},
    "done": {"method": "...", "planned_only": false, "levels_modeled": [], "clustering": "...",
             "restricted_rand": "...", "longitudinality": "...", "small_sample_correction": "..."},
    "comment": {"tags": [], "note": null}
  }
}
```

- `reasoning`: why, in your own words. **200 characters maximum** each.
- `promptbook_evidence`: the deciding criterion number — P rules for power, D rules for data.
- `confidence`: your real confidence in that judgment for this paper, 0.0-1.0.
- Numbers are JSON numbers (`20`, not `"20"`). `true`/`false`/`null` are bare.

**Your answer is checked for consistency, and an inconsistent answer is rejected.** In particular:
a `yes` needs `clustering: all_levels` and `restricted_rand` of `accounted` or `not_applicable`;
`all_levels` means every `correlated_units` level is listed; `restricted_rand` is
`not_applicable` when the design's restriction status is `none` or `not_reported`, and never when
it is `restricted`; `longitudinality` is `not_applicable` with one follow-up and no baseline, and
never with two or more follow-ups; a data `yes` cannot use `individual_level` or `cluster_fixed_effects`.

`undecidable` is an abstention for genuinely unreadable text, **not** for a hard call. A difficult
paper still gets a `yes` or a `no`.
