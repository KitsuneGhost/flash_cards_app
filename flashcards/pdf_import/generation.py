"""Prompting and guarded conversion of Ollama output into draft cards."""

from __future__ import annotations

import json
from collections.abc import Callable

from .confidence import calculate_confidence
from .models import DocumentChunk, DraftFlashcard
from .validation import generated_cards_schema, parse_model_output, validate_generated_card

SYSTEM_PROMPT = """You create study flashcards using only the supplied source text.
Do not use outside knowledge or infer unsupported conclusions. Do not add medical facts, diagnoses,
treatment recommendations, personalized medical advice, or drug doses not explicitly present in the source.
Create cards that test knowledge a student needs to understand or recall the subject. Skip slide metadata,
speaker or professor names, affiliations, dates, acknowledgements, course logistics, and other administrative
facts unless the source explicitly makes them part of the subject matter. Prefer mechanisms, distinctions,
causes, consequences, definitions, diagnostic features, and ordered processes over trivia.
Every question must be self-contained for a student who has not seen the document recently. Include the
relevant domain or process when a term could be ambiguous (for example, "During chemical carcinogenesis,
how does initiation contribute to tumor development?"). Never refer to "the source text", "the document",
"the passage", "the presentation", "this slide", or what is stated, shown, described, or mentioned there.
Questions must identify the exact concept and must not ask vague relationship questions such as "How is A
linked to B?" Answers must state the specific mechanism, direction, consequence, or distinguishing detail;
do not answer only that something is involved in, associated with, linked to, or plays a role in something.
If the source does not support a specific useful card, return fewer cards. Answers must be concise but complete.
Every card must include a direct quotation or very close normalized quotation as evidence.
Return JSON only, matching the supplied schema. Return no markdown or commentary."""


def generate_cards(
    chunk: DocumentChunk,
    generate: Callable[[str, str, dict], str],
    max_cards: int,
) -> tuple[list[DraftFlashcard], list[str]]:
    prompt = f"""Create at most {max_cards} flashcards from this source chunk.
Section: {chunk.section_title}
Schema: {json.dumps(generated_cards_schema(), separators=(",", ":"))}
SOURCE TEXT:
{chunk.text}"""
    payloads = parse_model_output(generate(SYSTEM_PROMPT, prompt, generated_cards_schema()))
    cards, warnings = [], []
    for payload in payloads[:max_cards]:
        card = validate_generated_card(payload, chunk)
        if card is None:
            warnings.append(f"Rejected an unsupported or invalid card in chunk {chunk.id}.")
            continue
        card.confidence = calculate_confidence(card)
        cards.append(card)
    if len(payloads) > max_cards:
        warnings.append(f"Ignored cards above the {max_cards}-card per-chunk limit.")
    return cards, warnings
