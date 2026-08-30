"""TF-IDF ranker (PRD F5.1). Cosine similarity between a job description
and a resume, scaled to 0-100.

Rules.md 4.6 forbids the API fitting a model ahead of time; a vectoriser
needed at request time must be fitted per scoring run and discarded, which
is exactly what fit() below does. It deliberately does NOT fit on just the
one resume/job-description pair being compared: IDF is a rarity signal
computed *across* documents, and across a corpus of two documents every
term is either "in both" or "in one" — there is no meaningful notion of
rarity, and the score degenerates toward plain term overlap. The caller
(scoring_service.py) fits this once per scoring run on the real applicant
pool for the job (every applicant's resume text, plus the job description),
so IDF reflects which terms are actually common versus distinguishing
across real candidates for this job.
"""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class TFIDFRanker:
    def __init__(self) -> None:
        self._vectorizer: TfidfVectorizer | None = None

    def fit(self, corpus: list[str]) -> None:
        """A fresh TfidfVectorizer, fit on `corpus` and held only for the
        life of this instance — nothing is cached or persisted between
        calls or instances (Rules.md 4.6).
        """
        self._vectorizer = TfidfVectorizer(stop_words="english")
        self._vectorizer.fit(corpus)

    def score(self, resume_text: str, job_text: str) -> float:
        """Cosine similarity between `resume_text` and `job_text`, scaled
        to [0, 100]. Resolves to 0.0 (never NaN, never an exception) when
        one side has no vocabulary overlap with the fitted corpus at all:
        scikit-learn's normalize() step leaves an all-zero TF-IDF vector
        as zero rather than dividing by a zero norm, so cosine_similarity
        returns 0.0 for that pair — verified directly, not assumed.
        """
        if self._vectorizer is None:
            raise RuntimeError("TFIDFRanker.score() called before fit().")
        vectors = self._vectorizer.transform([resume_text, job_text])
        similarity = cosine_similarity(vectors[0:1], vectors[1:2])[0][0]
        return float(similarity) * 100
