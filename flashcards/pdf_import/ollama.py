"""Small local-only Ollama HTTP client with retryable failures."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: int, retries: int, temperature: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.temperature = temperature

    def generate(self, system: str, prompt: str, schema: dict[str, Any]) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "format": schema,
                "stream": False,
                "think": False,
                "options": {"temperature": self.temperature},
            }
        ).encode()
        request = Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        for attempt in range(self.retries + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    envelope = json.loads(response.read())
                content = envelope.get("message", {}).get("content")
                if not isinstance(content, str) or not content.strip():
                    raise OllamaError("Ollama returned an empty response.")
                return content
            except HTTPError as error:
                detail = self._http_error_detail(error)
                if error.code == 404:
                    raise OllamaError(f"The Ollama model '{self.model}' is not installed.") from error
                if error.code < 500 or attempt >= self.retries:
                    raise OllamaError(detail) from error
            except TimeoutError as error:
                if attempt >= self.retries:
                    raise OllamaError("Ollama timed out while generating flashcards.") from error
            except URLError as error:
                if attempt >= self.retries:
                    raise OllamaError("Ollama is not reachable. Start Ollama and try again.") from error
            except json.JSONDecodeError as error:
                raise OllamaError("Ollama returned an invalid HTTP response.") from error
            time.sleep(min(2**attempt, 4))
        raise OllamaError("Ollama generation failed.")

    @staticmethod
    def _http_error_detail(error: HTTPError) -> str:
        try:
            message = json.loads(error.read()).get("error", "")
        except (json.JSONDecodeError, OSError):
            message = ""
        lowered = message.lower()
        if "memory" in lowered or "allocate" in lowered:
            return "Ollama ran out of memory while loading or running the model."
        return message or f"Ollama returned HTTP {error.code}."
