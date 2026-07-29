"""PDF -> cached text, with fallback logic.

Primary extractor: PyMuPDF (fitz). Falls back to pdfplumber if the
extracted text looks too sparse/garbled (common with multi-column PMC
layouts). Falls back to OCR (pytesseract) only if both digital extractors
come up empty, i.e. the PDF is a scanned image.

Each PDF is parsed once; results are cached to data/extracted_text/<paper_id>.json
keyed by the PDF's filename stem.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber

# Below this many characters per page, on average, treat the extraction as
# too sparse to trust and try the next method.
MIN_CHARS_PER_PAGE = 200


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


def _is_sparse(text: str, page_count: int) -> bool:
    """True if the extracted text is too thin (per page) to trust, signaling
    that the next fallback extractor should be tried instead."""
    if page_count == 0:
        return True
    return len(text.strip()) / page_count < MIN_CHARS_PER_PAGE


def extract_pdf_text(pdf_path: Path) -> dict:
    """Extract text from a single PDF, trying pymupdf -> pdfplumber -> ocr in
    order and stopping at the first non-sparse result (falling through on
    any extractor exception). paper_id is taken from the filename stem, so
    e.g. data/raw_pdfs/validation/PMC1234567.pdf -> paper_id "PMC1234567".

    Returns a dict ready to cache to JSON:
        paper_id, source_path, method (which extractor won),
        page_count, char_count, extracted_at, text.
    """
    pdf_path = Path(pdf_path)
    attempts = [
        ("pymupdf", _extract_with_pymupdf),
        ("pdfplumber", _extract_with_pdfplumber),
        ("ocr", _extract_with_ocr),
    ]

    text, page_count, method = "", 0, attempts[-1][0]
    for name, fn in attempts:
        try:
            text, page_count = fn(pdf_path)
        except Exception:
            continue
        method = name
        if not _is_sparse(text, page_count):
            break

    return {
        "paper_id": pdf_path.stem,
        "source_path": str(pdf_path),
        "method": method,
        "page_count": page_count,
        "char_count": len(text),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "text": text,
    }


def extract_and_cache(pdf_path: Path, cache_dir: Path, overwrite: bool = False) -> dict:
    """Extract (or load from cache) the text for one PDF.

    Checks cache_dir/<paper_id>.json first and returns it as-is if present,
    so a PDF is only ever parsed once. Pass overwrite=True to force
    re-extraction (e.g. after changing the extraction logic).
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{Path(pdf_path).stem}.json"

    if cache_path.exists() and not overwrite:
        return json.loads(cache_path.read_text(encoding="utf-8"))

    record = extract_pdf_text(pdf_path)
    cache_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record
