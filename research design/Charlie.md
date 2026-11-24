# Questions for Charlie

<!-- Open questions only. When one is answered, record the answer where it belongs (plan, v2 doc,
Design_Choices.md) and delete it here. Questions for Deb and Keith live in Deb.md. -->

Last updated 2026-11-24. None of these block the v2 smoke test. Until they are answered, the
affected cells are reported as "not scored", never as wrong.

## 1. Unit names in `data/unit_synonyms.csv`

**What's going on:** The model must name units (the thing a person is grouped inside) from a fixed
list: patient, participant, student, clinic, school, classroom, practice, hospital, ward, physician,
nursing_home, village, community, household, family, worksite, site, matched_pair, stratum.
The human reviewers wrote freely and used 71 other words, like "PCP", "church", or "child".

When the human wrote "PCP" and the model wrote "physician", the scorer can't tell they mean the
same thing unless this file says so. So right now those cells are not scored.

**What to do:** Open the file. Each row is one human word.

- **25 rows have a suggested match** in the `unit` column (e.g. `PCP → physician`,
  `child → participant`). If the match is right, change `checked` to `yes`. If it's wrong, fix
  `unit` and then set `checked` to `yes`.
- **46 rows have no match** (e.g. `church`, `city`, `agency`). If a listed unit fits, type it in
  `unit` and set `checked` to `yes`. If none fits, leave `unit` blank and set `checked` to `yes`.
  The model then has to use the same word (as `other: church`) to match.

Only rows marked `yes` are used.

## 2. Turning the human power/data notes into answers we can score

**What's going on:** Three human columns are short notes, not fixed answers, so the scorer can't
compare them with the model yet. Examples from `data/ground_truth.csv`:

| Column | Example human notes | How many |
|---|---|---|
| `power_done` | "Accounted for clustering alone", "Accounted for clustering but not longitudinality" | 88 |
| `data_done` | "GEE with bias correction", "linear model accounting for clustering" | 88 |
| `data_comment` | "needed bias correction. Big design effect.", "didn't account for repeated measures" | 59 |

The model answers these in fixed parts. For `power_done` the parts are: was a power analysis
reported, was clustering handled, was restricted randomization handled, was repeated measurement
handled, method (formula/simulation), and timing. For example, "Accounted for clustering but not
longitudinality" would become: clustering = handled, repeated measurement = not handled, the rest
blank (not mentioned).

**Question a.** Who turns the 235 notes into those parts: you, Deb, or two people who then compare?

**Question b.** Which parts should be filled in?

- All the parts the model answers, leaving blank anything the note doesn't mention.
- Only the one or two parts most notes mention (e.g. clustering and repeated measurement).
- Skip it, and don't score these three columns in this project.

## 3. When the model uses a unit word that isn't on the list

**What's going on:** In the first v2 smoke test (2026-11-24), paper `6XFGQN39` was grouped as
"patients within clinicians within practices". The model wrote `clinician`. The list only has
`physician`, and the rule says any other word must be written `other: clinician`. The model left
off `other: `, so the whole reply was rejected (8 errors, all this one word). Nothing from that
paper was saved.

**Question:** If this keeps happening, which fix?

- **Retry and wait (current).** A rejected reply is asked again, up to 3 tries, then marked for
  human review. Costs a little per retry, and the model may repeat the mistake.
- **Accept a bare word as `other: <word>`.** The checker treats `clinician` as if it said
  `other: clinician`. The prompt doesn't change, so no v3 is needed. The word is then matched
  through `data/unit_synonyms.csv` (question 1), where `clinician → physician` is already
  suggested.
- **Fix the prompt wording in v3.**

Suggested: retry for now and count how often it happens in the first 50-paper round, then decide.
One paper isn't a pattern. (On the retry, the model wrote `physician`, so it didn't repeat.)
