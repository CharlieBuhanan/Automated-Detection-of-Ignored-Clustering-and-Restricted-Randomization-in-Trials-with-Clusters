"""Write a references-stripped copy of every cached paper. Spawns nothing, costs nothing.

WHAT IT DOES
    Reads `data/extracted_text/*.json` and writes one file of the same name to
    `data/extracted_text_stripped/`, with the bibliography removed and an audit
    record attached. The Reading Room reads the stripped directory; the original
    cache is never modified and never deleted (DC6).

    Pure text processing. No model call, no network, no subscription quota.

QUICK START
    # What it would do, and what it would save. Writes nothing.
    python scripts/19_strip_references.py --check

    # Do it. Re-runnable: a file already produced from the same source by the
    # same rules is left alone unless --force.
    python scripts/19_strip_references.py

    # Rebuild every file, e.g. after editing the rules in src/reference_strip.py
    python scripts/19_strip_references.py --force

WHY A DIRECTORY AND NOT A FLAG
    The exact bytes sent to the model are the evidence a judgment is audited
    against. On disk, hashed against their source, they can be diffed a year
    from now; computed at send time they exist only in a process that has exited.

WHAT IT REFUSES TO CUT
    A paper with no standalone references heading, one whose heading sits in the
    first 30% of the document, and one where the cut would remove more than 60%.
    Those are copied through **whole**, with the reason recorded in
    `references_strip.reason`. The output directory therefore always holds one
    file per input file -- so a file missing from it is a real gap, not a paper
    the stripper declined.

WHAT IT REPORTS
    Per-set totals, characters before and after, the estimated token saving, and
    every paper it declined to cut, grouped by reason. Also two accounting
    checks, because "all files must be accounted for" is a standing rule:
    sources with no stripped copy, and stripped copies whose source is gone
    (a paper moved to `data/removed_pdfs/` by one of the drop scripts).
"""

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import reference_strip as rs                            # noqa: E402

SOURCE_DIR = ROOT / "data" / "extracted_text"
TARGET_DIR = ROOT / "data" / "extracted_text_stripped"

# Costs.md counts tokens at 3 characters each; the same divisor is used in the
# Reading Room's --dry-run so the two numbers are comparable.
CHARS_PER_TOKEN = 3


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write a references-stripped copy of the extracted-text cache.")
    parser.add_argument("--check", action="store_true",
                        help="Report what would happen and what it would save; "
                             "write nothing")
    parser.add_argument("--force", action="store_true",
                        help="Rewrite every file, including ones already current")
    parser.add_argument("--source", type=Path, default=SOURCE_DIR)
    parser.add_argument("--target", type=Path, default=TARGET_DIR)
    parser.add_argument("--limit", type=int, help="First N papers only, for a smoke test")
    args = parser.parse_args()

    bar = "=" * 74
    sources = sorted(args.source.glob("*.json"))
    if not sources:
        print(f"No cached text at {args.source}. Run scripts/02_extract_pdfs.py first.")
        return 1
    if args.limit:
        sources = sources[:args.limit]

    print(f"{bar}\nREFERENCE STRIPPING -- {len(sources):,} cached paper(s)\n{bar}")
    print(f"  source : {args.source.relative_to(ROOT)}")
    print(f"  target : {args.target.relative_to(ROOT)}"
          + ("   (--check: nothing will be written)" if args.check else ""))

    reasons = collections.Counter()
    stripped = skipped_current = written = 0
    source_chars = result_chars = tail_chars = 0
    declined: list[tuple[str, str]] = []

    for path in sources:
        payload = load(path)
        text = payload.get("text") or ""

        # Idempotence is what makes this safe to re-run inside a longer script.
        # A file produced from *this* source text by *these* rules is already
        # the answer; anything else is rebuilt.
        target_path = args.target / path.name
        if not args.force and target_path.is_file():
            try:
                if rs.is_current(load(target_path), text):
                    skipped_current += 1
                    existing = rs.strip_record(load(target_path))
                    source_chars += existing.get("source_chars", len(text))
                    result_chars += existing.get("result_chars", len(text))
                    if existing.get("stripped"):
                        stripped += 1
                    else:
                        reasons[existing.get("reason", "?")] += 1
                        declined.append((path.stem, existing.get("reason", "?")))
                    continue
            except json.JSONDecodeError:
                pass            # a corrupt copy is rebuilt, not trusted

        out, result = rs.strip_payload(payload)
        source_chars += result.source_chars
        result_chars += result.result_chars
        tail_chars += result.tail_chars
        if result.stripped:
            stripped += 1
        else:
            reasons[result.reason] += 1
            declined.append((path.stem, result.reason))

        if not args.check:
            write(target_path, out)
            written += 1

    removed = source_chars - result_chars
    percent = (removed / source_chars * 100) if source_chars else 0.0

    print(f"\n  stripped        : {stripped:,}")
    print(f"  left whole      : {sum(reasons.values()):,}")
    for reason, count in reasons.most_common():
        print(f"      {count:>5,}  {reason}  ({rs.explain(reason)})")
    if skipped_current:
        print(f"  already current : {skipped_current:,} (use --force to rebuild)")
    if not args.check:
        print(f"  files written   : {written:,}")

    print(f"\n  chars  {source_chars:,} -> {result_chars:,}  "
          f"({removed:,} removed, {percent:.1f}%)")
    print(f"  tokens ~{source_chars // CHARS_PER_TOKEN:,} -> "
          f"~{result_chars // CHARS_PER_TOKEN:,} at {CHARS_PER_TOKEN} chars/token")
    if tail_chars:
        print(f"  appendix text kept after the bibliography: {tail_chars:,} chars")

    if declined:
        print(f"\n  Papers left whole (first 20 of {len(declined):,}):")
        for paper_id, reason in declined[:20]:
            print(f"      {paper_id}  {rs.explain(reason)}")

    # Accounting. Never silent: a stripped copy whose source has been moved to
    # data/removed_pdfs/ is an orphan the Reading Room could still read.
    if not args.check and args.target.is_dir():
        source_names = {p.name for p in args.source.glob("*.json")}
        target_names = {p.name for p in args.target.glob("*.json")}
        orphans = sorted(target_names - source_names)
        missing = sorted(source_names - target_names)
        if orphans:
            print(f"\n  !! {len(orphans)} stripped file(s) have no source -- the "
                  f"paper was dropped from the corpus after this pass ran:")
            for name in orphans[:10]:
                print(f"      {name}")
            print("     Delete them by hand only after checking the drop log; "
                  "the source cache is the record of what left.")
        if missing:
            print(f"\n  !! {len(missing)} cached paper(s) have no stripped copy. "
                  f"The Reading Room will refuse them (B7). Re-run without --limit.")

    print(bar)
    if args.check:
        print("--check: nothing written.")
    else:
        print(f"Stripped cache -> {args.target.relative_to(ROOT)}")
        print("Next: python scripts/20_reading_room.py --task exclusion "
              "--round 1 --dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
