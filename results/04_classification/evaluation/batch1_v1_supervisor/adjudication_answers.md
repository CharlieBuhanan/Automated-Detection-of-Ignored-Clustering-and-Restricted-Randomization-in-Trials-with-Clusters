# Adjudication answers

## Question 1: Restricted randomization

- Yes, the analysis must include the matched set/block.
- Partial or alternative adjustment is not sufficient.
- For power, there is no otherwise adequate clustering adjustment that is sufficient; the matched set/block must also be included.

## Applied to batch-1 label checks (2026-11-09)

Question 1's answer settles three human labels as **incorrect**, so they were dropped from the
supervisor questions doc (`research design/Deb.md`). The facts come from the model's reading in
batch 1, not a human re-read. Per DC50, these are not edited in place; route them to the
expert-review pile if they need to leave scoring.

- Gans 2018 (`SGCHKJTH`), data: labelled correct; pair-matched, but no pair term in the model.
- Vidrine 2019 (`2RDD8DGI`), data and power: labelled correct; stratified by site type and
  racial/ethnic composition, but the model includes only one factor and the power calc uses only
  the ICC.
- Snavely 2023 (`9DKJKFAS`), power: labelled correct; pair-matched, but the power calc uses only
  ICC/CV.
