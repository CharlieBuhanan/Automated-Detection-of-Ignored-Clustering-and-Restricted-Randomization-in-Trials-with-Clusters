# Review files

- **`01_papers_to_review.csv`** — PDFs flagged by identity verification for manual triage.
- **`02_removed_us_duplicates.csv`** — Unlabelled Set papers dropped for already being in the Human Labelled Set.
- **`03_hls_internal_duplicates.csv`** — Human Labelled Set papers fetched into both NCI and NHLBI.
- **`04_papers_reviewed_results.csv`** — human decisions from the mismatch-review GUI.
- **`05_label_match_review.csv`** — ground-truth citations needing a human: unresolved or disputed.
- **`06_merged_hls_duplicates.csv`** — which NCI/NHLBI duplicate pair merged into which paper_id.
- **`07_ground_truth_unjoined.csv`** — label rows that never resolved to a paper_id.
- **`09_nhlbi_unreviewed_dropped.csv`** — NHLBI papers dropped for never being reviewed.
- **`10_nonjudgeable_exclusions_dropped.csv`** — HLS papers dropped for a cross-paper exclusion reason (protocol paper, random drop).
- **`11_text_integrity_flagged.csv`** — papers whose cached text looked like the wrong document (submission forms, etc.).
- **`12_institutional_disagreements_dropped.csv`** — HLS papers dropped for an NCI/NHLBI disagreement, assumed unresolved.
