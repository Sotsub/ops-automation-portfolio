"""A small, swappable interface to the AI model, with a Gemini implementation.

The orchestrator (assistant/ask.py) only uses the `LLM` protocol, so another provider can be added
behind AI_PROVIDER without touching it. The model name and key come from .env (AI_MODEL,
AI_API_KEY); neither is written in code.

Gemini is called through its REST API (generateContent with function declarations), the request
shape that was tested live against the free tier. Rate-limit (429) and overload (503) answers are
retried with backoff, honoring the delay the API asks for.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from shared.config import Settings

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
RETRY_STATUSES = {429, 500, 503}


class LLMError(Exception):
    pass


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass
class Turn:
    """One model reply: either tool calls, or a text answer."""

    text: str
    calls: list[ToolCall]
    content: dict[str, Any]  # the reply as the provider sent it, to append to the conversation
    usage: dict[str, Any] = field(default_factory=dict)


class LLM(Protocol):
    model: str

    def user_message(self, text: str) -> dict[str, Any]: ...
    def tool_results_message(
        self, calls: list[ToolCall], results: list[dict[str, Any]]
    ) -> dict[str, Any]: ...
    def generate(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        allow_tools: bool = True,
    ) -> Turn: ...


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Seconds to wait: Retry-After header, else Google's RetryInfo, else exponential backoff."""
    header = response.headers.get("retry-after")
    if header and header.replace(".", "", 1).isdigit():
        return min(float(header), 60.0)
    try:
        for detail in response.json().get("error", {}).get("details", []):
            if match := re.fullmatch(r"(\d+(?:\.\d+)?)s", str(detail.get("retryDelay", ""))):
                return min(float(match[1]), 60.0)
    except ValueError:
        pass
    return min(2.0**attempt, 30.0)


class GeminiClient:
    def __init__(
        self,
        model: str,
        api_key: str,
        *,
        retries: int = 4,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ):
        self.model = model
        self._http = httpx.Client(
            timeout=timeout, transport=transport, headers={"x-goog-api-key": api_key}
        )
        self._retries = retries
        self._sleep = sleep

    def close(self) -> None:
        self._http.close()

    def user_message(self, text: str) -> dict[str, Any]:
        return {"role": "user", "parts": [{"text": text}]}

    def tool_results_message(
        self, calls: list[ToolCall], results: list[dict[str, Any]]
    ) -> dict[str, Any]:
        parts = []
        for call, result in zip(calls, results, strict=True):
            response: dict[str, Any] = {"name": call.name, "response": result}
            if call.id:
                response["id"] = call.id
            parts.append({"functionResponse": response})
        return {"role": "user", "parts": parts}

    def generate(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        allow_tools: bool = True,
    ) -> Turn:
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": messages,
        }
        if tools:
            body["tools"] = [{"functionDeclarations": tools}]
            body["toolConfig"] = {
                "functionCallingConfig": {"mode": "AUTO" if allow_tools else "NONE"}
            }
        data = self._post(body)
        candidates = data.get("candidates") or []
        if not candidates:
            reason = data.get("promptFeedback", {}).get("blockReason", "no candidates")
            raise LLMError(f"model returned no answer ({reason})")
        content = candidates[0].get("content") or {"role": "model", "parts": []}
        parts = content.get("parts", [])
        calls = [
            ToolCall(
                p["functionCall"]["name"],
                p["functionCall"].get("args") or {},
                p["functionCall"].get("id"),
            )
            for p in parts
            if "functionCall" in p
        ]
        text = "".join(
            p.get("text", "") for p in parts if "text" in p and not p.get("thought")
        ).strip()
        if not calls and not text:
            raise LLMError(
                f"model returned an empty answer (finishReason {candidates[0].get('finishReason')})"
            )
        return Turn(text=text, calls=calls, content=content, usage=data.get("usageMetadata", {}))

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        url = GEMINI_URL.format(model=self.model)
        for attempt in range(1, self._retries + 1):
            try:
                response = self._http.post(url, json=body)
            except httpx.TransportError as exc:
                if attempt == self._retries:
                    raise LLMError(f"could not reach the model: {type(exc).__name__}") from exc
                self._sleep(min(2.0**attempt, 30.0))
                continue
            if response.status_code in RETRY_STATUSES and attempt < self._retries:
                self._sleep(_retry_delay(response, attempt))
                continue
            if response.is_error:
                try:
                    message = response.json().get("error", {}).get("message", "")
                except ValueError:
                    message = response.text
                raise LLMError(f"model API error HTTP {response.status_code}: {message[:300]}")
            return response.json()
        raise AssertionError("unreachable")


def get_llm(settings: Settings) -> GeminiClient:
    """Build the client named by AI_PROVIDER. Fails clearly if .env isn't filled in."""
    provider = (settings.ai_provider or "").strip().lower()
    if not provider:
        raise SystemExit(
            "AI_PROVIDER is blank in .env. Set AI_PROVIDER=gemini (see assistant/README.md)."
        )
    if provider != "gemini":
        raise SystemExit(
            f"AI_PROVIDER={provider} is not supported yet. Only gemini is implemented."
        )
    if not settings.ai_model:
        raise SystemExit("AI_MODEL is blank in .env. Set it to a free-tier Gemini model name.")
    if settings.ai_api_key is None or not settings.ai_api_key.get_secret_value().strip():
        raise SystemExit("AI_API_KEY is blank in .env. Create a free key in Google AI Studio.")
    return GeminiClient(settings.ai_model.strip(), settings.ai_api_key.get_secret_value().strip())
