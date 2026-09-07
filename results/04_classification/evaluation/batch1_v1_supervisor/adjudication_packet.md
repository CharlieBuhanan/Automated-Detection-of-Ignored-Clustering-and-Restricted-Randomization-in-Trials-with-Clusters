# Decisions needed before the next v2 build evaluation

Good evening,

Before I run the next v2 build evaluation, I need your decisions on the points below. In batch 1, the data-analysis rubric correctly identified only 2 of the 7 papers labelled correct (overall accuracy was 79.2%, 38/48). Some of the ten disagreements appear to be model errors, while others might reflect inconsistent or under-specified labels. If we continue without resolving them, the next rubric will remain inaccurate.

I used Codex Sol to audit the discrepancies because I am not experienced with the statistical details to resolve them myself, so I hope the questions still make sense and are clear & relevant. If one of the questions isn't clear or relevant feel free ignore it and let me know. I understand there's a lot of papers listed so the review might take some time and some papers may remain unresolved. Let me know if I can help or clarify anything. The IDs below (for example, DCYTWR4N) are Zotero item IDs and can be pasted into Zotero's Quick Search bar.

## Questions from the LLM

### Core methodological questions

#### Restricted randomization

For this question, **blocking** means assigning clusters within predefined groups (blocks), or using an allocation scheme that constrains the number assigned to each arm, rather than making one unrestricted random draw. **Minimization** means assigning each new cluster to the arm that best preserves balance across selected baseline characteristics, usually with a random component.

When a trial used stratification, pair matching, blocking, minimization, or constrained randomization, what must the primary analysis include to be correct? Must it include the matched set/block or every matching/stratification variable, and is partial or alternative adjustment ever sufficient? For power, must the sample-size calculation also represent the correlation induced by the restriction, or is an otherwise adequate clustering adjustment sufficient?

#### Nested clustering

Apart from longitudinal repeated measures, which you previously said not to count, must the analysis account only for the randomization unit or for every provider/delivery level with residual correlation? Please apply this to Mann 2020 (DCYTWR4N), Goldstein 2019 (LU33978L), and Cox 2024 (TEXLFQSL). For Cox, the full text appears to describe a clinician random effect and centered stratification variables, while the source note says fixed effects and missed levels; please confirm which primary analysis controls the label. Please also confirm Goldstein's power label, because its calculation accounted for the hospital but not the clinician level.

#### Protocols and baseline/design reports

We will continue to keep these papers eligible, per an earlier decision. Can a paper that reports only a planned future analysis nevertheless receive data_correct=yes, or must a treatment-effect analysis have actually been performed and reported? Please apply this to Arrossi 2019 (B3KTU9TU) and Brewer 2022 (FHVQQIX3). For Arrossi, please also confirm whether the power calculation needed to account for its gender and urban/rural strata.

#### Source-field interpretation

Are data_should and power_should columns exhaustive descriptions of what the reviewers required, or are they shorthand? In particular, if restricted_rand=yes but a *_should field omits the restriction, should we still assume that the restriction had to be addressed? This determines whether those fields can be used to audit the binary labels.

### Specific record reviews

#### Five NCI/NHLBI disagreements

Please give the final eligible/exclude decision and exclusion reason, if applicable, for Bartels 2024 (VGG3KIMT: baseline-only vs keep), Beck 2019 (RJD9XX6D: power/data yes vs no), Gilbert 2022 (Z7NF2G6Q: baseline-only vs implementation study), Ockene 2021 (HLQA5RI6: secondary analysis vs keep), and Smith 2023 (E92KWK4B: implementation vs methods paper). For every paper kept, please also provide final power- and data-analysis labels.

#### Cattamanchi 2021 (XHFTHUCG)

You previously identified its data_correct=yes label as wrong because its analysis handled clinic clustering but not its stratified randomization. Please confirm the final corrected data label; the paper is currently removed from scoring pending this review.

#### Seven restricted-randomization records

Douin 2025 (7NYXSVAI), Fortmann 2021 (W2VQEXEG), Kinnamon 2023 (XEIAGV9H), Green 2018 (5VWZPNEQ), Grissom 2023 (QUEFXEQY), Hanrahan 2023 (WUNIU4CC), and Olomu 2022 (4TRC3UDD) all have restricted_rand=yes, but neither their data nor power should field asks for the restriction. Please confirm the final power and data labels for each, especially the currently positive labels for Douin, Fortmann, and Kinnamon. Fortmann's existing comment already says Keith did not think its data analysis was correct. Douin also appears in the stepped-wedge group below.

#### Five analysed stepped-wedge papers

Bernabe-Ortiz 2020 (3JVAWNIE), Ciccone (TT7PIVLD), Douin 2025 (7NYXSVAI), Courtright (QMLU4TM8), and Fiscella (8H9BUEWH) were labelled eligible even though nine other stepped-wedge papers were excluded. You have since ruled that E3 excludes stepped-wedge trials, but these five records were not individually re-read. Please confirm whether each meets E3 and should be excluded. If any should remain eligible, please also confirm its power and data labels. These papers are currently removed from scoring pending this review.

### Additional batch-1 questions

Codex Sol came up with 10 additional papers from the first batch that it was interested in clarifying, below are the listed requests.

#### Five additional batch-1 data conflicts

Please give a final data label for Gans 2018 (SGCHKJTH: labelled yes; no matched-pair term found), Vidrine 2019 (2RDD8DGI: labelled yes; only one of two stratification factors found in the model), Bryant-Stephens 2024 (IPR6QU8P: labelled yes; the full text appears to contain clinic/school stratification not recorded in the source row), Cooper 2024 (84YU8UCD: labelled no; the full text appears to account for practice clustering and the health-system stratum), and Adams 2019 (D24FD6G2: labelled no; the full text appears to specify physician-level GEE clustering with robust standard errors). Vidrine, Bryant-Stephens, and Adams also have disputed power labels, so please confirm those as well.


#### Five remaining batch-1 power conflicts

Please give a final power label for Snavely 2023 (9DKJKFAS: labelled yes; matching not found in the calculation), Pacyna 2018 (BAABE7JM: labelled no; clustering handled, but allocation was blocked), Thankappan 2020 (WY9D5UIK: labelled no; the paper appears to use a design effect and six clusters with simple 3-vs-3 allocation), Pfammatter 2020 (LGEECHQM: labelled no; the paper cites a paired-cluster formula), and Halterman 2022 (7M6ST2JQ: labelled no; the paper appears to randomize individuals within school strata rather than schools). These checks will also clarify what evidence is sufficient within the manuscript rather than inferred from a citation or balanced arms.

## Requested response format

For each paper, a final decision and a very brief (~1 sentence) rationale would be incredibly helpful to the model's accuracy. I will retain the original labels and record adjudications separately instead of overwriting any data.

## Review materials in Dropbox

The promptbook and review summaries are in the shared Dropbox under `Boring Task/`:

- `Review Summaries and Promptbooks/Batch1 Version1 Promptbook/` contains the v1 promptbook used for this batch: the exclusion, power-analysis, and data-analysis criteria given to the model.
- `Review Summaries and Promptbooks/review_tables/` contains the HTML review summaries. Each page compares the human label with the model's decision and shows the model's confidence, rationale, and cited promptbook rule for each paper. Please open the `.html` files in a web browser.

There are two power-analysis HTML pages because an earlier incomplete export was retained for audit. Please use `power_analysis_v1_r1_review_table.html`: it is the complete v1 report with all 49 judgments and recorded run provenance. The similarly named `power_analysis_r1_review_table.html` is the earlier legacy export; it contains only 37 scored judgments and does not record which promptbook or run environment produced them.

### Full-text PDFs

In the Dropbox, under `Literature/`:

- The five institutional-disagreement full text PDFs are in `data/removed_pdfs/institutional_disagreements/`.
- Cattamanchi and the five stepped-wedge PDFs are in `data/removed_pdfs/expert_review/`.
- The other PDFs are in `data/raw_pdfs/Human Labelled Set/`.

Thank you for the help,

Charlie Buhanan
