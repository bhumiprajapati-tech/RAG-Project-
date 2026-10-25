"""Bounded PDF text extraction with a secondary parser fallback."""

from __future__ import annotations

from io import BytesIO

import pdfplumber
from pdfminer.pdfexceptions import PDFException
from pdfminer.pdfparser import PDFSyntaxError
from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError

from config import MAX_PDF_PAGES, MAX_RESUME_CHARS, MAX_UPLOAD_BYTES


class PDFParseError(ValueError):
    """Raised when an uploaded file cannot safely be read as a PDF."""


def extract_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes:
        raise PDFParseError("The uploaded file is empty.")
    if len(pdf_bytes) > MAX_UPLOAD_BYTES:
        raise PDFParseError("The PDF exceeds the 10 MB upload limit.")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise PDFParseError("The uploaded file does not have a valid PDF header.")

    extracted = ""
    errors: list[str] = []
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            if len(pdf.pages) > MAX_PDF_PAGES:
                raise PDFParseError(f"PDFs are limited to {MAX_PDF_PAGES} pages.")
            extracted = "\n".join(
                page.extract_text() or "" for page in pdf.pages
            ).strip()
    except PDFParseError:
        raise
    except (PDFException, PDFSyntaxError, OSError, ValueError, EOFError) as exc:
        errors.append(f"pdfplumber: {exc}")

    if not extracted:
        try:
            reader = PdfReader(BytesIO(pdf_bytes), strict=False)
            if len(reader.pages) > MAX_PDF_PAGES:
                raise PDFParseError(f"PDFs are limited to {MAX_PDF_PAGES} pages.")
            extracted = "\n".join(
                page.extract_text() or "" for page in reader.pages
            ).strip()
        except PDFParseError:
            raise
        except (
            PdfReadError,
            PdfStreamError,
            OSError,
            ValueError,
            EOFError,
            KeyError,
            TypeError,
        ) as exc:
            errors.append(f"pypdf: {exc}")

    if not extracted:
        detail = "; ".join(errors) or "No extractable text was found."
        raise PDFParseError(
            "Could not extract text. The PDF may be scanned or encrypted. "
            f"Details: {detail[:500]}"
        )
    if len(extracted) > MAX_RESUME_CHARS:
        extracted = extracted[:MAX_RESUME_CHARS]
    return extracted
