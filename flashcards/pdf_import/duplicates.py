"""Document-wide duplicate detection without an embeddings dependency."""

from __future__ import annotations

from difflib import SequenceMatcher

from .models import DraftFlashcard
from .normalization import normalize_for_matching, word_tokens


def card_similarity(left: DraftFlashcard, right: DraftFlashcard) -> float:
    left_q, right_q = normalize_for_matching(left.question), normalize_for_matching(right.question)
    left_a, right_a = normalize_for_matching(left.answer), normalize_for_matching(right.answer)
    if left_q == right_q and (not left_a or left_a == right_a):
        return 1.0
    q_sequence = SequenceMatcher(None, left_q, right_q).ratio()
    q_tokens_left, q_tokens_right = word_tokens(left_q), word_tokens(right_q)
    q_union = q_tokens_left | q_tokens_right
    q_tokens = len(q_tokens_left & q_tokens_right) / len(q_union) if q_union else 0.0
    answer_sequence = SequenceMatcher(None, left_a, right_a).ratio() if left_a and right_a else 0.0
    return round(max(q_sequence, q_tokens) * 0.8 + answer_sequence * 0.2, 3)


def _quality_key(card: DraftFlashcard) -> tuple[float, float, int, int]:
    return (card.confidence, card.evidence_match_quality, -len(card.answer), -len(card.question))


def remove_duplicates(cards: list[DraftFlashcard], threshold: float = 0.88) -> list[DraftFlashcard]:
    unique: list[DraftFlashcard] = []
    for card in cards:
        duplicate_index = next(
            (index for index, existing in enumerate(unique) if card_similarity(card, existing) >= threshold),
            None,
        )
        if duplicate_index is None:
            unique.append(card)
        elif _quality_key(card) > _quality_key(unique[duplicate_index]):
            unique[duplicate_index] = card
    return unique
