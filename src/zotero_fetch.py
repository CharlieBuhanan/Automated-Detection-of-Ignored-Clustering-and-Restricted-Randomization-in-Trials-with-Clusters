"""Zotero group library -> local PDF corpus.

Walks a Zotero collection and every collection nested beneath it, at any
depth, pulls each record's PDF attachment, verifies it against the md5 Zotero
stores for that attachment, and writes data/raw_pdfs/<Set Name>/<paper_id>.pdf
(the directory for a set comes from SET_DIRS; see set_dir()).

paper_id is the Zotero item key (8 chars, e.g. "4XKQ7B2M"): always present,
unique, and stable across edits. DOI/PMCID are kept as metadata only, since
they are missing or inconsistently formatted on some records.

md5 verification here catches a truncated or corrupted transfer. It does NOT
catch the wrong PDF filed under the right record -- that is identity
verification, which runs later against extracted text (see research design/PLAN.md step 1).
"""

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from pyzotero import zotero
from tenacity import retry, stop_after_attempt, wait_exponential

# Separator for a folder path, e.g. "Boring Task / NCI / 2019".
PATH_SEP = " / "

# Separator for the folders of a paper filed in more than one collection.
MULTI_SEP = "; "

# Attachments whose bytes live in Zotero's cloud storage, best first. A
# linked_file exists only on the machine that added it, so it can never be
# downloaded through the API.
LINK_MODE_PRIORITY = ["imported_file", "imported_url", "linked_url"]

# Which half of the corpus a paper belongs to. The Unlabelled Set (US) is the
# papers being classified; the Human Labelled Set (HLS) carries human labels
# and is the regression suite. Zotero knows nothing about this split -- it
# comes from which collection was fetched.
SET_UNLABELLED = "unlabelled"
SET_HUMAN_LABELLED = "human_labelled"

# The set is stored as a slug, never as a directory name: it is baked into
# every manifest row, so a folder rename must not require rewriting the data.
# This map is the single place the two are connected.
SET_DIRS = {
    SET_UNLABELLED: "Unlabelled Set",
    SET_HUMAN_LABELLED: "Human Labelled Set",
}


def set_dir(root: Path, set_name: str) -> Path:
    """data/raw_pdfs/ subdirectory holding `set_name`'s PDFs.

    Raises on an unknown set rather than silently building a path to a
    directory that does not exist -- the old failure mode, which surfaced as
    "PDF missing" on every paper at once.
    """
    try:
        return root / "data" / "raw_pdfs" / SET_DIRS[set_name]
    except KeyError:
        raise ValueError(
            f"unknown set {set_name!r}; expected one of {sorted(SET_DIRS)}"
        ) from None

# Only journal articles are papers. The library also holds the occasional
# videoRecording, webpage, or report; those are skipped and reported rather
# than quietly entering the corpus.
PAPER_ITEM_TYPES = {"journalArticle"}

# Per-record outcomes recorded in the manifest.
STATUS_OK = "OK"
STATUS_PDF_MISSING = "PDF_MISSING"
STATUS_DOWNLOAD_CORRUPT = "DOWNLOAD_CORRUPT"
STATUS_PDF_UNREADABLE = "PDF_UNREADABLE"

MANIFEST_COLUMNS = [
    "paper_id", "folder", "folder_path", "title", "first_author", "doi",
    "pmid", "pmcid", "year", "journal", "attachment_key", "md5",
    "status", "detail", "warning", "verdict", "verdict_reason", "title_score",
    "set", "fetched_at",
]


class CollectionNotFound(Exception):
    """Raised when the configured root collection is absent from the library.

    Deliberately fatal: silently guessing at a different collection would
    pull the wrong corpus.
    """


def connect(library_id: str, api_key: str, library_type: str = "group") -> zotero.Zotero:
    """Open a pyzotero client. pyzotero wraps API v3 paging and honors the
    Backoff / Retry-After headers, which hand-rolled request loops usually miss."""
    return zotero.Zotero(library_id, library_type, api_key)


def _collection_path(key: str, by_key: dict) -> list[str]:
    """Names from the library root down to this collection.

    Guards against a cycle in parentCollection -- malformed data would
    otherwise loop forever.
    """
    names, seen = [], set()
    while key and key in by_key and key not in seen:
        seen.add(key)
        names.append(by_key[key]["data"]["name"])
        parent = by_key[key]["data"].get("parentCollection")
        key = parent if parent else None
    return list(reversed(names))


def resolve_subtree(zot: zotero.Zotero, root: str, exclude: list[str] | None = None) -> list[dict]:
    """Return the root collection plus every collection nested under it.

    `root` is a Zotero collection key, or a collection name as a fallback for
    convenience. Each returned dict carries the Zotero collection plus:
        name        -- the collection's own name
        path        -- full path from the library root, e.g. "Boring Task / NCI"

    `exclude` drops collections by name or key, along with everything nested
    under them -- for staging or sample collections that sit in the tree but
    are not part of the corpus.

    Depth is unlimited: institutes today, institutes-by-year tomorrow, both
    work without a code change.
    """
    exclude = set(exclude or [])
    collections = zot.all_collections()
    by_key = {c["key"]: c for c in collections}

    if root in by_key:
        root_key = root
    else:
        match = next((c for c in collections if c["data"]["name"] == root), None)
        if match is None:
            available = sorted(
                f"{c['data']['name']} ({c['key']})" for c in collections
            )
            raise CollectionNotFound(
                f"No collection with key or name {root!r} in library. "
                f"Available: {available}"
            )
        root_key = match["key"]

    # A collection is in scope when root_key appears anywhere in its ancestry.
    subtree = []
    for c in collections:
        path_keys, key, seen = [], c["key"], set()
        while key and key in by_key and key not in seen:
            seen.add(key)
            path_keys.append(key)
            parent = by_key[key]["data"].get("parentCollection")
            key = parent if parent else None
        if root_key not in path_keys:
            continue
        # Exclusion applies to the whole branch: naming a parent drops its
        # children too, which is what "not part of the corpus" has to mean.
        if any(k in exclude or by_key[k]["data"]["name"] in exclude for k in path_keys):
            continue
        subtree.append(
            {**c, "name": c["data"]["name"], "path": PATH_SEP.join(_collection_path(c["key"], by_key))}
        )

    return sorted(subtree, key=lambda c: c["path"])


def normalize_doi(raw: str | None) -> str:
    """Reduce a DOI to bare '10.xxxx/yyyy' form, lowercased.

    Records carry DOIs as bare strings, as doi: prefixes, and as full
    https://doi.org/ URLs; downstream matching needs one shape.
    """
    if not raw:
        return ""
    doi = unicodedata.normalize("NFKC", raw).strip()
    doi = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    match = re.search(r"10\.\d{4,9}/\S+", doi)
    return match.group(0).rstrip(".,;").lower() if match else ""


# Recent Zotero added dedicated PMID/PMCID fields on journalArticle. Records
# created before that -- and anything imported by an older connector -- still
# carry them in free text, so both paths are needed and will be for a long
# time. Field casing is checked defensively: Zotero uses uppercase for DOI and
# ISSN, but the schema is not consistent about it.
_PMID_FIELDS = ["PMID", "pmid"]
_PMCID_FIELDS = ["PMCID", "pmcid"]

# Fallbacks, in rough order of reliability: the Extra field, archiveID (used by
# some PubMed importers), and the item URL.
_PMID_PATTERNS = [
    r"PMID\s*[:=]?\s*(\d{1,8})\b",
    r"pubmed\.ncbi\.nlm\.nih\.gov/(\d{1,8})",
    r"/pubmed/(\d{1,8})",
]
_PMCID_PATTERNS = [
    r"PMCID\s*[:=]?\s*(?:PMC)?(\d+)\b",
    r"\bPMC(\d+)\b",
    r"/pmc/articles/PMC(\d+)",
]


def _first_match(patterns: list[str], sources: list[str]) -> str:
    """First capture group any pattern finds, searching sources in order.

    Source order is priority order: an explicit "PMID: 123" in Extra beats an
    ID scraped out of a URL.
    """
    for source in sources:
        if not source:
            continue
        for pattern in patterns:
            match = re.search(pattern, source, re.I)
            if match:
                return match.group(1)
    return ""


def _field_value(data: dict, names: list[str]) -> str:
    """First non-empty value among several possible field spellings."""
    for name in names:
        value = data.get(name)
        if value:
            return str(value).strip()
    return ""


def parse_identifiers(data: dict) -> dict:
    """Pull PMID / PMCID / DOI off an item.

    The dedicated field wins when present. Otherwise fall back to free text:
    Extra is the usual home, but records imported from a PubMed link carry the
    ID only in the URL, and some importers use archiveID instead.

    Missing a PMCID is not fatal -- paper_id is the Zotero key -- but these are
    the identifiers that will join this corpus to the human labels, which
    are almost certainly keyed by DOI or PMCID rather than a Zotero key.
    """
    extra = data.get("extra") or ""
    url = data.get("url") or ""
    archive_id = data.get("archiveID") or ""
    sources = [extra, archive_id, url]

    # A dedicated field can still hold "PMID: 123" or a bare number, so run the
    # same patterns over it rather than trusting its shape.
    pmid = _first_match(_PMID_PATTERNS + [r"^\s*(\d{1,8})\s*$"], [_field_value(data, _PMID_FIELDS)])
    pmcid = _first_match(_PMCID_PATTERNS + [r"^\s*(\d+)\s*$"], [_field_value(data, _PMCID_FIELDS)])

    pmid = pmid or _first_match(_PMID_PATTERNS, sources)
    pmcid = pmcid or _first_match(_PMCID_PATTERNS, sources)
    doi = re.search(r"DOI\s*[:=]?\s*(\S+)", extra, re.I)

    return {
        "pmid": pmid,
        # Stored with the prefix, the form PubMed and the labels file use.
        "pmcid": f"PMC{pmcid}" if pmcid else "",
        "doi": normalize_doi(doi.group(1)) if doi else "",
    }


def build_metadata(item: dict) -> dict:
    """Flatten one Zotero item into the manifest's metadata fields."""
    data = item["data"]
    ids = parse_identifiers(data)

    authors = [
        c for c in data.get("creators", []) if c.get("creatorType") == "author"
    ]
    first_author = ""
    if authors:
        first_author = authors[0].get("lastName") or authors[0].get("name", "")

    year = re.search(r"\b(1[89]\d{2}|20\d{2})\b", data.get("date", "") or "")

    return {
        "paper_id": item["key"],
        "zotero_version": item["version"],
        "title": data.get("title", ""),
        "authors": [a.get("lastName") or a.get("name", "") for a in authors],
        "first_author": first_author,
        # The DOI field is authoritative; Extra is the fallback for records
        # imported without one.
        "doi": normalize_doi(data.get("DOI")) or ids["doi"],
        "pmid": ids["pmid"],
        "pmcid": ids["pmcid"],
        "year": year.group(0) if year else "",
        "journal": data.get("publicationTitle", ""),
        "abstract": data.get("abstractNote", ""),
    }


def build_meta_records(records: dict, set_name: str = SET_UNLABELLED) -> list[dict]:
    """Build the full metadata record for each paper, for data/zotero_meta.jsonl.

    The manifest CSV keeps one scannable row per paper; this keeps everything
    else. `zotero_item` is Zotero's untouched JSON, so a field nobody thought
    to promote to a column is still recoverable without re-pulling the library.

    Takes the dict `collect_items` already returns, so no extra API calls.
    """
    meta_records = []

    for paper_id, record in records.items():
        meta = build_metadata(record["item"])
        meta_records.append({
            **meta,
            "paper_id": paper_id,
            "set": set_name,
            "folders": record["folders"],
            "folder_paths": record["paths"],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "zotero_item": record["item"],
        })

    return meta_records


def load_meta(path: Path) -> dict:
    """Read data/zotero_meta.jsonl back as {paper_id: record}.

    Identity verification reads author surnames from here -- `author_frac`
    needs every author, and the manifest only carries `first_author`.
    """
    path = Path(path)
    if not path.exists():
        return {}

    records = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                record = json.loads(line)
                records[record["paper_id"]] = record
    return records


def completed_ids(manifest_rows: dict, pdf_dir: Path) -> set:
    """Papers already fetched and still intact on disk, safe to skip.

    All three conditions must hold: the manifest says the fetch succeeded, the
    PDF is present, and its bytes still hash to the md5 Zotero reported. That
    is the same check `fetch_pdf` makes before re-downloading, so skipping here
    is exactly as trustworthy -- it just avoids the `zot.children()` call that
    would otherwise be needed to learn the md5 again.

    A row with no md5 is never skipped: without it there is nothing to verify.
    """
    pdf_dir = Path(pdf_dir)
    done = set()

    for paper_id, row in manifest_rows.items():
        if row.get("status") != STATUS_OK or not row.get("md5"):
            continue
        pdf_path = pdf_dir / f"{paper_id}.pdf"
        if pdf_path.exists() and _md5(pdf_path.read_bytes()) == row["md5"]:
            done.add(paper_id)

    return done


def select_pdf_attachment(children: list[dict]) -> tuple[dict | None, str, str]:
    """Choose the best downloadable PDF among an item's child attachments.

    Rules:
      - Several PDFs -> take the highest-priority one but WARN. One of them is
        probably a supplement, an appendix, or an older version, and picking
        the wrong file silently would put the wrong text in the corpus.
      - One PDF alongside non-PDF attachments (link, snapshot, note) -> take
        the PDF, no warning. That is the normal shape of a Zotero record.
      - No usable PDF -> a problem, reported as PDF_MISSING.

    Returns (attachment, problem, warning). `problem` is non-empty only when
    nothing is downloadable; `warning` is non-empty when the pick is ambiguous.
    """
    pdfs = [
        c for c in children
        if c["data"].get("contentType") == "application/pdf"
    ]
    if not pdfs:
        return None, "no PDF attachment on record", ""

    warning = ""
    if len(pdfs) > 1:
        titles = MULTI_SEP.join(
            p["data"].get("title") or p["data"].get("filename") or p["key"]
            for p in pdfs
        )
        warning = f"{len(pdfs)} PDF attachments, picked highest priority: {titles}"

    for link_mode in LINK_MODE_PRIORITY:
        match = next(
            (p for p in pdfs if p["data"].get("linkMode") == link_mode), None
        )
        if match is not None:
            return match, "", warning

    return None, "linked_file not in cloud storage", ""


def _md5(payload: bytes) -> str:
    return hashlib.md5(payload).hexdigest()


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=30), reraise=True)
def _download(zot: zotero.Zotero, attachment_key: str) -> bytes:
    """GET the attachment's bytes, retrying on transient network/5xx errors.

    pyzotero already respects Zotero's own backoff headers; this covers
    connection resets and gateway errors on top of that.
    """
    return zot.file(attachment_key)


def fetch_pdf(zot: zotero.Zotero, attachment: dict, dest: Path) -> tuple[str, str]:
    """Download one attachment to dest, verifying integrity before it lands.

    Skips the download entirely when dest already matches the expected md5,
    which is what makes a whole-corpus re-run cheap and lets a partial pull
    repair itself.

    Returns (status, detail).
    """
    expected_md5 = attachment["data"].get("md5") or ""

    if dest.exists() and expected_md5 and _md5(dest.read_bytes()) == expected_md5:
        return STATUS_OK, "cached"

    payload = _download(zot, attachment["key"])

    actual_md5 = _md5(payload)
    if expected_md5 and actual_md5 != expected_md5:
        return STATUS_DOWNLOAD_CORRUPT, f"md5 {actual_md5} != zotero {expected_md5}"

    # A Zotero record can have contentType application/pdf while the stored
    # bytes are an HTML paywall/error page saved by the browser connector.
    if not payload.startswith(b"%PDF"):
        return STATUS_PDF_UNREADABLE, "downloaded bytes are not a PDF"

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    return STATUS_OK, "downloaded"


def collect_items(zot: zotero.Zotero, subtree: list[dict]) -> dict:
    """Gather every record in the subtree, deduplicated by paper_id.

    A paper filed in two collections appears twice in the walk but must
    produce one row -- paper_id is the key everything downstream joins on,
    and a duplicate would double-count in accuracy math. The folders are
    collected instead, so nothing is lost.

    Returns (records, skipped) where records is
    {paper_id: {"item": item, "folders": [...], "paths": [...]}} and skipped is
    a list of (paper_id, item_type, title, folder) for non-paper items -- the
    library holds the occasional videoRecording or report, and those should be
    visible rather than silently dropped or silently classified.
    """
    records = {}
    skipped = {}

    for collection in subtree:
        for item in zot.everything(zot.collection_items_top(collection["key"])):
            item_type = item["data"].get("itemType")

            # collection_items_top should already exclude these; cheap to be sure.
            if item_type in {"note", "attachment"}:
                continue

            if item_type not in PAPER_ITEM_TYPES:
                skipped.setdefault(
                    item["key"],
                    (item["key"], item_type, item["data"].get("title", ""), collection["name"]),
                )
                continue

            record = records.setdefault(
                item["key"], {"item": item, "folders": [], "paths": []}
            )
            if collection["name"] not in record["folders"]:
                record["folders"].append(collection["name"])
                record["paths"].append(collection["path"])

    return records, list(skipped.values())


def collect_items_by_key(zot: zotero.Zotero, paper_ids: list[str],
                         folders: dict | None = None) -> tuple[dict, list]:
    """Gather specific records by Zotero item key, skipping the collection walk.

    The walk in collect_items() costs ~3 minutes and returns the whole
    collection, which is the wrong shape when a handful of named papers need
    restoring (DC42): it would resurrect every previously-removed row, not the
    few whose reason for leaving has expired.

    `folders` supplies the collection names for each paper, since fetching an
    item by key gives its collection *keys* but not their names, and resolving
    those would mean the walk this function exists to avoid. Pass
    {paper_id: (folders, folder_paths)}; a paper with no entry gets blanks.

    Returns the same (records, skipped) shape as collect_items(), so the rest
    of the fetch pipeline is reused unchanged.
    """
    records = {}
    skipped = []
    folders = folders or {}

    for paper_id in paper_ids:
        item = zot.item(paper_id)
        item_type = item["data"].get("itemType")
        if item_type not in PAPER_ITEM_TYPES:
            skipped.append((paper_id, item_type, item["data"].get("title", ""), ""))
            continue
        names, paths = folders.get(paper_id, ([], []))
        records[paper_id] = {"item": item, "folders": list(names), "paths": list(paths)}

    return records, skipped


def iter_fetch_records(
    zot: zotero.Zotero,
    records: dict,
    pdf_dir: Path,
    set_name: str = SET_UNLABELLED,
    skip_ids: set | None = None,
    progress=None,
):
    """Download each record's PDF and yield its manifest row, one at a time.

    A generator so the caller can checkpoint as rows arrive. Writing the
    manifest only after the whole loop means an interrupted run leaves PDFs on
    disk with nothing describing them -- and they are named by Zotero item key,
    so without the manifest they are opaque.

    `set_name` tags every row as SET_UNLABELLED (papers to classify) or
    SET_HUMAN_LABELLED (papers with human labels, used for scoring). It comes from
    the caller because it is a property of which collection is being fetched,
    not of anything Zotero records about the item.

    `skip_ids` are papers already fetched and verified on disk. They are
    skipped before the `zot.children()` call, which is the expensive part --
    one HTTP round trip per paper, and the reason a no-op re-run used to cost
    as much as the original.

    Yields one row per record, including failures -- a paper with no
    retrievable PDF has to stay visible, not vanish from the corpus silently.
    """
    skip_ids = skip_ids or set()

    for paper_id, record in records.items():
        if paper_id in skip_ids:
            if progress is not None:
                progress.update(1)
            continue

        meta = build_metadata(record["item"])
        row = {
            **{k: meta.get(k, "") for k in MANIFEST_COLUMNS},
            "folder": MULTI_SEP.join(record["folders"]),
            "folder_path": MULTI_SEP.join(record["paths"]),
            "attachment_key": "",
            "md5": "",
            "warning": "",
            # Filled by identity verification at extraction time.
            "verdict": "",
            "title_score": "",
            "set": set_name,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        attachment, problem, warning = select_pdf_attachment(zot.children(paper_id))
        row["warning"] = warning
        if attachment is None:
            row.update(status=STATUS_PDF_MISSING, detail=problem)
        else:
            status, detail = fetch_pdf(zot, attachment, pdf_dir / f"{paper_id}.pdf")
            row.update(
                attachment_key=attachment["key"],
                md5=attachment["data"].get("md5", ""),
                status=status,
                detail=detail,
            )

        if progress is not None:
            progress.update(1)
        yield row


def fetch_records(zot: zotero.Zotero, records: dict, pdf_dir: Path, **kwargs) -> list[dict]:
    """Eager wrapper around iter_fetch_records, for callers that want a list."""
    return list(iter_fetch_records(zot, records, pdf_dir, **kwargs))
