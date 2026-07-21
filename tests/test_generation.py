import json

from flashcards.pdf_import.generation import generate_cards
from flashcards.pdf_import.models import DocumentChunk


def test_generation_uses_mocked_ollama_and_limits_cards():
    source = "The mitral valve lies between the left atrium and left ventricle."
    chunk = DocumentChunk("c-1", "doc", 0, "Mitral valve", "", source, 2, 2)
    calls = []

    def fake_generate(system, prompt, schema):
        calls.append((system, prompt, schema))
        return json.dumps(
            {
                "cards": [
                    {
                        "question": "Where is the mitral valve?",
                        "answer": "Between the left atrium and left ventricle.",
                        "evidence": source,
                    },
                    {
                        "question": "What does the mitral valve connect?",
                        "answer": "The left atrium and left ventricle.",
                        "evidence": source,
                    },
                ]
            }
        )

    cards, warnings = generate_cards(chunk, fake_generate, max_cards=1)
    assert len(cards) == 1
    assert warnings
    assert "outside knowledge" in calls[0][0]
    assert calls[0][2]["type"] == "object"
