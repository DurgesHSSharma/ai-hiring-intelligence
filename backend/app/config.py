"""Application configuration. Validated at import time — see Architecture.md 8.

Fails loudly (raises) rather than falling back to a default whenever a value
would leave the app running in a state nobody chose on purpose.
"""
import logging
from enum import Enum
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.logging import configure_logging

# Logging must be ready before Settings() runs its validators below, since the
# empty-SECRET_KEY-in-development case logs a WARNING during validation.
configure_logging()
logger = logging.getLogger(__name__)

WEIGHT_SUM_TOLERANCE = 1e-6
ALLOWED_SCORING_METHODS = {"tfidf", "embedding"}

# Absolute path: env_file resolved relative to cwd would silently load nothing
# (then fail on every missing key) if uvicorn/pytest is run from the repo root
# instead of backend/.
ENV_FILE_PATH = Path(__file__).resolve().parent.parent / ".env"


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="forbid",
    )

    APP_ENV: AppEnv
    API_V1_PREFIX: str = "/api/v1"
    SECRET_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int

    DATABASE_URL: str

    CORS_ORIGINS: str

    UPLOAD_DIR: str
    MAX_UPLOAD_SIZE_MB: int
    MAX_FILES_PER_BATCH: int

    SCORING_METHOD: str
    EMBEDDING_MODEL: str
    # Opt-in, default false: F4.4's semantic skill fallback depends on the
    # same ~90MB embedding model as SCORING_METHOD=embedding, but skill-gap
    # computation runs for every candidate regardless of ranking method. If
    # this defaulted to true, the shipped SCORING_METHOD=tfidf config would
    # silently depend on a model download, and skill_match_score would vary
    # with whether that unrelated model happened to load — a non-determinism
    # the operator never opted into. False keeps skill gap dictionary-only
    # and fully deterministic until explicitly turned on.
    SEMANTIC_SKILL_MATCHING: bool = False
    WEIGHT_RESUME: float
    WEIGHT_SKILL: float
    WEIGHT_EXPERIENCE: float
    WEIGHT_EDUCATION: float

    LLM_PROVIDER: str
    LLM_MODEL: str = ""
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""
    ANTHROPIC_API_KEY: str = ""
    LLM_TIMEOUT_SECONDS: int

    ATTRITION_MODEL_PATH: str

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @field_validator("SCORING_METHOD")
    @classmethod
    def scoring_method_must_be_allowed(cls, v: str) -> str:
        if v not in ALLOWED_SCORING_METHODS:
            raise ValueError(
                f"SCORING_METHOD must be one of {sorted(ALLOWED_SCORING_METHODS)}, got {v!r}."
            )
        return v

    @model_validator(mode="after")
    def secret_key_policy(self) -> "Settings":
        if not self.SECRET_KEY.strip():
            if self.APP_ENV != AppEnv.DEVELOPMENT:
                raise ValueError(
                    f"SECRET_KEY must be set when APP_ENV={self.APP_ENV.value!r}. "
                    "Refusing to start with an empty secret outside development."
                )
            logger.warning(
                "SECRET_KEY is empty. This is only acceptable in development; "
                "tokens signed with an empty key are not secure."
            )
        return self

    @model_validator(mode="after")
    def semantic_skill_matching_policy(self) -> "Settings":
        # A real-model sanity check (docs/EVALUATION.md's Phase 7 section)
        # found SEMANTIC_MATCH_THRESHOLD (app/ml/skills/skill_gap.py) isn't
        # just unmeasured — it's inverted on the cases that matter:
        # PostgreSQL/MySQL, two different database products, passes at
        # 0.547, while AWS/"cloud infrastructure", a genuine paraphrase,
        # fails at 0.492. Crediting a candidate for the wrong product is
        # worse than no semantic matching at all, so the feature refuses
        # to run regardless of this flag (see
        # scoring_service._semantic_embed_fn and skill_gap.py's
        # THRESHOLD_VALIDATED) until Phases.md Phase 13 validates a real
        # threshold. This only warns, never fails startup — the operator
        # explicitly opted in, they just need to know it currently has no
        # effect.
        if self.SEMANTIC_SKILL_MATCHING:
            logger.warning(
                "SEMANTIC_SKILL_MATCHING is enabled, but the similarity "
                "threshold is unvalidated and known to mis-rank near-synonyms "
                "(see docs/EVALUATION.md). This flag currently has no effect: "
                "semantic skill matching refuses to run until the threshold is "
                "validated against a labelled set (Phases.md Phase 13)."
            )
        return self

    @model_validator(mode="after")
    def llm_provider_policy(self) -> "Settings":
        # Phase 8: fail loudly here rather than let ml/llm/client.py guess
        # a model id at call time. Anthropic has a verified-safe default
        # (claude-haiku-4-5, checked against current pricing — see
        # Memory.md), so LLM_MODEL may be left blank for that provider.
        # OpenAI has no equivalent verified default in this codebase: a
        # guessed model id would only fail at request time with a 404,
        # after burning a request. Refusing to start is the earlier,
        # cheaper failure. This reasoning is stronger now that
        # OPENAI_BASE_URL is configurable, not weaker: the set of valid
        # model ids depends on which OpenAI-compatible endpoint is
        # actually configured, so guessing one is even less safe than
        # when this provider only ever meant real OpenAI.
        if self.LLM_PROVIDER not in {"openai", "anthropic"}:
            raise ValueError(
                f"LLM_PROVIDER must be 'openai' or 'anthropic', got {self.LLM_PROVIDER!r}."
            )
        if self.LLM_PROVIDER == "openai" and not self.LLM_MODEL.strip():
            raise ValueError(
                "LLM_MODEL must be set when LLM_PROVIDER='openai' — there is no built-in "
                "default OpenAI model id. Set LLM_MODEL in .env after checking OpenAI's "
                "current pricing and model list."
            )
        return self

    @model_validator(mode="after")
    def weights_must_sum_to_one(self) -> "Settings":
        total = (
            self.WEIGHT_RESUME
            + self.WEIGHT_SKILL
            + self.WEIGHT_EXPERIENCE
            + self.WEIGHT_EDUCATION
        )
        if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                "Scoring weights must sum to 1.0 "
                f"(tolerance {WEIGHT_SUM_TOLERANCE}): "
                f"WEIGHT_RESUME={self.WEIGHT_RESUME}, WEIGHT_SKILL={self.WEIGHT_SKILL}, "
                f"WEIGHT_EXPERIENCE={self.WEIGHT_EXPERIENCE}, "
                f"WEIGHT_EDUCATION={self.WEIGHT_EDUCATION} -> sum={total}."
            )
        return self


settings = Settings()
