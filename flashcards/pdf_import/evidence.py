"""Evidence grounding checks against trusted source chunks."""

from __future__ import annotations

from difflib import SequenceMatcher

from .normalization import normalize_for_matching, word_tokens


def evidence_match_quality(evidence: str, source: str) -> float:
    needle = normalize_for_matching(evidence)
    haystack = normalize_for_matching(source)
    if not needle or not haystack:
        return 0.0
    if needle in haystack:
        return 1.0

    needle_words = needle.split()
    haystack_words = haystack.split()
    if not needle_words or not haystack_words:
        return 0.0
    window_size = len(needle_words)
    step = max(1, window_size // 5)
    best = 0.0
    for start in range(0, max(1, len(haystack_words) - window_size + 1), step):
        window = " ".join(haystack_words[start : start + window_size])
        best = max(best, SequenceMatcher(None, needle, window).ratio())
    token_score = len(word_tokens(needle) & word_tokens(haystack)) / max(1, len(word_tokens(needle)))
    return round(max(best, token_score * 0.9), 3)


def answer_support_quality(answer: str, evidence: str) -> float:
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "were",
        "with",
    }
    answer_tokens = word_tokens(answer) - stop_words
    if not answer_tokens:
        return 0.0
    evidence_tokens = word_tokens(evidence) - stop_words
    return round(len(answer_tokens & evidence_tokens) / len(answer_tokens), 3)
