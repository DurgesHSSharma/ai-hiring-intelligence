"""Shared text-matching helpers for ml/ extraction and skill code. Pure
string/regex utilities — no DB, no HTTP — so both app/ml/skills/ and
app/ml/extraction/ can import this (Rules.md 4.2: ml/ may import utils/).
"""
import re

# Characters that block a match boundary, in addition to alphanumerics.
# Plain \b is not enough here: \b treats "+" and "#" as non-word, so
# \bC\b would (wrongly) match the "C" inside "C++" or "C#" — there IS a
# word boundary between "C" and "+"/"#" under \b's definition. Adding
# them to the blocking set closes that hole. "." is deliberately NOT
# included: doing so would block a real match at the end of a sentence
# ("Fluent in C.", "Skilled in C++."), which is a far more common shape
# than the false positive it would prevent. Verified empirically for
# both the desired matches (C++, C#, .NET, node.js) and the required
# non-matches (R in React, Go in Google, C in C++) before this was relied
# on anywhere — see skill_matcher.py.
_BOUNDARY_BLOCK = "A-Za-z0-9+#"


def compile_boundary_pattern(literal: str) -> re.Pattern[str]:
    """Compiles a case-insensitive, boundary-safe regex for one literal
    phrase. Internal whitespace matches one-or-more whitespace characters
    (so "machine learning" tolerates a double space or a line wrap), and
    the match cannot be preceded or followed by an alphanumeric, "+", or
    "#" character — see _BOUNDARY_BLOCK above for why plain \\b fails
    this for symbol-suffixed skill names.
    """
    escaped = re.escape(literal).replace(r"\ ", r"\s+")
    pattern = rf"(?<![{_BOUNDARY_BLOCK}]){escaped}(?![{_BOUNDARY_BLOCK}])"
    return re.compile(pattern, re.IGNORECASE)
