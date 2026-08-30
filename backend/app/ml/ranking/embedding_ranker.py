"""Embedding-based ranker (PRD F5.2, F5.5; Phases.md Phase 7). Cosine
similarity between all-MiniLM-L6-v2 sentence embeddings, scaled to 0-100.
Pure — no DB, no HTTP (Rules.md 4.2); scoring_service.py owns every touch
of candidates.embedding.

The model itself is a genuine process-wide singleton (Rules.md 4.6):
_get_model() is a MODULE-level lru_cache, not an instance attribute — every
EmbeddingRanker across every request shares the one loaded model, so the
~90MB weights load exactly once per process. Loading is lazy (first actual
use), never eager in main.py's lifespan: the shipped default is
SCORING_METHOD=tfidf, and an install that never switches to embedding mode
should never pay for the download at all. functools.lru_cache guards
concurrent misses with an internal lock, so two simultaneous first requests
can't double-load it.

What IS instance-level is `self._cache`, a plain text -> vector dict — this
is what makes fit() a real batch precompute rather than a no-op: it embeds
every not-yet-cached string in the corpus in one SentenceTransformer.encode()
call (far cheaper than one encode() per candidate), and score() then looks
both texts up by exact match instead of re-embedding. scoring_service.py
seeds this cache with any embedding already persisted on candidates.embedding
(via seed()) before fit() runs, so a candidate scored against a second job
skips the encode() step for their resume entirely — the actual mechanism
behind F5.5's "reused across jobs."
"""
from functools import lru_cache

from sklearn.metrics.pairwise import cosine_similarity

from app.config import settings
from app.core.exceptions import ModelUnavailableError


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer

    try:
        return SentenceTransformer(settings.EMBEDDING_MODEL)
    except Exception as exc:
        # Covers everything from "no network and nothing cached locally"
        # to a corrupted download or an invalid model name. lru_cache does
        # NOT cache exceptions, so a later call (after the operator fixes
        # connectivity, say) retries the load rather than being stuck on a
        # stale failure. Translated to the domain exception here so every
        # caller deals with one error type instead of sentence-transformers'.
        raise ModelUnavailableError(
            f"Could not load the embedding model {settings.EMBEDDING_MODEL!r}: {exc}",
            code="EMBEDDING_MODEL_UNAVAILABLE",
        ) from exc


def ensure_model_available() -> None:
    """Raises ModelUnavailableError if the model can't be loaded; returns
    normally (leaving the model loaded) otherwise. Lets a caller confirm
    availability once, up front, rather than discover it mid-batch —
    scoring_service.py's semantic skill-matching gate uses this so a broken
    model is reported once per scoring run, not retried on every candidate.
    """
    _get_model()


class EmbeddingRanker:
    def __init__(self) -> None:
        self._cache: dict[str, list[float]] = {}

    def seed(self, text: str, vector: list[float]) -> None:
        """Injects an already-computed embedding (e.g. read from
        candidates.embedding) so fit()/score() never re-encode it.
        """
        self._cache[text] = vector

    def embed(self, text: str) -> list[float]:
        """Returns text's embedding, computing and caching it first if this
        exact string hasn't been seen yet via seed(), fit(), or a prior
        embed() call.
        """
        if text not in self._cache:
            vector = _get_model().encode(text)
            self._cache[text] = vector.tolist()
        return self._cache[text]

    def fit(self, corpus: list[str]) -> None:
        """Batch-precomputes an embedding for every string in `corpus` not
        already cached, in one SentenceTransformer.encode() call. Since
        scoring_service.py always puts the job description at corpus[0]
        followed by every applicant's resume text, this is where "job
        embedding computed once per batch" (Phases.md Phase 7) happens.
        """
        uncached = [text for text in dict.fromkeys(corpus) if text not in self._cache]
        if not uncached:
            return
        vectors = _get_model().encode(uncached)
        for text, vector in zip(uncached, vectors):
            self._cache[text] = vector.tolist()

    def score(self, resume_text: str, job_text: str) -> float:
        """Cosine similarity between resume_text and job_text, scaled to
        [0, 100] and clamped: unlike TF-IDF's non-negative term vectors,
        sentence embeddings can in principle score a negative cosine
        similarity, which would otherwise render as an out-of-range
        sub-score.
        """
        resume_vector = self.embed(resume_text)
        job_vector = self.embed(job_text)
        similarity = cosine_similarity([resume_vector], [job_vector])[0][0]
        return max(0.0, min(100.0, float(similarity) * 100))
