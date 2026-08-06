"""Zotero group library -> local PDF corpus.

Walks Glykos > "Boring Task" > <NIH institute> subcollections, pulls each
record's PDF attachment, verifies it against the md5 Zotero stores for that
attachment, and writes it to data/raw_pdfs/all/<paper_id>.pdf.

paper_id is the Zotero item key (8 chars, e.g. "4XKQ7B2M"): always present,
unique, and stable across edits. DOI/PMCID are kept as metadata only, since
they are missing or inconsistently formatted on some records.

md5 verification here catches a truncated or corrupted transfer. It does NOT
catch the wrong PDF filed under the right record -- that is identity
verification, which runs later against extracted text (see zotero_fetch_draft.md
section 4).
"""

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from pyzotero import zotero
from tenacity import retry, stop_after_attempt, wait_exponential

ROOT_COLLECTION_NAME = "Boring Task"

# Attachments whose bytes live in Zotero's cloud storage, best first. A
# linked_file exists only on the machine that added it, so it can never be
# downloaded through the API.
LINK_MODE_PRIORITY = ["imported_file", "imported_url", "linked_url"]

# Per-record outcomes recorded in the manifest.
STATUS_OK = "OK"
STATUS_PDF_MISSING = "PDF_MISSING"
STATUS_DOWNLOAD_CORRUPT = "DOWNLOAD_CORRUPT"
STATUS_PDF_UNREADABLE = "PDF_UNREADABLE"

MANIFEST_COLUMNS = [
    "paper_id", "institute", "title", "first_author", "doi", "pmid", "pmcid",
    "year", "journal", "attachment_key", "md5", "status", "detail", "warning",
    "verdict", "title_score", "set", "fetched_at",
]


class CollectionNotFound(Exception):
    """Raised when the root collection name is absent from the group library.

    Deliberately fatal: silently guessing at a differently-named collection
    would pull the wrong corpus.
    """


def connect(library_id: str, api_key: str, library_type: str = "group") -> zotero.Zotero:
    """Open a pyzotero client. pyzotero wraps API v3 paging and honors the
    Backoff / Retry-After headers, which hand-rolled request loops usually miss."""
    return zotero.Zotero(library_id, library_type, api_key)


def resolve_institutes(zot: zotero.Zotero, root_name: str = ROOT_COLLECTION_NAME) -> list[dict]:
    """Find the root collection by name and return its immediate children --
    one per NIH institute.

    Raises CollectionNotFound (listing what was available) rather than
    falling back to a partial or empty tree.
    """
    collections = zot.all_collections()

    root = next((c for c in collections if c["data"]["name"] == root_name), None)
    if root is None:
        available = sorted(c["data"]["name"] for c in collections)
        raise CollectionNotFound(
            f"No collection named {root_name!r} in library. Available: {available}"
        )

    return [c for c in collections if c["data"].get("parentCollection") == root["key"]]


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


def parse_extra(extra: str | None) -> dict:
    """Pull PMID / PMCID / DOI out of Zotero's free-text Extra field, where
    the PubMed and Zotero connectors stash identifiers that have no dedicated
    column on a journalArticle item."""
    extra = extra or ""
    pmid = re.search(r"PMID:\s*(\d+)", extra, re.I)
    pmcid = re.search(r"(PMC\d+)", extra, re.I)
    doi = re.search(r"DOI:\s*(\S+)", extra, re.I)
    return {
        "pmid": pmid.group(1) if pmid else "",
        "pmcid": pmcid.group(1).upper() if pmcid else "",
        "doi": normalize_doi(doi.group(1)) if doi else "",
    }


def build_metadata(item: dict, institute_name: str) -> dict:
    """Flatten one Zotero item into the manifest's metadata fields."""
    data = item["data"]
    extra = parse_extra(data.get("extra"))

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
        "institute": institute_name,
        "title": data.get("title", ""),
        "authors": [a.get("lastName") or a.get("name", "") for a in authors],
        "first_author": first_author,
        # The DOI field is authoritative; Extra is the fallback for records
        # imported without one.
        "doi": normalize_doi(data.get("DOI")) or extra["doi"],
        "pmid": extra["pmid"],
        "pmcid": extra["pmcid"],
        "year": year.group(0) if year else "",
        "journal": data.get("publicationTitle", ""),
    }


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
        titles = "; ".join(
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


def fetch_collection(
    zot: zotero.Zotero,
    institute: dict,
    pdf_dir: Path,
    progress=None,
) -> list[dict]:
    """Fetch every top-level record in one institute subcollection.

    Returns one manifest row per record, including the ones that failed --
    a paper with no retrievable PDF has to stay visible, not vanish from the
    corpus silently.
    """
    institute_name = institute["data"]["name"]
    items = zot.everything(zot.collection_items_top(institute["key"]))
    rows = []

    for item in items:
        # collection_items_top should already exclude these; cheap to be sure.
        if item["data"].get("itemType") in {"note", "attachment"}:
            continue

        meta = build_metadata(item, institute_name)
        row = {
            **{k: meta.get(k, "") for k in MANIFEST_COLUMNS},
            "attachment_key": "",
            "md5": "",
            "warning": "",
            # Filled by identity verification at extraction time.
            "verdict": "",
            "title_score": "",
            # "Boring Task" holds only the study corpus; the 500 labeled
            # validation papers come from elsewhere.
            "set": "full_set",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        attachment, problem, warning = select_pdf_attachment(zot.children(item["key"]))
        row["warning"] = warning
        if attachment is None:
            row.update(status=STATUS_PDF_MISSING, detail=problem)
        else:
            dest = pdf_dir / f"{meta['paper_id']}.pdf"
            status, detail = fetch_pdf(zot, attachment, dest)
            row.update(
                attachment_key=attachment["key"],
                md5=attachment["data"].get("md5", ""),
                status=status,
                detail=detail,
            )

        rows.append(row)
        if progress is not None:
            progress.update(1)

    return rows
