"""Local text embeddings and resume/job-description matching."""

from __future__ import annotations

import re
from collections import Counter
from typing import TypedDict

import numpy as np
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.-]{1,}")
_STOP_WORDS = set(ENGLISH_STOP_WORDS) | {
    "ability",
    "experience",
    "including",
    "looking",
    "required",
    "requirements",
    "responsibilities",
    "role",
    "skills",
    "team",
    "work",
}


class KeywordMatch(TypedDict):
    matched_keywords: list[str]
    missing_keywords: list[str]
    keyword_match: float
    semantic_similarity: float


def generate_embeddings(texts: list[str]) -> np.ndarray:
    """Generate normalized TF-IDF vectors; no external embedding service is used."""
    if not texts:
        return np.empty((0, 0), dtype=float)
    vectorizer = TfidfVectorizer(
        stop_words="english", ngram_range=(1, 2), max_features=20_000
    )
    try:
        return vectorizer.fit_transform(texts).toarray()
    except ValueError as exc:
        if "empty vocabulary" in str(exc).lower():
            return np.zeros((len(texts), 1), dtype=float)
        raise


def cosine_similarity_score(text_a: str, text_b: str) -> float:
    vectors = generate_embeddings([text_a, text_b])
    if vectors.shape[1] == 0:
        return 0.0
    return float(cosine_similarity(vectors[0:1], vectors[1:2])[0, 0] * 100)


def _terms(text: str) -> list[str]:
    return [
        token.lower()
        for token in _TOKEN_RE.findall(text)
        if token.lower() not in _STOP_WORDS and len(token) > 2
    ]


def extract_keywords(text: str, limit: int = 25) -> list[str]:
    terms = _terms(text)
    if not terms:
        return []
    counts = Counter(terms)
    return [term for term, _ in counts.most_common(limit)]


def match_keywords(resume_text: str, job_description: str) -> KeywordMatch:
    job_keywords = extract_keywords(job_description)
    resume_terms = set(_terms(resume_text))
    matched = [term for term in job_keywords if term in resume_terms]
    missing = [term for term in job_keywords if term not in resume_terms]
    coverage = (len(matched) / len(job_keywords) * 100) if job_keywords else 0.0
    similarity = cosine_similarity_score(resume_text, job_description)
    return {
        "matched_keywords": matched,
        "missing_keywords": missing,
        "keyword_match": round(coverage, 1),
        "semantic_similarity": round(similarity, 1),
    }
