import pytest

from app.config import Settings

BASE_ENV = {
    "APP_ENV": "development",
    "SECRET_KEY": "",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "1440",
    "DATABASE_URL": "sqlite:///./test.db",
    "CORS_ORIGINS": "http://localhost:5173",
    "UPLOAD_DIR": "./storage",
    "MAX_UPLOAD_SIZE_MB": "5",
    "MAX_FILES_PER_BATCH": "50",
    "SCORING_METHOD": "tfidf",
    "EMBEDDING_MODEL": "all-MiniLM-L6-v2",
    "SEMANTIC_SKILL_MATCHING": "false",
    "WEIGHT_RESUME": "0.40",
    "WEIGHT_SKILL": "0.35",
    "WEIGHT_EXPERIENCE": "0.15",
    "WEIGHT_EDUCATION": "0.10",
    "LLM_PROVIDER": "openai",
    # Phase 8: config.py's llm_provider_policy refuses to start with
    # LLM_PROVIDER=openai and an empty LLM_MODEL — this baseline must carry
    # a real-looking value so every other test in this file (which doesn't
    # care about LLM config at all) isn't collaterally broken by that check.
    "LLM_MODEL": "gpt-4o-mini",
    "OPENAI_API_KEY": "",
    "ANTHROPIC_API_KEY": "",
    "LLM_TIMEOUT_SECONDS": "30",
    "ATTRITION_MODEL_PATH": "../ml/attrition/artifacts/attrition_model.joblib",
}


def _set_env(monkeypatch, overrides: dict | None = None) -> None:
    env = {**BASE_ENV, **(overrides or {})}
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_valid_settings_load(monkeypatch):
    _set_env(monkeypatch)
    settings = Settings(_env_file=None)
    assert settings.SCORING_METHOD == "tfidf"


def test_secret_key_required_outside_development(monkeypatch):
    _set_env(monkeypatch, {"APP_ENV": "production", "SECRET_KEY": ""})
    with pytest.raises(Exception, match="SECRET_KEY must be set"):
        Settings(_env_file=None)


def test_secret_key_empty_in_development_warns(monkeypatch, caplog):
    _set_env(monkeypatch, {"APP_ENV": "development", "SECRET_KEY": ""})
    with caplog.at_level("WARNING"):
        Settings(_env_file=None)
    assert any("SECRET_KEY is empty" in record.message for record in caplog.records)


def test_weights_must_sum_to_one(monkeypatch):
    _set_env(monkeypatch, {"WEIGHT_RESUME": "0.50"})
    with pytest.raises(Exception, match="must sum to 1.0"):
        Settings(_env_file=None)


def test_scoring_method_must_be_allowed(monkeypatch):
    _set_env(monkeypatch, {"SCORING_METHOD": "bogus"})
    with pytest.raises(Exception, match="SCORING_METHOD must be one of"):
        Settings(_env_file=None)


def test_semantic_skill_matching_enabled_warns(monkeypatch, caplog):
    # The threshold is unvalidated and known to mis-rank near-synonyms
    # (Memory.md decision 42/46) — enabling the flag must warn, not fail
    # startup, since the operator explicitly opted in and just needs to
    # know it currently has no effect (skill_gap.THRESHOLD_VALIDATED).
    _set_env(monkeypatch, {"SEMANTIC_SKILL_MATCHING": "true"})
    with caplog.at_level("WARNING"):
        Settings(_env_file=None)
    assert any("SEMANTIC_SKILL_MATCHING" in record.message for record in caplog.records)


def test_semantic_skill_matching_disabled_does_not_warn(monkeypatch, caplog):
    _set_env(monkeypatch, {"SEMANTIC_SKILL_MATCHING": "false"})
    with caplog.at_level("WARNING"):
        Settings(_env_file=None)
    assert not any("SEMANTIC_SKILL_MATCHING" in record.message for record in caplog.records)


def test_missing_required_key_fails(monkeypatch):
    _set_env(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(Exception, match="DATABASE_URL"):
        Settings(_env_file=None)


def test_llm_provider_openai_requires_explicit_model(monkeypatch):
    # Decision (Phase 8 plan, approved): a guessed OpenAI model id that
    # 404s at request time is worse than a startup failure that says what
    # to do. Anthropic has a verified-safe default and doesn't need this.
    _set_env(monkeypatch, {"LLM_PROVIDER": "openai", "LLM_MODEL": ""})
    with pytest.raises(Exception, match="LLM_MODEL must be set"):
        Settings(_env_file=None)


def test_llm_provider_anthropic_allows_empty_model(monkeypatch):
    _set_env(monkeypatch, {"LLM_PROVIDER": "anthropic", "LLM_MODEL": ""})
    settings = Settings(_env_file=None)
    assert settings.LLM_MODEL == ""


def test_llm_provider_must_be_allowed(monkeypatch):
    _set_env(monkeypatch, {"LLM_PROVIDER": "bogus"})
    with pytest.raises(Exception, match="LLM_PROVIDER must be"):
        Settings(_env_file=None)


def test_openai_base_url_unset_resolves_to_empty(monkeypatch):
    _set_env(monkeypatch)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.OPENAI_BASE_URL == ""


def test_openai_base_url_set_is_preserved_verbatim(monkeypatch):
    _set_env(monkeypatch, {"OPENAI_BASE_URL": "https://api.groq.com/openai/v1"})
    settings = Settings(_env_file=None)
    assert settings.OPENAI_BASE_URL == "https://api.groq.com/openai/v1"
