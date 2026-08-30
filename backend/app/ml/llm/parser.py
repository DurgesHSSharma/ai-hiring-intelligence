"""Strict JSON parse plus Pydantic schema validation for LLM output
(Rules.md 4.7, F8.5). Pure — no DB, no HTTP (Rules.md 4.2's layer table).

LLMOutputError is a module-local exception, not a core/exceptions.py type:
ml/ must not import core/ (Rules.md 4.2), the same precedent as
ml/extraction/text_extractor.py's TextExtractionError. interview_service.py
is the only caller and translates a second failure into
LLMError(code="LLM_INVALID_OUTPUT").
"""
import json
import re

from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

from app.core.enums import QuestionCategory, QuestionDifficulty


class LLMOutputError(Exception):
    """Raised for invalid JSON or a schema mismatch. interview_service.py
    treats both the same way — Rules.md 5.4: "Strict JSON parse; on parse
    failure, one repair attempt; on second failure, raise
    LLM_INVALID_OUTPUT" — read as one shared repair budget for either
    failure shape, since both mean "the model did not return the structure
    asked for," and the repair prompt is identical either way.
    """


class LLMQuestionItem(BaseModel):
    question: str = Field(min_length=1)
    category: QuestionCategory
    difficulty: QuestionDifficulty
    rationale: str | None = None


class ParsedQuestions(BaseModel):
    questions: list[LLMQuestionItem]


# Matches a fenced block wrapping the whole response ("```json\n...\n```" or
# "```\n...\n```"), stripped only at the very start/end of the text.
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _strip_code_fence(text: str) -> str:
    """Models occasionally wrap strict-JSON output in a markdown fence
    despite being told not to — Rules.md 4.7's "no code fences" is a
    prompt instruction, not a guarantee. Stripped before parsing; does NOT
    count against the one repair retry Rules.md 5.4 budgets, since it's a
    trivial, common formatting quirk, not a content defect.
    """
    return _CODE_FENCE_RE.sub("", text.strip()).strip()


def parse_questions(raw_text: str) -> ParsedQuestions:
    """Raises LLMOutputError on invalid JSON or a schema mismatch."""
    cleaned = _strip_code_fence(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMOutputError(f"Response was not valid JSON: {exc}") from exc

    try:
        return ParsedQuestions.model_validate(data)
    except PydanticValidationError as exc:
        raise LLMOutputError(f"Response did not match the expected schema: {exc}") from exc
