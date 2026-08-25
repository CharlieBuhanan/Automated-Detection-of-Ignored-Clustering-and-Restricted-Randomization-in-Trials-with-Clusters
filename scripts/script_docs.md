# Script docs

## Script 01 — logical steps

- Read manifest, keep fetched
- Extract first two pages
- Score DOI, title, authors
- Apply ordered verdict ladder
- Optionally retry other attachments
- Write verdicts to manifest
- Write per-signal report

## Script 02 — logical steps

- Read manifest, keep VERIFIED
- Skip rows missing PDFs
- Hash PDF, check cache
- Re-extract if md5 changed
- Flag failures, corrections, thin text
- Append flagged to review queue
- Write extraction report

## Script 03 — logical steps

- Load queue, drop resolved
- Ask scope, resume position
- Show finding, open sources
- Record decision per paper
- Re-verify replaced PDFs immediately
- Append decision to log
- Update manifest verdict
- Clear stale cached text
