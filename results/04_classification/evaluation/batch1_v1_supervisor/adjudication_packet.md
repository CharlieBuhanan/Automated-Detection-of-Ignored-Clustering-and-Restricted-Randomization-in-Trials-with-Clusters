**DRAFT — please read, edit, and confirm this email before sending it.**

Subject: Decisions needed before the next v2 build evaluation

Good evening Deb and Keith,

Before I run the next v2 build evaluation, I need your decisions on the points
below. In batch 1, the data-analysis rubric correctly identified only 2 of the
7 papers labelled correct (overall accuracy was 79.2%, 38/48). Some of the ten
disagreements appear to be model errors, while others may reflect inconsistent
or under-specified labels. If we continue without resolving them, the next
rubric may learn the wrong distinctions and remain inaccurate.

I used Codex to audit the discrepancies because I am not confident enough in
the statistical details to resolve them myself. The IDs below (for example,
`DCYTWR4N`) are Zotero item IDs and can be pasted into Zotero's Quick Search
bar.

Could you please answer the following?

Core methodological questions

1. **Restricted randomization:** When a trial used stratification, pair
   matching, blocking, minimization, or constrained randomization, what must
   the primary analysis include to be correct? Must it include the matched
   set/block or every matching/stratification variable, and is partial or
   alternative adjustment ever sufficient? For power, must the sample-size
   calculation also represent the correlation induced by the restriction, or
   is an otherwise adequate clustering adjustment sufficient?

2. **Nested clustering:** Apart from longitudinal repeated measures, which you
   previously said not to count, must the analysis account only for the
   randomization unit or for every provider/delivery level with residual
   correlation? Please apply this to Mann 2020 (`DCYTWR4N`), Goldstein 2019
   (`LU33978L`), and Cox 2024 (`TEXLFQSL`). For Cox, the full text appears to
   describe a clinician random effect and centered stratification variables,
   while the source note says fixed effects and missed levels; please confirm
   which primary analysis controls the label. Please also confirm Goldstein's
   power label, because its calculation accounted for the hospital but not the
   clinician level.

3. **Protocols and baseline/design reports:** We will continue to keep these
   papers eligible, per your earlier decision. Can a paper that reports only a
   planned future analysis nevertheless receive `data_correct=yes`, or must a
   treatment-effect analysis have actually been performed and reported?
   Please apply this to Arrossi 2019 (`B3KTU9TU`) and Brewer 2022
   (`FHVQQIX3`). For Arrossi, please also confirm whether the power calculation
   needed to account for its gender and urban/rural strata.

4. **Source-field interpretation:** Are `data_should` and `power_should`
   exhaustive descriptions of what the reviewers required, or are they
   shorthand? In particular, if `restricted_rand=yes` but a `*_should` field
   omits the restriction, should we still assume that the restriction had to
   be addressed? This determines whether those fields can be used to audit the
   binary labels.

Specific record reviews

- **Five NCI/NHLBI disagreements:** Please give the final eligible/exclude
  decision and exclusion reason, if applicable, for Bartels 2024 (`VGG3KIMT`:
  baseline-only vs keep), Beck 2019 (`RJD9XX6D`: power/data yes vs no), Gilbert
  2022 (`Z7NF2G6Q`: baseline-only vs implementation study), Ockene 2021
  (`HLQA5RI6`: secondary analysis vs keep), and Smith 2023 (`E92KWK4B`:
  implementation vs methods paper). For every paper kept, please also provide
  final power- and data-analysis labels.

- **Cattamanchi 2021 (`XHFTHUCG`):** You previously identified its
  `data_correct=yes` label as wrong because its analysis handled clinic
  clustering but not its stratified randomization. Please confirm the final
  corrected data label; the paper is currently removed from scoring pending
  this review.

- **Seven restricted-randomization records:** Douin 2025 (`7NYXSVAI`),
  Fortmann 2021 (`W2VQEXEG`), Kinnamon 2023 (`XEIAGV9H`), Green 2018
  (`5VWZPNEQ`), Grissom 2023 (`QUEFXEQY`), Hanrahan 2023 (`WUNIU4CC`), and
  Olomu 2022 (`4TRC3UDD`) all have `restricted_rand=yes`, but neither their
  data nor power `should` field asks for the restriction. Please confirm the
  final power and data labels for each, especially the currently positive
  labels for Douin, Fortmann, and Kinnamon. Fortmann's existing comment already
  says Keith did not think its data analysis was correct. Douin also appears in
  the stepped-wedge group below.

- **Five additional batch-1 data conflicts:** Please give a final data label
  for Gans 2018 (`SGCHKJTH`: labelled yes; no matched-pair term found), Vidrine
  2019 (`2RDD8DGI`: labelled yes; only one of two stratification factors found
  in the model), Bryant-Stephens 2024 (`IPR6QU8P`: labelled yes; the full text
  appears to contain clinic/school stratification not recorded in the source
  row), Cooper 2024 (`84YU8UCD`: labelled no; the full text appears to account
  for practice clustering and the health-system stratum), and Adams 2019
  (`D24FD6G2`: labelled no; the full text appears to specify physician-level
  GEE clustering with robust standard errors). Vidrine, Bryant-Stephens, and
  Adams also have disputed power labels, so please confirm those as well.

- **Five remaining batch-1 power conflicts:** Please give a final power label
  for Snavely 2023 (`9DKJKFAS`: labelled yes; matching not found in the
  calculation), Pacyna 2018 (`BAABE7JM`: labelled no; clustering handled, but
  allocation was blocked), Thankappan 2020 (`WY9D5UIK`: labelled no; the paper
  appears to use a design effect and six clusters with simple 3-vs-3
  allocation), Pfammatter 2020 (`LGEECHQM`: labelled no; the paper cites a
  paired-cluster formula), and Halterman 2022 (`7M6ST2JQ`: labelled no; the
  paper appears to randomize individuals within school strata rather than
  schools). These checks will also clarify what evidence is sufficient within
  the manuscript rather than inferred from a citation or balanced arms.

- **Five analysed stepped-wedge papers:** Bernabe-Ortiz 2020 (`3JVAWNIE`),
  Ciccone (`TT7PIVLD`), Douin 2025 (`7NYXSVAI`), Courtright (`QMLU4TM8`), and
  Fiscella (`8H9BUEWH`) were labelled eligible even though nine other
  stepped-wedge papers were excluded. You have since ruled that E3 excludes
  stepped-wedge trials, but these five records were not individually re-read.
  Please confirm whether each meets E3 and should be excluded. If any should
  remain eligible, please also confirm its power and data labels. These papers
  are currently removed from scoring pending this review.

For each paper, please give the final decision and a one-sentence rationale.
Where a methodological ruling affects both power and data analysis, please
apply it to both. We will retain the original labels and record your
adjudications separately rather than overwriting the source data.

The five institutional-disagreement PDFs are in
`data/removed_pdfs/institutional_disagreements/`; Cattamanchi and the five
stepped-wedge PDFs are in `data/removed_pdfs/expert_review/`; the other PDFs are
in `data/raw_pdfs/Human Labelled Set/`.

Thank you,
[Your name]

---

Internal note: This email now covers all three pending expert-review piles and
all ten disagreements from each batch-1 analysis task. It also asks whether
the seven restricted-randomization omissions affect both `data_should` and
`power_should`. The v2 evidence anchors remain draft until these decisions are
recorded.
