"""PDF and text extraction with objective quality scoring.

Extraction pipeline (PDF only):
  1. HTML guard    — reject BSE HTML error pages disguised as .pdf
  2. Native        — PyMuPDF text extraction (always attempted first)
  3. Quality score — objective metrics decide whether native text is usable
  4. OCR fallback  — PyMuPDF + Tesseract (only when quality is low)

The decision to fall back to OCR depends only on two quantitative metrics:
  * chars_per_page  (catches scanned / image-only PDFs)
  * garbled_ratio   (catches broken ToUnicode CMap encodings)

No company, sector, or document-type knowledge is used.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Quality constants
# ---------------------------------------------------------------------------

# A page in a dense financial document yields ~200–500 extractable characters.
# Below 50 chars/page the PDF is effectively a scanned image.
_MIN_CHARS_PER_PAGE: float = 50.0

# Fraction of words in the first 8 000 chars that may be "garbled" (contain
# encoding-corruption artefacts) before the extraction is considered unreliable.
# Calibrated on real data:
#   TCS / TATASTEEL (good encoding): 0.000–0.002
#   SBI quarterly results (broken ToUnicode): 0.013–0.019
# A multiplier of 50 drives coherence to 0 at 2 % garbled, leaving ample
# headroom above TCS/TATASTEEL (score ≥ 0.94) while reliably flagging SBI
# (score ≤ 0.61).
_GARBLED_MULTIPLIER: float = 50.0

# Composite quality score below this threshold triggers an OCR attempt.
QUALITY_THRESHOLD: float = 0.65

# Unicode characters that commonly appear in Indian financial text and are NOT
# evidence of encoding corruption.
_SAFE_NON_ASCII: frozenset[str] = frozenset(
    "₹"  # Indian Rupee sign  U+20B9
    "–"  # en-dash            U+2013
    "—"  # em-dash            U+2014
    "‘"  # left single quote
    "’"  # right single quote
    "“"  # left double quote
    "”"  # right double quote
    "…"  # ellipsis
    " "  # non-breaking space
)


# ---------------------------------------------------------------------------
# Quality scoring
# ---------------------------------------------------------------------------


def _is_garbled_word(word: str) -> bool:
    """Return True if *word* shows signs of broken PDF font encoding.

    Three independent signals — any one is sufficient:

    1. Non-ASCII character outside the safe financial-text set, in the Latin
       supplement / Latin extended range (U+0080–U+024F).  This range covers
       accented Latin letters that appear in English financial documents only
       when a ToUnicode CMap is wrong.  Example: "lnt€resU" (€ = U+20AC
       masquerading as 'e').

    2. A digit sandwiched between two letters mid-word.  Legitimate financial
       abbreviations (Q2FY26, CET1, Tier2) don't have this pattern internally.
       Example: "oPe6tlonE" (6 between 'e' and 't').

    3. Word starts with lowercase 'l' followed by an uppercase letter.  This
       is a well-known encoding swap where '[' or 'I' (capital-i) is decoded
       as 'l' (lowercase-L).  Example: "lUnaudlledl" → "[Unaudited]".
    """
    # Strip common surrounding punctuation before inspecting the core token.
    w = word.strip(".,;:!?\"'-()/[]{}|\\")
    if len(w) < 2:
        return False

    # Signal 1 — any non-ASCII character not in the safe set.
    # The range covers all of Unicode above ASCII (> 0x7F), so it catches
    # Latin extended characters (0x0080–0x024F) as well as symbols like
    # € (U+20AC) that appear as broken substitutes for ASCII letters.
    for c in w:
        if ord(c) > 127 and c not in _SAFE_NON_ASCII:
            return True

    # Signal 2 — digit between two alpha characters.
    # Skip words that are entirely uppercase letters + digits: these are
    # legitimate financial abbreviations (Q2FY26, CET1, H1FY25, GNPA).
    # Garbled tokens like "oPe6tlonE" have mixed case, so the guard fails.
    if not all(c.isupper() or c.isdigit() for c in w if c.isalpha() or c.isdigit()):
        for i in range(1, len(w) - 1):
            if w[i].isdigit() and w[i - 1].isalpha() and w[i + 1].isalpha():
                return True

    # Signal 3 — lowercase-l prefix followed by uppercase.
    if w[0] == "l" and w[1].isupper():
        return True

    return False


def score_text_quality(text: str, page_count: int) -> float:
    """Compute a quality score for extracted PDF text.

    Returns a float in [0.0, 1.0]:
      ≥ QUALITY_THRESHOLD  — text is usable; no OCR fallback needed.
      < QUALITY_THRESHOLD  — text is unreliable; OCR fallback should be tried.

    Formula:  0.4 × density + 0.6 × coherence

    density:    min(1, chars_per_page / 200)
    coherence:  max(0, 1 − garbled_ratio × 50)

    Only the first 8 000 characters are sampled for garbled-word detection so
    that corruption concentrated in financial tables (early pages) is not
    diluted by large blocks of clean regulatory text later in the document.
    """
    if not text or page_count <= 0:
        return 0.0

    chars_per_page = len(text) / page_count
    density = min(1.0, max(0.0, chars_per_page / 200.0))

    sample_words = text[:8000].split()
    if sample_words:
        garbled = sum(1 for w in sample_words if _is_garbled_word(w))
        garbled_ratio = garbled / len(sample_words)
    else:
        garbled_ratio = 0.0

    coherence = max(0.0, 1.0 - garbled_ratio * _GARBLED_MULTIPLIER)
    return round(0.4 * density + 0.6 * coherence, 4)


# ---------------------------------------------------------------------------
# Extraction result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionResult:
    """Output of the multi-stage PDF extraction pipeline."""

    text: str
    extraction_method: Literal["native", "ocr"]
    quality_score: float
    ocr_attempted: bool
    page_count: int


# ---------------------------------------------------------------------------
# Internal PDF helpers
# ---------------------------------------------------------------------------


def _check_html_guard(path: Path) -> None:
    """Raise ValueError if the file is HTML disguised as a PDF.

    BSE's AnnualReport API sometimes returns HTML error pages with a .pdf URL.
    PyMuPDF opens them silently and yields empty text, hiding the failure.
    """
    header = path.read_bytes()[:64].lstrip()
    if header[:9].lower() == b"<!doctype" or header[:5].lower() == b"<html":
        raise ValueError(f"file appears to be HTML, not PDF (header={header[:24]!r})")


def _native_extract(path: Path) -> tuple[str, int]:
    """Extract text from a PDF using PyMuPDF's native text layer.

    Returns (text, page_count).  Never raises for valid PDFs.
    """
    import fitz  # type: ignore[import-untyped]

    doc = fitz.open(str(path))
    try:
        page_count = doc.page_count
        text = "\n".join(page.get_text() for page in doc)
        return text, page_count
    finally:
        doc.close()


def _find_tessdata() -> str:
    """Return the path to the Tesseract tessdata directory.

    Discovery order:
    1. fitz.get_tessdata() — checks TESSDATA_PREFIX env var, then 'where tesseract'.
    2. UB-Mannheim system-wide Windows install  (C:/Program Files/Tesseract-OCR/tessdata).
    3. UB-Mannheim user-scope Windows install   (%LOCALAPPDATA%/Programs/Tesseract-OCR/tessdata).

    As a side-effect, if a Tesseract install is found via fallback paths (2 or 3),
    its parent directory is prepended to os.environ['PATH'] so that PyMuPDF's
    internal subprocess calls to the tesseract binary succeed even when the
    installer did not update the current session's PATH.

    Raises RuntimeError if Tesseract cannot be found by any method.
    """
    import os

    import fitz

    try:
        return str(fitz.get_tessdata())
    except RuntimeError:
        pass

    candidates = [
        Path("C:/Program Files/Tesseract-OCR"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Tesseract-OCR",
    ]
    for install_dir in candidates:
        tessdata = install_dir / "tessdata"
        if tessdata.exists() and (tessdata / "eng.traineddata").exists():
            # Ensure the binary is reachable for PyMuPDF's subprocess calls.
            bin_dir = str(install_dir)
            if bin_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
            return str(tessdata)

    raise RuntimeError(
        "Tesseract is not installed or not on PATH.  "
        "Install from https://github.com/UB-Mannheim/tesseract/wiki "
        "or set TESSDATA_PREFIX to the tessdata directory."
    )


def _ocr_extract(path: Path, page_count: int) -> str:
    """Extract text by rendering each PDF page to a 300 DPI image and running Tesseract.

    Uses full=True to force whole-page OCR, which is required for PDFs with broken
    ToUnicode CMap encodings.  With full=False PyMuPDF would keep the garbled text as
    "legible" (it contains real characters, just wrong ones) and only OCR areas that
    produce U+FFFD — which broken-font PDFs never produce.

    Raises RuntimeError if Tesseract is not installed.
    """
    import fitz

    tessdata = _find_tessdata()
    doc = fitz.open(str(path))
    try:
        pages_text: list[str] = []
        for page in doc:
            tp = page.get_textpage_ocr(
                language="eng", dpi=300, full=True, tessdata=tessdata
            )
            pages_text.append(fitz.utils.get_text(page, "text", textpage=tp))
        return "\n".join(pages_text)
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Public PDF extraction entry point
# ---------------------------------------------------------------------------


def extract_pdf(path: Path) -> ExtractionResult:
    """Multi-stage PDF text extraction with automatic quality-based OCR fallback.

    Stage 1 — HTML guard: immediately rejects HTML pages disguised as PDFs.
    Stage 2 — Native:     PyMuPDF text-layer extraction (fast, always attempted).
    Stage 3 — Quality:    Objective score; if below QUALITY_THRESHOLD → Stage 4.
    Stage 4 — OCR:        Tesseract via PyMuPDF render→OCR (only when needed).

    If Tesseract is not installed, Stage 4 is skipped and the native result is
    returned with its (low) quality score and ``ocr_attempted=False``.  Analyzers
    can inspect ``quality_score`` to adjust their confidence accordingly.

    Raises:
        ValueError: if the file is HTML, not a PDF.
        Any fitz error: propagated so the caller can record status='failed'.
    """
    _check_html_guard(path)

    # Stage 2 — native extraction.
    native_text, page_count = _native_extract(path)
    native_score = score_text_quality(native_text, page_count)

    if native_score >= QUALITY_THRESHOLD:
        return ExtractionResult(
            text=native_text,
            extraction_method="native",
            quality_score=native_score,
            ocr_attempted=False,
            page_count=page_count,
        )

    # Stage 4 — OCR fallback.
    try:
        ocr_text = _ocr_extract(path, page_count)
        ocr_score = score_text_quality(ocr_text, page_count)
        # Use OCR result only when it's actually better.
        if ocr_score >= native_score:
            return ExtractionResult(
                text=ocr_text,
                extraction_method="ocr",
                quality_score=ocr_score,
                ocr_attempted=True,
                page_count=page_count,
            )
        # OCR didn't help (e.g., clean-looking image but bad result) — keep native.
        return ExtractionResult(
            text=native_text,
            extraction_method="native",
            quality_score=native_score,
            ocr_attempted=True,
            page_count=page_count,
        )
    except Exception:  # noqa: BLE001  (Tesseract missing, crash, etc.)
        # Graceful degradation: return native text with low quality score.
        # The caller stores ocr_attempted=True so operators know OCR was needed
        # but unavailable.
        return ExtractionResult(
            text=native_text,
            extraction_method="native",
            quality_score=native_score,
            ocr_attempted=True,
            page_count=page_count,
        )


# ---------------------------------------------------------------------------
# Plain-text extractors (non-PDF)
# ---------------------------------------------------------------------------


def _read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# Legacy single-function PDF extractor kept for backward compatibility.
# KnowledgeBase.parse() uses extract_pdf() directly for PDFs; _EXTRACTORS
# is used only for non-PDF formats and for monkeypatching in legacy tests.
def _extract_pdf_text(path: Path) -> str:
    result = extract_pdf(path)
    return result.text


_EXTRACTORS: dict[str, Callable[[Path], str]] = {
    "csv": _read_utf8,
    "htm": _read_utf8,
    "html": _read_utf8,
    "json": _read_utf8,
    "pdf": _extract_pdf_text,
    "txt": _read_utf8,
    "xml": _read_utf8,
}
