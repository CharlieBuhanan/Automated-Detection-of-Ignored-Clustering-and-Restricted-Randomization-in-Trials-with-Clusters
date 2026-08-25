# Exclusion Reasons: NCI vs. NHLBI

NCI: 136 excluded, 8 reasons. NHLBI: 225 excluded, 13 reasons (7 don't exist in NCI's protocol).

## NCI (8)

| reason | n |
|---|---|
| secondary_analysis | 70 |
| implementation_study | 19 |
| duplicate_group_random_drop | 15 |
| baseline_only | 14 |
| not_group_randomized | 9 |
| methods_paper | 5 |
| qualitative_study | 2 |
| not_randomized | 2 |

## NHLBI (13)

| reason | n | maps to NCI? |
|---|---|---|
| secondary_analysis | 100 | yes |
| methods_paper | 27 | yes |
| duplicate_group_random_drop | 19 | yes |
| not_group_randomized | 14 | yes |
| implementation_study | 14 | yes |
| baseline_only | 12 | yes |
| pilot_study | 11 | **no** |
| protocol_paper | 9 | **no** |
| stepped_wedge_design | 9 | **no**† |
| cohort_study | 3 | **no**‡ |
| comment_or_letter | 3 | **no**‡ |
| preprint | 3 | **no**† |
| review_article | 3 | **no**‡ |

† already excluded by NCI's PubMed search string, not a reviewer judgment gap.
‡ relabel of an existing NCI reason (not_randomized / methods_paper) — same judgment, new name.

## Discuss with Deb

**`protocol_paper` (9) and `pilot_study` (11)** — genuinely new criteria, no NCI counterpart. These skew the headline power/data-analysis-correctness rate because both types rarely report a proper power analysis, so excluding them removes likely "incorrect" cases from NHLBI's denominator. Need a decision: adopt for both arms, or drop from NHLBI to match NCI.