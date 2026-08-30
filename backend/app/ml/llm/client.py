"""Provider-agnostic LLM client (Rules.md 3.3, 4.7 — vendor SDKs imported
only in this file). Phases.md Phase 8, Architecture.md 7.3.

Every caller outside this module sees exactly one function, generate(),
and one return type, LLMResult — both provider-neutral. Switching
LLM_PROVIDER between "openai" and "anthropic" in .env changes no code
anywhere else in the codebase.

"openai" means any OpenAI-compatible Chat Completions endpoint, not only
api.openai.com. OPENAI_BASE_URL selects which one; leaving it empty
targets real OpenAI. The shipped .env points it at Groq instead.
"""
import logging
import time
from dataclasses import dataclass
from functools import lru_cache

from app.config import settings
from app.core.exceptions import LLMError

logger = logging.getLogger(__name__)

# Verified live against this project's current Anthropic pricing (see
# Memory.md): $1.00 / $5.00 per 1M input/output tokens on a 200K context
# window — well suited to this task (short, structured, low-stakes-per-call).
# There is still no equivalent verified-safe OpenAI default in this
# codebase, now for a second reason: with OPENAI_BASE_URL configurable,
# "openai" can mean any OpenAI-compatible endpoint, so a hardcoded default
# model id could be silently wrong for whichever endpoint is actually
# configured. config.py's llm_provider_policy refuses to start with
# LLM_PROVIDER=openai and an empty LLM_MODEL rather than let this file
# guess one.
_DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5"

# Rules.md 5.4: exactly one retry on transient failure. Both SDK clients
# below are constructed with max_retries=0 so this is the only retry that
# ever happens — the SDK's own default backoff schedule never compounds
# with it.
_RETRY_BACKOFF_SECONDS = 1.0

# Hard per-call cost ceiling: generous headroom for up to 10 short
# questions with a one-sentence rationale each, but a real cap, not
# unbounded (Rules.md 5.1, cost control).
MAX_TOKENS = 2048


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


def resolve_model() -> str:
    """Public (no leading underscore) so interview_service.py can log which
    model a call targeted even when the call itself failed before a
    response came back — the only piece of provider detail that crosses
    this module's boundary, and only as a plain string.
    """
    if settings.LLM_PROVIDER == "anthropic":
        return settings.LLM_MODEL or _DEFAULT_ANTHROPIC_MODEL
    # openai: config.py's llm_provider_policy guarantees this is non-empty
    # before the app ever starts.
    return settings.LLM_MODEL


def _api_key_configured() -> bool:
    key = settings.OPENAI_API_KEY if settings.LLM_PROVIDER == "openai" else settings.ANTHROPIC_API_KEY
    return bool(key.strip())


@lru_cache(maxsize=1)
def _get_openai_client():
    import openai

    kwargs = {
        "api_key": settings.OPENAI_API_KEY,
        "timeout": settings.LLM_TIMEOUT_SECONDS,
        "max_retries": 0,
    }
    if settings.OPENAI_BASE_URL.strip():
        kwargs["base_url"] = settings.OPENAI_BASE_URL.strip()
    return openai.OpenAI(**kwargs)


@lru_cache(maxsize=1)
def _get_anthropic_client():
    import anthropic

    return anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY, timeout=settings.LLM_TIMEOUT_SECONDS, max_retries=0
    )


def _call_openai(prompt: str, system: str) -> LLMResult:
    client = _get_openai_client()
    response = client.chat.completions.create(
        model=resolve_model(),
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    return LLMResult(
        text=response.choices[0].message.content or "",
        model=response.model,
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
    )


def _call_anthropic(prompt: str, system: str) -> LLMResult:
    client = _get_anthropic_client()
    response = client.messages.create(
        model=resolve_model(),
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    return LLMResult(
        text=text,
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


def generate(prompt: str, *, system: str) -> LLMResult:
    """Sends one request to the configured LLM_PROVIDER.

    Raises LLMError(code="LLM_UNAVAILABLE") immediately, with no network
    call at all, if the configured provider's API key is empty (Phases.md's
    "provider key removed" acceptance case).

    Otherwise: LLMError(code="LLM_TIMEOUT") after one retry on a timeout;
    LLMError(code="LLM_UNAVAILABLE") after one retry on any other transient
    failure (429, >=500, connection error); LLMError(code="LLM_UNAVAILABLE")
    immediately, no retry, on a non-transient failure (bad request, auth,
    not found — retrying those wastes a call without changing the outcome).

    A genuinely unexpected exception (not one of the SDK's known failure
    types) is deliberately NOT caught here — it propagates to the
    application's catch-all handler as INTERNAL_ERROR (Rules.md 5.4),
    rather than being mislabeled as a provider failure.
    """
    if not _api_key_configured():
        raise LLMError(
            f"No API key configured for LLM_PROVIDER={settings.LLM_PROVIDER!r}.",
            code="LLM_UNAVAILABLE",
        )

    if settings.LLM_PROVIDER == "openai":
        import openai as sdk

        call = _call_openai
    else:
        import anthropic as sdk

        call = _call_anthropic

    for attempt in (1, 2):
        try:
            return call(prompt, system)
        except sdk.APITimeoutError as exc:
            if attempt == 2:
                raise LLMError(f"LLM request timed out: {exc}", code="LLM_TIMEOUT") from exc
            logger.warning("LLM call timed out (provider=%s); retrying once.", settings.LLM_PROVIDER)
        except (sdk.RateLimitError, sdk.APIConnectionError) as exc:
            if attempt == 2:
                raise LLMError(f"LLM provider unavailable: {exc}", code="LLM_UNAVAILABLE") from exc
            logger.warning(
                "LLM call failed transiently (provider=%s, %s); retrying once.",
                settings.LLM_PROVIDER,
                type(exc).__name__,
            )
        except sdk.APIStatusError as exc:
            if exc.status_code >= 500 and attempt == 1:
                logger.warning(
                    "LLM provider returned %s (provider=%s); retrying once.",
                    exc.status_code,
                    settings.LLM_PROVIDER,
                )
            else:
                raise LLMError(f"LLM provider returned an error: {exc}", code="LLM_UNAVAILABLE") from exc
        time.sleep(_RETRY_BACKOFF_SECONDS)

    # Unreachable: every branch above either returns or raises. Kept only
    # so the function has an explicit exhaustive exit for readers/linters.
    raise LLMError("LLM request failed after retry.", code="LLM_UNAVAILABLE")
