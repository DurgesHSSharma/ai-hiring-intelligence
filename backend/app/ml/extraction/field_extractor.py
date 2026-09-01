"""Structured field extraction from cleaned resume text (PRD F3.5,
Phases.md Phase 5). Pure — no DB, no HTTP (Rules.md 4.2). Every function
returns None (never a placeholder like "" or 0) when it cannot find a
confident answer — an absent value is not the same claim as a found-empty
one, and Candidate.email/phone/education/experience_years are all
nullable specifically so this distinction survives into the database
(see models/candidate.py, Memory.md decision 18).

spaCy's en_core_web_sm is used only as a fallback (name PERSON entity,
experience DATE-entity year span) when the cheaper regex/heading-based
approach finds nothing — loaded once as a lazy singleton, never per call
(Rules.md 4.6).
"""
import json
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.utils.text import compile_boundary_pattern

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_EDUCATION_PATH = _DATA_DIR / "education.json"

_NLP = None  # lazy singleton, see _get_nlp()


def _get_nlp():
    global _NLP
    if _NLP is None:
        import spacy

        _NLP = spacy.load("en_core_web_sm")
    return _NLP


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def extract_email(text: str) -> str | None:
    match = _EMAIL_PATTERN.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,;:")


# ---------------------------------------------------------------------------
# Phone
# ---------------------------------------------------------------------------

# Deliberately format-agnostic rather than hardcoding "3-3-4" grouping: that
# shape only covers US/Canada numbers and would miss e.g. Indian mobile
# numbers written as "98765 43210" (5+5). Instead this matches any
# contiguous run of digits and phone punctuation, then validates by digit
# COUNT (7-15, the E.164 range) rather than by internal grouping. Known
# limitation, documented in docs/EVALUATION.md: a 9-digit ZIP+4 or a
# similarly-shaped digit run could false-positive; the labelled eval set
# is what would surface how often that actually happens.
_PHONE_CANDIDATE = re.compile(r"(?<!\d)(\(?\+?\d[\d\s().-]{6,18}\d\)?)(?!\d)")
# Excludes the one common false-positive shape checked for explicitly: a
# bare "YYYY-YYYY" employment year range, which is otherwise digit-count-
# compatible with a phone number.
_YEAR_RANGE_LOOKALIKE = re.compile(r"^(19|20)\d{2}\s*[-–—]\s*(19|20)\d{2}$")


def extract_phone(text: str) -> str | None:
    for match in _PHONE_CANDIDATE.finditer(text):
        candidate = match.group(0).strip()
        if _YEAR_RANGE_LOOKALIKE.match(candidate):
            continue
        digits = re.sub(r"\D", "", candidate)
        if 7 <= len(digits) <= 15:
            return re.sub(r"\s+", " ", candidate)
    return None


# ---------------------------------------------------------------------------
# Name — first-lines heuristic, spaCy PERSON fallback
# ---------------------------------------------------------------------------

_NAME_LINE_PATTERN = re.compile(r"^[A-Z][A-Za-z'.-]+(\s+[A-Z][A-Za-z'.-]+){1,3}$")
_NAME_LINE_SCAN_LIMIT = 5
_NON_NAME_KEYWORDS = {
    "resume", "résumé", "curriculum vitae", "cv", "summary", "objective",
    "profile", "contact", "contact information", "experience", "education",
    "skills", "projects", "certifications", "references",
}
# Stripped from the start of a candidate line before the shape check runs —
# "Dr. Nkechi Obi" should read as the name "Nkechi Obi", not fail to match
# anything useful downstream. Case-insensitive; requires trailing
# whitespace (with or without a period) so it never touches a name that
# genuinely starts with these letters ("Erika" is not "Er" + a name).
_HONORIFIC_PREFIX = re.compile(r"^(?:dr|prof|mr|ms|mrs|er)\.?\s+", re.IGNORECASE)


def extract_name(text: str) -> str | None:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    for raw_line in lines[:_NAME_LINE_SCAN_LIMIT]:
        line = _HONORIFIC_PREFIX.sub("", raw_line, count=1)
        if "@" in line or any(ch.isdigit() for ch in line):
            continue
        lower = line.lower().rstrip(":")
        if lower in _NON_NAME_KEYWORDS or len(line) > 60:
            continue

        # Phase 13 item A5/A3 — a layout defect can weld a recognized
        # section heading onto the same line as the candidate's own name
        # (Phase 5 decision 27, e.g. "Wei Chen EXPERIENCE"). Strip a
        # welded heading suffix before the shape check below, reusing the
        # same word-boundary-safe, short-line-gated detection
        # _extract_section() uses for section boundaries, so the heading
        # is never returned as part of the name.
        welded = _find_welded_heading_split(line, _ALL_HEADINGS)
        if welded is not None:
            line = welded[0]

        # The first line that survives the structural disqualifiers above
        # is the heuristic's one candidate. If it doesn't look like a name,
        # stop here rather than keep scanning later lines for a same-shaped
        # match — a job title ("Network Support Specialist") is exactly as
        # "2-4 capitalized words" as a real name, and silently accepting
        # one is worse than falling through to the NER fallback below,
        # which is a genuinely different signal rather than another guess
        # at the same shape.
        if _NAME_LINE_PATTERN.match(line):
            return line
        break

    # Restricted to the first ~500 chars so a PERSON entity mentioned later
    # (a reference, a former manager named in a bullet) is never mistaken
    # for the candidate's own name.
    doc = _get_nlp()(text[:500])
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            return ent.text
    return None


# ---------------------------------------------------------------------------
# Section isolation — shared by education, experience, projects, certifications
# ---------------------------------------------------------------------------

_EXPERIENCE_HEADINGS = [
    "experience", "work experience", "professional experience",
    "employment history", "work history", "employment",
    # Single/short-word variants common on academic, Commonwealth-style,
    # and executive-format resumes — not specific to any one resume in
    # any evaluation set; "appointments" is the standard heading on
    # academic/clinical CVs, "positions" and "career history" are common
    # alternate headings on general and executive resumes.
    "appointments", "positions", "career history",
]
_PROJECT_HEADINGS = [
    "projects", "personal projects", "key projects", "academic projects",
    "notable projects",
]
_CERTIFICATION_HEADINGS = [
    "certifications", "certificates", "licenses",
    "licenses and certifications", "professional certifications",
]
_EDUCATION_HEADINGS = [
    "education", "academic background", "academic qualifications",
    "educational background",
]
_OTHER_HEADINGS = [
    "skills", "technical skills", "summary", "objective", "profile",
    "contact", "references", "awards", "publications", "languages",
]
_ALL_HEADINGS = frozenset(
    _EXPERIENCE_HEADINGS + _PROJECT_HEADINGS + _CERTIFICATION_HEADINGS
    + _EDUCATION_HEADINGS + _OTHER_HEADINGS
)
# Every individual word appearing in any recognized heading phrase (e.g.
# "work", "history" from "work history") — used by is_heading_word() below
# to keep a heading that layout corruption welded onto adjacent content
# (Phase 5 decision 27, e.g. "Wei Chen EXPERIENCE") from being mistaken for
# actual resume content by a caller scanning unscoped text.
_ALL_HEADING_WORDS = frozenset(word for phrase in _ALL_HEADINGS for word in phrase.split())

_TRAILING_HEADING_PUNCTUATION = re.compile(r"[:\-–—]+$")


def is_heading_word(word: str) -> bool:
    """True if `word` (any case) is one of the words making up a
    recognized section heading, so a caller can exclude it from anything
    it is treating as free-text resume content.
    """
    return word.lower() in _ALL_HEADING_WORDS


def _normalize_heading(line: str) -> str:
    return _TRAILING_HEADING_PUNCTUATION.sub("", line.strip()).strip().lower()


# Phase 13 item A5/A1 — a two-column PDF layout can weld a section heading
# onto the same line as adjacent content (Phase 5 decision 27, e.g.
# "Wei Chen EXPERIENCE", "CONTACT EXPERIENCE"), which defeats the exact
# full-line match above. Gated to short lines only, so an ordinary sentence
# that happens to end in a heading word ("...gained valuable experience.")
# is never mistaken for a heading line — a real welded heading in this
# corpus is always a name/short-heading pair, not a full sentence.
_WELDED_HEADING_MAX_WORDS = 6


def _find_welded_heading_split(
    line: str, heading_variants: "frozenset[str] | list[str]"
) -> tuple[str, str] | None:
    """If a short line's trailing word(s) exactly match one of
    `heading_variants`, word-for-word (case-insensitive, never a substring
    match — "R" inside "React" is exactly the class of bug this avoids,
    the same discipline skill_matcher.py already uses for skill names),
    returns (prefix, matched_phrase): prefix is everything before the
    matched heading, in the line's original casing/spacing — e.g.
    ("Wei Chen EXPERIENCE", _EXPERIENCE_HEADINGS) -> ("Wei Chen",
    "experience"). None if the line doesn't end with a recognized heading
    at all, is too long to plausibly be a welded heading rather than a
    real sentence, or nothing would be left after removing it.
    """
    raw_words = line.strip().split()
    if not raw_words or len(raw_words) > _WELDED_HEADING_MAX_WORDS:
        return None
    words = list(raw_words)
    words[-1] = _TRAILING_HEADING_PUNCTUATION.sub("", words[-1])
    lower_words = [w.lower() for w in words]

    for phrase in heading_variants:
        phrase_words = phrase.split()
        n = len(phrase_words)
        if 0 < n < len(lower_words) and lower_words[-n:] == phrase_words:
            prefix = " ".join(raw_words[: len(raw_words) - n]).strip()
            if prefix:
                return prefix, phrase
    return None


def _matches_heading(line: str, heading_variants: "frozenset[str] | list[str]") -> bool:
    """True if `line` is a recognized section heading — either the whole
    line, normalized, exactly equals one of `heading_variants` (the
    original, always-supported case), or a short line ends with a
    recognized heading phrase welded onto adjacent content (Phase 13 A1,
    see _find_welded_heading_split above). Does not attempt any general
    two-column body-text reordering or gutter/column detection — this
    only recognizes a heading *word*, wherever a full-line match already
    would have, plus the one narrow welded-suffix case.
    """
    if _normalize_heading(line) in heading_variants:
        return True
    return _find_welded_heading_split(line, heading_variants) is not None


def _find_section_bounds(
    lines: list[str], heading_variants: "frozenset[str] | list[str]"
) -> tuple[int, int] | None:
    """Returns (start_idx, end_idx) — the half-open line-index range of the
    section body (excluding the heading line itself) for the first
    matching heading in `heading_variants`. end_idx is the index of the
    next recognized heading (any category) or len(lines). None if no
    matching heading line is found at all.

    Welded-heading tolerance (_matches_heading, Phase 13 A1) applies only
    to finding where the target section STARTS, not to finding where it
    ends — deliberately. Both real observed cases (Phase 5 decision 27:
    "Wei Chen EXPERIENCE", "CONTACT EXPERIENCE") weld a heading onto the
    very first line of the section, where welded-tolerance is exactly
    what's needed; their own section END is found via a clean, unwelded
    heading line either way. Applying the same tolerance to the END search
    was tried and reverted: the synthetic regression suite has a
    (deliberately adversarial) case where a heading is welded onto the END
    of an experience-entry title line, with that entry's own employment
    date on the very next line — recognizing the weld there as an end
    boundary cuts the section off before its own date range, misreading a
    line that is genuinely still part of the section as if it started the
    next one. End-boundary detection stays exact-match-only to avoid that.
    """
    start_idx = None
    for i, line in enumerate(lines):
        if _matches_heading(line, heading_variants):
            start_idx = i + 1
            break
    if start_idx is None:
        return None

    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if _normalize_heading(lines[j]) in _ALL_HEADINGS:
            end_idx = j
            break
    return start_idx, end_idx


def _extract_section(text: str, heading_variants: list[str]) -> str | None:
    """Returns the text between a matching heading line and the next
    recognized heading (any category) or end of text. None if no matching
    heading line is found at all — callers decide their own fallback.
    """
    lines = text.split("\n")
    bounds = _find_section_bounds(lines, heading_variants)
    if bounds is None:
        return None
    start_idx, end_idx = bounds
    section = "\n".join(lines[start_idx:end_idx]).strip()
    return section or None


# ---------------------------------------------------------------------------
# Education — degree-pattern matching against data/education.json's ladder
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_education_ladder() -> list[dict]:
    raw = json.loads(_EDUCATION_PATH.read_text(encoding="utf-8"))
    return raw["ladder"]


def extract_education(text: str) -> tuple[str | None, int | None]:
    """Returns (display_name, ordinal_level). Highest degree mentioned
    wins when more than one appears (a resume listing both a bachelor's
    and a master's is a master's-level candidate).
    """
    search_text = _extract_section(text, _EDUCATION_HEADINGS) or text
    best_level: int | None = None
    best_name: str | None = None
    for entry in _load_education_ladder():
        for pattern_str in entry["patterns"]:
            if compile_boundary_pattern(pattern_str).search(search_text):
                if best_level is None or entry["level"] > best_level:
                    best_level = entry["level"]
                    best_name = entry["display_name"]
                break
    return (best_name, best_level)


# ---------------------------------------------------------------------------
# Experience years — date-range parsing with an NER fallback
# ---------------------------------------------------------------------------

_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
# Longest names first so alternation tries "march" before "mar" — otherwise
# "mar" would match and consume just those 3 letters, and the mandatory
# following-year check would then fail against the leftover "ch 2020".
_MONTH_ALTERNATION = "|".join(sorted(_MONTHS.keys(), key=len, reverse=True))
_YEAR = r"(?:19|20)\d{2}"
_DATE_TOKEN = rf"(?:(?:{_MONTH_ALTERNATION})\.?\s+{_YEAR}|\d{{1,2}}[/\-]{_YEAR}|{_YEAR})"
_PRESENT_WORDS = r"present|current|currently|now|ongoing|till date|to date"

_RANGE_PATTERN = re.compile(
    rf"(?P<start>{_DATE_TOKEN})\s*(?:-|–|—|to|until)\s*"
    rf"(?P<end>{_DATE_TOKEN}|{_PRESENT_WORDS})",
    re.IGNORECASE,
)
_YEAR_IN_TOKEN = re.compile(_YEAR)
_NUMERIC_MONTH_YEAR = re.compile(rf"(\d{{1,2}})[/\-]({_YEAR})")
_MONTH_NAME_IN_TOKEN = re.compile(rf"({_MONTH_ALTERNATION})", re.IGNORECASE)
_PRESENT_WORDS_FULL = re.compile(rf"^(?:{_PRESENT_WORDS})$", re.IGNORECASE)


def _parse_date_token(token: str, *, is_end: bool) -> tuple[int, int] | None:
    """Returns (year, month). A year-only token assumes January for a
    start date and December for an end date — the whole-calendar-year
    approximation is deliberate and documented, not an oversight.
    """
    token = token.strip()
    year_match = _YEAR_IN_TOKEN.search(token)
    if not year_match:
        return None
    year = int(year_match.group(0))

    numeric_match = _NUMERIC_MONTH_YEAR.match(token)
    if numeric_match:
        month = int(numeric_match.group(1))
        if 1 <= month <= 12:
            return (year, month)

    month_match = _MONTH_NAME_IN_TOKEN.search(token)
    if month_match:
        return (year, _MONTHS[month_match.group(1).lower()])

    return (year, 12 if is_end else 1)


def _month_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


def _parse_date_intervals(text: str, *, as_of: date) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    for match in _RANGE_PATTERN.finditer(text):
        start = _parse_date_token(match.group("start"), is_end=False)
        end_token = match.group("end")
        if _PRESENT_WORDS_FULL.match(end_token.strip()):
            end = (as_of.year, as_of.month)
        else:
            end = _parse_date_token(end_token, is_end=True)
        if start is None or end is None:
            continue
        start_idx, end_idx = _month_index(*start), _month_index(*end)
        if end_idx < start_idx:
            continue  # nonsensical range (e.g. a mis-parsed token) — discard, don't guess
        intervals.append((start_idx, end_idx))
    return intervals


def _sum_intervals(intervals: list[tuple[int, int]]) -> float:
    """Merges overlapping AND contiguous intervals (one role ending March
    2019, the next starting April 2019, is continuous employment with no
    gap) but never bridges a real gap between separate merged groups —
    total is the sum of merged-interval lengths, not max-minus-min.
    """
    ordered = sorted(intervals)
    merged: list[list[int]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    total_months = sum(end - start + 1 for start, end in merged)
    return round(total_months / 12, 1)


def _experience_years_from_ner(text: str) -> float | None:
    """Weaker fallback used only when regex range-parsing finds nothing at
    all: the span between the earliest and latest 4-digit year spaCy
    tags as part of a DATE entity. Documented as an approximation — it
    has no notion of gaps or overlaps, unlike the primary path.
    """
    doc = _get_nlp()(text)
    years: set[int] = set()
    for ent in doc.ents:
        if ent.label_ != "DATE":
            continue
        match = _YEAR_IN_TOKEN.search(ent.text)
        if match:
            years.add(int(match.group(0)))
    if len(years) < 2:
        return None
    return round(float(max(years) - min(years)), 1)


def _text_excluding_education_section(text: str) -> str:
    """Phase 13 item A5/A2 — a safety net for extract_experience_years()'s
    whole-text fallback below, used only when no EXPERIENCE section can be
    found at all (even with _extract_section()'s welded-heading tolerance,
    A1). Removes a successfully detected EDUCATION section's own lines
    (heading line included) before the fallback scans for date ranges, so
    an education date range (e.g. "2012 - 2016") can never be counted as
    employment. A no-op (returns text unchanged) when no EDUCATION section
    is found — there is nothing safe to remove.
    """
    lines = text.split("\n")
    bounds = _find_section_bounds(lines, _EDUCATION_HEADINGS)
    if bounds is None:
        return text
    start_idx, end_idx = bounds
    remaining = lines[: start_idx - 1] + lines[end_idx:]
    return "\n".join(remaining)


def extract_experience_years(text: str, *, as_of: date | None = None) -> float | None:
    """Returns None — never 0.0 — when nothing parses. A computed 0.something
    (a role that started last month) is a real answer; None means "could
    not tell," and those are not interchangeable.

    Scoped to the EXPERIENCE section when a heading is found, to avoid
    counting an EDUCATION section's own years (e.g. "2015-2019" as
    college attendance). Falls back to scanning the whole resume — minus
    any detected EDUCATION section (Phase 13 A2, see
    _text_excluding_education_section above) — only when no EXPERIENCE
    heading is found at all — documented risk: that fallback path can
    still overcount by picking up some other non-employment date range
    (e.g. a certification date) the EDUCATION exclusion doesn't cover.
    """
    as_of = as_of or date.today()
    section_text = _extract_section(text, _EXPERIENCE_HEADINGS)
    intervals = _parse_date_intervals(section_text, as_of=as_of) if section_text else []
    if not intervals:
        intervals = _parse_date_intervals(_text_excluding_education_section(text), as_of=as_of)
    if intervals:
        return _sum_intervals(intervals)
    return _experience_years_from_ner(text)


def extract_experience_section_text(text: str) -> str | None:
    """Public wrapper around the same EXPERIENCE-heading section isolator
    extract_experience_years() already depends on, so a caller outside
    this module (interview_service.py's grounding filter) can scope its
    own scan to the same section without re-implementing heading
    detection. None if no EXPERIENCE heading is found — same contract as
    _extract_section().
    """
    return _extract_section(text, _EXPERIENCE_HEADINGS)


def find_date_ranges(text: str) -> list[re.Match[str]]:
    """Public wrapper around the same date-range pattern
    extract_experience_years() uses, so a caller can locate employment
    date-range spans (e.g. to find the employer name sharing a line with
    one) without a second, potentially drifting date regex.
    """
    return list(_RANGE_PATTERN.finditer(text))


# ---------------------------------------------------------------------------
# Projects / certifications — section heading extraction, one entry per line
# ---------------------------------------------------------------------------

_BULLET_PREFIX = re.compile(r"^[\-*•▪●○]\s*")


def _split_section_entries(section: str) -> list[str]:
    lines = [line.strip() for line in section.split("\n") if line.strip()]
    cleaned = [_BULLET_PREFIX.sub("", line).strip() for line in lines]
    return [line for line in cleaned if line]


def extract_projects(text: str) -> list[str]:
    section = _extract_section(text, _PROJECT_HEADINGS)
    return _split_section_entries(section) if section else []


def extract_certifications(text: str) -> list[str]:
    section = _extract_section(text, _CERTIFICATION_HEADINGS)
    return _split_section_entries(section) if section else []


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExtractedFields:
    name: str | None
    email: str | None
    phone: str | None
    education: str | None
    education_level: int | None
    experience_years: float | None
    projects: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)


def extract_all(text: str, *, as_of: date | None = None) -> ExtractedFields:
    """`as_of` defaults to real today's date for every production caller
    (resume_service.py never passes it) — it exists so tests can pin
    "Present"-relative experience calculations to a fixed date instead of
    silently drifting as real time passes.
    """
    education, education_level = extract_education(text)
    return ExtractedFields(
        name=extract_name(text),
        email=extract_email(text),
        phone=extract_phone(text),
        education=education,
        education_level=education_level,
        experience_years=extract_experience_years(text, as_of=as_of),
        projects=extract_projects(text),
        certifications=extract_certifications(text),
    )
