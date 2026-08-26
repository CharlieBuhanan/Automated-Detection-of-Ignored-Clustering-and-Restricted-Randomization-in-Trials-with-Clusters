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

## Script 13 — logical steps

Read-only. Asks whether the HLS has stopped shrinking, so the DC42 restore is safe.

- Load manifest, labels, review logs
- C1-C2: label parity, verdict closure
- C3-C5: queue drained, text present and clean
- C6-C8: label categories and vocabulary
- C9-C12: duplicates, disagreements, unjoined citations
- C13-C14: split unassigned, ledger agrees
- Preview DC42 restore candidates, restore nothing

## Script 14 — logical steps

Read-only. The US has no labels, so every check asks about *inputs* instead.

- Load manifest, cache, review logs
- U1-U2: cached text present, verdicts resolved
- U3-U5: queue drained, no bad parse, no correction notice
- U6-U7: no duplicate inside the US, none shared with the HLS
- U8-U9: removals still justified (U9 fails until DC42 restore runs)
- U10-U12: ledger agrees, PDFs accounted for, count matches the published figure
