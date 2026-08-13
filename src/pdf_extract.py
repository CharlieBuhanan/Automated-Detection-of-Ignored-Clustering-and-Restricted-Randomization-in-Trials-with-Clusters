"""PDF -> cached text, with fallback logic.

Primary extractor: PyMuPDF (fitz). Falls back to pdfplumber if the
extracted text looks too sparse/garbled (common with multi-column PMC
layouts). Falls back to OCR (pytesseract) only if both digital extractors
come up empty, i.e. the PDF is a scanned image.

Each PDF is parsed once; results are cached to data/extracted_text/<paper_id>.json
keyed by the PDF's filename stem.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber

# Below this many characters per page, on average, treat the extraction as
# too sparse to trust and try the next method.
MIN_CHARS_PER_PAGE = 200

# Pages of front matter used for identity verification. Title, authors and DOI
# live here; two pages covers papers whose author list runs long.
HEAD_PAGES = 2


def _extract_with_pymupdf(pdf_path: Path) -> tuple[str, int]:
    """Extract text page-by-page using PyMuPDF. Fast, and usually sufficient
    for digital-native PDFs (e.g. PMC papers)."""
    with fitz.open(pdf_path) as doc:
        pages = [page.get_text() for page in doc]
    return "\n\n".join(pages), len(pages)


def _extract_with_pdfplumber(pdf_path: Path) -> tuple[str, int]:
    """Extract text page-by-page using pdfplumber. Slower than PyMuPDF but
    often more accurate on multi-column layouts and tables."""
    with pdfplumber.open(pdf_path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n\n".join(pages), len(pages)


def _extract_with_ocr(pdf_path: Path) -> tuple[str, int]:
    """Rasterize each page to an image and run Tesseract OCR over it. Last
    resort for scanned pages that have no extractable text layer at all."""
    import pytesseract
    from PIL import Image

    with fitz.open(pdf_path) as doc:
        pages = []
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            pages.append(pytesseract.image_to_string(img))
    return "\n\n".join(pages), len(pages)


def file_md5(path: Path) -> str:
    """md5 of a file's bytes, read in chunks so a large PDF is not slurped."""
    digest = hashlib.md5()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sparse(text: str, page_count: int) -> bool:
    """True if the extracted text is too thin (per page) to trust, signaling
    that the next fallback extractor should be tried instead."""
    if page_count == 0:
        return True
    return len(text.strip()) / page_count < MIN_CHARS_PER_PAGE


def extract_head_text(pdf_path: Path, pages: int = HEAD_PAGES) -> tuple[str, int, str]:
    """Text of the first few pages only, for identity verification.

    Deliberately separate from extract_pdf_text: identity is decided on front
    matter (title, authors, DOI), and full extraction is expensive to run over
    a corpus that has not been verified yet. PLAN.md step 1 runs this; step 2
    runs the full pass, on verified papers only.

    The last page is NOT included, though an earlier draft called for it to
    catch footer DOIs. Measured on 60 PDFs: the last page contributed zero DOI
    hits that pages 1-2 had not already found, while adding reference-list DOIs
    that only muddy the check.

    No OCR here -- a PDF with no text layer is reported as such (near-zero
    characters) and triaged separately, rather than silently costing 30s/paper.

    Returns (text, total_page_count, method).
    """
    pdf_path = Path(pdf_path)

    for name, opener in (("pymupdf", _head_with_pymupdf), ("pdfplumber", _head_with_pdfplumber)):
        try:
            text, page_count = opener(pdf_path, pages)
        except Exception:
            continue
        if text.strip():
            return text, page_count, name

    return "", 0, "none"


def _head_with_pymupdf(pdf_path: Path, pages: int) -> tuple[str, int]:
    with fitz.open(pdf_path) as doc:
        total = len(doc)
        head = "\n".join(doc[i].get_text() for i in range(min(pages, total)))
    return head, total


def _head_with_pdfplumber(pdf_path: Path, pages: int) -> tuple[str, int]:
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        head = "\n".join(
            (pdf.pages[i].extract_text() or "") for i in range(min(pages, total))
        )
    return head, total


def extract_pdf_text(pdf_path: Path) -> dict:
    """Extract text from a single PDF, trying pymupdf -> pdfplumber -> ocr in
    order and stopping at the first non-sparse result (falling through on
    any extractor exception). paper_id is taken from the filename stem, so
    e.g. data/raw_pdfs/validation/PMC1234567.pdf -> paper_id "PMC1234567".

    Returns a dict ready to cache to JSON:
        paper_id, source_path, method (which extractor won, "none" if all
        failed), errors (why each failed extractor failed), page_count,
        char_count, extracted_at, text.

    `errors` matters most for the OCR rung: it imports pytesseract and Pillow
    lazily and needs the Tesseract binary, so it fails with ImportError on a
    machine that has none of them. Recording the reason is what separates "this
    PDF is a scan we cannot read" from "OCR was never actually available".
    """
    pdf_path = Path(pdf_path)
    attempts = [
        ("pymupdf", _extract_with_pymupdf),
        ("pdfplumber", _extract_with_pdfplumber),
        ("ocr", _extract_with_ocr),
    ]

    # "none", not attempts[-1][0]: a PDF that every extractor choked on used no
    # method at all, and reporting it as OCR-extracted would hide the failure
    # behind the one method whose output nobody expects to be clean anyway.
    text, page_count, method = "", 0, "none"
    errors = []
    for name, fn in attempts:
        try:
            candidate, candidate_pages = fn(pdf_path)
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        text, page_count, method = candidate, candidate_pages, name
        if not _is_sparse(text, page_count):
            break

    return {
        "paper_id": pdf_path.stem,
        "source_path": str(pdf_path),
        # What this text was extracted FROM. Replacing a paper's PDF during
        # review has to invalidate its cached text, and a filename cannot say
        # that -- the replacement lands at the same path.
        "pdf_md5": file_md5(pdf_path),
        "method": method,
        "errors": errors,
        "page_count": page_count,
        "char_count": len(text),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "text": text,
    }


def is_cache_stale(cache_path: Path, pdf_path: Path) -> bool:
    """True if the cached text no longer describes the PDF sitting on disk.

    "The cache file exists" is not the same question. A paper whose PDF was
    swapped during hand review -- the wrong article replaced with the right one
    -- keeps its paper_id and therefore its cache path, so an existence check
    would hand back text extracted from a file that is gone. That is the worst
    kind of failure available here: silent, permanent, and invisible in every
    downstream count.

    Records written before pdf_md5 existed are treated as stale, so the first
    run after this change re-extracts once and everything afterwards is
    comparable.
    """
    try:
        cached = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return cached.get("pdf_md5") != file_md5(pdf_path)


def extract_and_cache(pdf_path: Path, cache_dir: Path, overwrite: bool = False) -> dict:
    """Extract (or load from cache) the text for one PDF.

    Returns the cached record when it still matches the PDF on disk, so a given
    PDF is only ever parsed once. A PDF that has since been replaced is
    re-extracted automatically -- see is_cache_stale. Pass overwrite=True to
    force re-extraction regardless (e.g. after changing the extraction logic).
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{Path(pdf_path).stem}.json"

    if cache_path.exists() and not overwrite and not is_cache_stale(cache_path, pdf_path):
        return json.loads(cache_path.read_text(encoding="utf-8"))

    record = extract_pdf_text(pdf_path)
    cache_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record
