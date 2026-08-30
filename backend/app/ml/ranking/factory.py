"""Returns the active Ranker per config (PRD F5.3 — switchable strategy,
never a code change). config.py already restricts SCORING_METHOD to
{"tfidf", "embedding"} at startup.
"""
from app.config import settings
from app.ml.ranking.base import Ranker
from app.ml.ranking.embedding_ranker import EmbeddingRanker
from app.ml.ranking.tfidf_ranker import TFIDFRanker


def get_ranker(method: str | None = None) -> Ranker:
    """`method` defaults to the live settings.SCORING_METHOD; callers only
    ever override it in tests. Construction never touches the embedding
    model — EmbeddingRanker only loads it lazily on the first fit()/score()
    call, so a broken or missing model surfaces there (as
    ModelUnavailableError), not here.
    """
    resolved = method or settings.SCORING_METHOD
    if resolved == "tfidf":
        return TFIDFRanker()
    if resolved == "embedding":
        return EmbeddingRanker()
    raise ValueError(f"Unknown scoring method: {resolved!r}")
