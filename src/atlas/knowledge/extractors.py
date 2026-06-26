from collections.abc import Callable
from pathlib import Path


def _read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_pdf_text(path: Path) -> str:
    import fitz  # type: ignore[import-untyped]  # pymupdf

    doc = fitz.open(str(path))
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


_EXTRACTORS: dict[str, Callable[[Path], str]] = {
    "csv":  _read_utf8,
    "htm":  _read_utf8,
    "html": _read_utf8,
    "json": _read_utf8,
    "pdf":  _extract_pdf_text,
    "txt":  _read_utf8,
    "xml":  _read_utf8,
}
