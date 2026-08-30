"""Ranker protocol (PRD F5.1-F5.3, Phases.md Phase 6). Pure interface — no
DB, no HTTP (Rules.md 4.2) — implemented by tfidf_ranker.py in Phase 6 and
embedding_ranker.py in Phase 7, selected by factory.py per config.

Two methods, not one, on purpose: `fit()` exists so a vectoriser-based
ranker can build its corpus once per scoring run instead of per candidate
pair (Rules.md 4.6 forbids the API ever fitting a model ahead of time, but
fitting on a single resume/job-description pair would make IDF nearly
meaningless — see tfidf_ranker.py's docstring). `score()` is the exact
per-candidate call shape scoring_service.py already uses. An embedding
ranker satisfies both trivially: fit() is a no-op (or where a job
embedding gets computed once per batch), score() compares precomputed
embeddings — scoring_service never needs to change when Phase 7 adds it.
"""
from typing import Protocol


class Ranker(Protocol):
    def fit(self, corpus: list[str]) -> None:
        """Prepares the ranker for the scoring run that follows. `corpus`
        is every document relevant to this run (the job description plus
        every applicant's resume text) — not just the candidates actually
        being scored, so a single-candidate rescore still fits against a
        realistic document set instead of degenerating to two documents.
        """
        ...

    def score(self, resume_text: str, job_text: str) -> float:
        """Returns a similarity score in [0, 100] between one resume and
        the job text, using whatever state fit() prepared.
        """
        ...
