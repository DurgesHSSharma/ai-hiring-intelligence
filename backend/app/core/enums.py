"""Shared vocabulary for the whole schema. Plain stdlib Enum classes only —
no SQLAlchemy or Pydantic imports — so both models/ and schemas/ can import
from here without either one importing from the other (Rules.md 4.2 layer
table restricts models/ to "SQLAlchemy, base"; core/ sits below that
restriction as shared foundation, same as core/exceptions.py and
core/security.py).

Each member's `.value` is the lowercase snake string that is actually
persisted and sent over the wire (Architecture.md 9.6). The SQLAlchemy side
of that guarantee — making sure `.value` and not `.name` is what lands in
the database — lives in `models/base.py`'s `db_enum()` helper.
"""
from enum import Enum


class UserRole(str, Enum):
    RECRUITER = "recruiter"
    MANAGER = "manager"
    ANALYST = "analyst"
    ADMIN = "admin"


class JobSeniority(str, Enum):
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"


class JobStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class ApplicationStatus(str, Enum):
    NEW = "new"
    SHORTLISTED = "shortlisted"
    INTERVIEWED = "interviewed"
    SELECTED = "selected"
    REJECTED = "rejected"


class ParseStatus(str, Enum):
    PARSED = "parsed"
    PARTIAL = "partial"
    PARSE_FAILED = "parse_failed"


class SkillType(str, Enum):
    TECHNICAL = "technical"
    TOOL = "tool"
    SOFT = "soft"
    DOMAIN = "domain"


class SkillSource(str, Enum):
    DICTIONARY = "dictionary"
    SEMANTIC = "semantic"


class ScoringMethod(str, Enum):
    TFIDF = "tfidf"
    EMBEDDING = "embedding"


class QuestionCategory(str, Enum):
    TECHNICAL = "technical"
    PROJECT = "project"
    EXPERIENCE = "experience"
    SKILL_VERIFICATION = "skill_verification"
    BEHAVIORAL = "behavioral"


class QuestionDifficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ScoreBand(str, Enum):
    STRONG_MATCH = "strong_match"
    GOOD_MATCH = "good_match"
    MODERATE_MATCH = "moderate_match"
    WEAK_MATCH = "weak_match"
