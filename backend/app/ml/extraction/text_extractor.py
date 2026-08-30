"""Raw text extraction from resume bytes. Pure — no DB, no HTTP (Rules.md
4.2: ml/ may import stdlib and third-party ML only, not core/). Failures
raise TextExtractionError, a plain exception local to this module; the
service layer translates it into the domain RESUME_PARSE_FAILED code.
"""
import io

import pdfplumber
from docx import Document
# docx.Document (above) is a factory FUNCTION, not a class — isinstance()
# needs the real class, which lives here under a different name.
from docx.document import Document as _DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

# Marker joining pdfplumber's per-page text so text_cleaner.py can find page
# boundaries to detect repeated headers/footers. Never appears in real
# extracted text, and normalize_whitespace() strips any that survive.
PAGE_BREAK = "\f"


class TextExtractionError(Exception):
    """Raised when a file's declared format matches (it passed magic-byte
    validation) but its internal structure can't actually be parsed."""


def extract_text(content: bytes, extension: str) -> str:
    """Extracts raw text in original reading order. Raises
    TextExtractionError if the file is corrupt/unparseable; returns "" (not
    an error) if the file parses cleanly but has no text layer — that
    distinction matters, because an image-only PDF is a length-guard
    failure downstream, not a parse failure.
    """
    if extension == ".pdf":
        return _extract_pdf_text(content)
    if extension == ".docx":
        return _extract_docx_text(content)
    raise TextExtractionError(f"No extractor registered for extension {extension!r}.")


def _extract_pdf_text(content: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = [(page.extract_text() or "") for page in pdf.pages]
    except Exception as exc:
        raise TextExtractionError(f"Unable to parse PDF: {exc}") from exc
    return f"\n{PAGE_BREAK}\n".join(pages)


def _iter_block_items(parent):
    """Yields Paragraph/Table objects from `parent` (a Document, or a table
    cell when called recursively) in true document order.

    document.paragraphs alone silently skips every table — tables live in a
    separate part of the document tree, not interleaved into .paragraphs —
    which is a common way resume templates build a 2-column sidebar layout.
    That made a candidate's entire sidebar column vanish with no error
    anywhere, worse than the PDF column-interleaving bug: silent data loss
    instead of visible scrambling. This is the standard recipe for reading
    a python-docx document in actual document order.
    """
    parent_elm = parent.element.body if isinstance(parent, _DocxDocument) else parent._tc
    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def _block_lines(container) -> list[str]:
    lines: list[str] = []
    for block in _iter_block_items(container):
        if isinstance(block, Paragraph):
            lines.append(block.text)
        else:
            # Row-then-cell order — correct for the common case of a single-
            # row, two-cell table used purely to fake a 2-column layout.
            # Recurses so a table nested inside a cell is also picked up.
            for row in block.rows:
                for cell in row.cells:
                    lines.extend(_block_lines(cell))
    return lines


def _extract_docx_text(content: bytes) -> str:
    # Word headers/footers live in separate section.header/section.footer
    # parts, never reached by walking the body — so DOCX needs no
    # header/footer-stripping step downstream, unlike PDF.
    try:
        document = Document(io.BytesIO(content))
        lines = _block_lines(document)
    except Exception as exc:
        raise TextExtractionError(f"Unable to parse DOCX: {exc}") from exc
    return "\n".join(lines)
