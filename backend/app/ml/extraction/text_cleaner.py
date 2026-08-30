"""Resume text cleaning. Pure string transformations — no DB, no HTTP.

Pipeline order is deliberate, each step depends on something the next step
would destroy:
    1. repair_hyphenated_linebreaks — needs literal "\\n" positions intact.
    2. strip_headers_and_footers    — needs page boundaries (PAGE_BREAK)
                                       intact, before whitespace collapsing
                                       erases where one page ends.
    3. normalize_whitespace          — collapses everything, including any
                                       leftover PAGE_BREAK markers; runs last.

No step here reorders lines, pages, or sections — extraction order (top to
bottom per page, pages in original order) passes through untouched. That is
what "section order preserved" means: an absence of reordering, not an
active transformation.
"""
import re

from app.ml.extraction.text_extractor import PAGE_BREAK

_HYPHEN_LINEBREAK = re.compile(r"([a-zA-Z])-\n([a-zA-Z])")
_HORIZONTAL_WHITESPACE = re.compile(r"[ \t\xa0]+")
_DIGIT_RUN = re.compile(r"\d+")
_WHITESPACE_RUN = re.compile(r"\s+")

# How many lines from each end of a page count as "edge" positions for
# header/footer detection.
_EDGE_WINDOW = 2
# A line longer than this is real body content, never a header/footer.
_MAX_HEADER_FOOTER_LENGTH = 100


def repair_hyphenated_linebreaks(text: str) -> str:
    """Joins a word wrapped across a line break with a trailing hyphen, e.g.
    "informa-\\ntion" -> "information". Restricted to letters on both sides
    of the hyphen so it never touches a real dash before a capitalized word
    ("2023-\\nPresent") or between digits ("100-\\n200").
    """
    return _HYPHEN_LINEBREAK.sub(r"\1\2", text)


def _normalize_for_comparison(line: str) -> str:
    key = line.strip().lower()
    key = _DIGIT_RUN.sub("#", key)  # "Page 1 of 3" and "Page 2 of 3" -> same key
    return _WHITESPACE_RUN.sub(" ", key)


def strip_headers_and_footers(text: str) -> str:
    """Removes lines that repeat at the top/bottom edge of most pages of a
    multi-page PDF (a running header, "Page N of M"). Three independent
    guards keep this from ever touching real content:
      - position: only the first/last _EDGE_WINDOW lines of a page are
        candidates at all — a skill or company name repeated in the body
        text never qualifies no matter how often it appears.
      - frequency: a line must repeat at that edge position on most pages,
        not just twice by coincidence.
      - length: anything over _MAX_HEADER_FOOTER_LENGTH characters is
        treated as body content, never a header/footer.
    A no-op for DOCX (no PAGE_BREAK marker ever appears — python-docx never
    hands us header/footer text in the first place) and for single-page PDFs
    (nothing to compare across).
    """
    if PAGE_BREAK not in text:
        return text

    pages = [page.strip("\n").split("\n") for page in text.split(PAGE_BREAK)]
    if len(pages) < 2:
        return text

    edge_counts: dict[str, int] = {}
    for lines in pages:
        edge_lines = lines[:_EDGE_WINDOW] + lines[-_EDGE_WINDOW:]
        seen_on_this_page: set[str] = set()
        for line in edge_lines:
            stripped = line.strip()
            if not stripped or len(stripped) > _MAX_HEADER_FOOTER_LENGTH:
                continue
            key = _normalize_for_comparison(stripped)
            if key and key not in seen_on_this_page:
                edge_counts[key] = edge_counts.get(key, 0) + 1
                seen_on_this_page.add(key)

    # ~60% of pages, minimum 2 — a two-page resume needs the line on both
    # pages, a longer one tolerates it missing from a page or two.
    threshold = max(2, (len(pages) * 3 + 4) // 5)
    repeated_keys = {key for key, count in edge_counts.items() if count >= threshold}
    if not repeated_keys:
        return text

    cleaned_pages = []
    for lines in pages:
        edge_cutoff = len(lines) - _EDGE_WINDOW
        kept = [
            line
            for idx, line in enumerate(lines)
            if not (
                (idx < _EDGE_WINDOW or idx >= edge_cutoff)
                and line.strip()
                and _normalize_for_comparison(line.strip()) in repeated_keys
            )
        ]
        cleaned_pages.append("\n".join(kept))

    return f"\n{PAGE_BREAK}\n".join(cleaned_pages)


def normalize_whitespace(text: str) -> str:
    """Collapses horizontal whitespace runs to a single space, strips
    trailing/leading whitespace per line, collapses any run of blank lines
    to exactly one, and converts leftover PAGE_BREAK markers to a paragraph
    break.
    """
    text = text.replace(PAGE_BREAK, "\n")
    lines = [_HORIZONTAL_WHITESPACE.sub(" ", line).strip() for line in text.split("\n")]

    collapsed: list[str] = []
    in_blank_run = False
    for line in lines:
        if line == "":
            if not in_blank_run:
                collapsed.append(line)
            in_blank_run = True
        else:
            collapsed.append(line)
            in_blank_run = False

    return "\n".join(collapsed)


def clean_text(raw_text: str) -> str:
    text = repair_hyphenated_linebreaks(raw_text)
    text = strip_headers_and_footers(text)
    text = normalize_whitespace(text)
    return text.strip()
