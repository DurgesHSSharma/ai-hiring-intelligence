"""Dictionary-based skill extraction (PRD F4.1-F4.3, Phases.md Phase 5).
Pure — no DB, no HTTP (Rules.md 4.2). Semantic fallback matching
(SkillSource.SEMANTIC, F4.4) is a Phase 7 addition, but lives in
ml/skills/skill_gap.py, not here — it's a skill-*gap* concern (comparing
a job's required skills against what a candidate already has), not a
skill-*extraction* one. Every match this module produces is, and stays,
SkillSource.DICTIONARY.

Known limitation, documented here and in docs/EVALUATION.md: a skill
whose canonical or alias form is also an ordinary English word ("Go",
"Spring", "R") can match inside unrelated prose ("Time to go home").
Word-boundary matching prevents cross-token false positives (R inside
React, Go inside Google) but cannot disambiguate word sense — that is
an inherent limit of dictionary matching, not a bug in the boundary
regex. Confirmed concretely for "go" during development.
"""
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.enums import SkillSource, SkillType
from app.utils.text import compile_boundary_pattern

_SKILLS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "skills.json"


@dataclass(frozen=True)
class MatchedSkill:
    canonical: str
    skill_type: SkillType
    source: SkillSource = SkillSource.DICTIONARY


@lru_cache(maxsize=1)
def _load_index() -> tuple[tuple, ...]:
    """Builds (compiled_pattern, canonical, skill_type) for every alias of
    every skill. Loaded once per process and cached — Rules.md 4.6's
    "loaded once, never per request" rule, applied to this static regex
    index the same way it applies to an ML model artefact.
    """
    raw = json.loads(_SKILLS_PATH.read_text(encoding="utf-8"))
    index = []
    for entry in raw["skills"]:
        canonical = entry["canonical"]
        skill_type = SkillType(entry["type"])
        for alias in entry["aliases"]:
            index.append((compile_boundary_pattern(alias), canonical, skill_type))
    return tuple(index)


def match_skills(text: str) -> list[MatchedSkill]:
    """Scans `text` against every known skill alias. Returns one
    MatchedSkill per canonical skill found (deduplicated across aliases —
    a resume mentioning both "JS" and "JavaScript" yields one match, not
    two), in the dictionary's original order. Empty text yields an empty
    list, never an error.
    """
    if not text:
        return []

    found: dict[str, SkillType] = {}
    for pattern, canonical, skill_type in _load_index():
        if canonical in found:
            continue
        if pattern.search(text):
            found[canonical] = skill_type

    return [MatchedSkill(canonical=c, skill_type=t) for c, t in found.items()]
