"""One provider interface, N adapters.

Design rule from the shared plan: use the HTTP client that is already in the
project. Both adapter families below are plain JSON-over-HTTP calls, so no
per-provider SDK is required.

Supported `AI_PROVIDER` values:
  gemini               - Google Gemini REST API (responseSchema + JSON mode)
  groq / cerebras /
  nvidia / openrouter /
  openai_compatible    - OpenAI-compatible /chat/completions

Everything is configured from the environment. Keys are never logged, never
returned in `describe()` output, and never written to disk by this module.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from .config import AIConfig, ProviderConfig, get_config
from .errors import (
    AIOutputInvalidError,
    AuthError,
    ContextInsufficientError,
    HallucinatedEvidenceError,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
    RateLimitedError,
    TimeoutError_,
)
from .schemas import ROLE_SCHEMAS, Role, StrictModel

Transport = Callable[[httpx.Request], httpx.Response] | httpx.BaseTransport | None

RETRY_BACKOFF_SECONDS = 0.35


@dataclass
class ProviderResult:
    """One provider call: raw text, timing, and the parsed+validated object."""

    text: str
    model: str
    provider: str
    latency_ms: int
    attempts: int
    validated: StrictModel | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    repair_used: bool = False
    raw_json: Any = None


def _schema_hint(role: Role) -> str:
    """Response-shape hint passed to providers with strict JSON schema support."""
    schema = ROLE_SCHEMAS[role].model_json_schema()
    return json.dumps(schema, ensure_ascii=False)


def _is_transient(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


class BaseProvider(ABC):
    """Uniform interface: complete(prompt, role, timeout) -> ProviderResult."""

    def __init__(self, config: ProviderConfig, *, transport: Transport = None) -> None:
        self.config = config
        self._transport = transport

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    def describe(self) -> dict[str, Any]:
        return self.config.describe()

    def _check_configured(self) -> None:
        if not self.config.is_configured:
            raise ProviderNotConfiguredError(
                f"provider '{self.config.name}' is not configured "
                "(AI_API_KEY and AI_BASE_URL/known default must resolve)"
            )

    def _request(self, url: str, *, method: str, headers: dict[str, str], json_body: dict[str, Any], timeout: float) -> httpx.Response:
        request = httpx.Request(method, url, headers=headers, json=json_body)
        return self._send(request, timeout)

    def _send(self, request: httpx.Request, timeout: float) -> httpx.Response:
        try:
            if self._transport is not None:
                response = _invoke_transport(self._transport, request)
            else:
                with httpx.Client(timeout=timeout) as client:
                    response = client.send(request)
        except httpx.TimeoutException as exc:
            raise TimeoutError_(
                f"provider '{self.name}' timed out after {timeout}s",
                details={"provider": self.name},
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                f"provider '{self.name}' transport error: {exc.__class__.__name__}",
                details={"provider": self.name},
            ) from exc
        return self._send_with_retries(request, response, timeout)

    def _send_with_retries(self, request: httpx.Request, response: httpx.Response, timeout: float) -> httpx.Response:
        attempts = max(0, self.config.max_retries)
        current = response
        try:
            for _ in range(attempts):
                self._raise_for_status(current)
                if not _is_transient(current.status_code):
                    return current
                time.sleep(RETRY_BACKOFF_SECONDS)
                with httpx.Client(timeout=timeout) as client:
                    current = client.send(request)
        except ProviderUnavailableError:
            raise
        self._raise_for_status(current)
        return current

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return
        body = _safe_text(response)
        if status in (401, 403):
            raise AuthError(
                f"provider '{self.name}' rejected the API key (HTTP {status})",
                details={"provider": self.name, "http_status": status},
            )
        if status == 429:
            raise RateLimitedError(
                f"provider '{self.name}' returned HTTP 429 (rate limited)",
                details={"provider": self.name, "http_status": status},
            )
        if status >= 500:
            raise ProviderUnavailableError(
                f"provider '{self.name}' returned HTTP {status}",
                details={"provider": self.name, "http_status": status, "body": body[:200]},
            )
        raise AIOutputInvalidError(
            f"provider '{self.name}' returned HTTP {status}",
            details={"provider": self.name, "http_status": status, "body": body[:200]},
        )

    @abstractmethod
    def complete(self, prompt: str, role: Role, *, timeout: float | None = None) -> ProviderResult:
        raise NotImplementedError

    # Shared: repair pass for malformed output, then validate. ---------------- #

    def _parse_and_validate(self, text: str, role: Role, *, provider: str, model: str, latency_ms: int, attempts: int, usage: dict[str, Any], repair_text: str | None = None) -> ProviderResult:
        extracted = extract_json_payload(text)
        if extracted is None and repair_text is not None:
            extracted = extract_json_payload(repair_text)
        if extracted is None:
            raise AIOutputInvalidError(
                f"provider '{provider}' returned a response that contains no JSON object",
                details={"provider": provider, "preview": text[:200]},
            )
        if not isinstance(extracted, dict):
            raise AIOutputInvalidError(
                f"provider '{provider}' returned JSON that is not an object",
                details={"provider": provider, "type": type(extracted).__name__},
            )
        try:
            validated = ROLE_SCHEMAS[role].model_validate(extracted)
        except Exception as exc:  # pydantic ValidationError
            raise AIOutputInvalidError(
                f"provider '{provider}' response failed {ROLE_SCHEMAS[role].__name__} validation",
                details={"provider": provider, "errors": _describe_validation_error(exc)},
            ) from exc
        return ProviderResult(
            text=text,
            model=model,
            provider=provider,
            latency_ms=latency_ms,
            attempts=attempts,
            validated=validated,
            usage=usage,
            repair_used=repair_text is not None,
            raw_json=extracted,
        )


def _invoke_transport(transport: Transport, request: httpx.Request) -> httpx.Response:
    """httpx transports expose handle_request(); a bare callable is also accepted."""
    handler = getattr(transport, "handle_request", None)
    if callable(handler):
        return handler(request)
    if callable(transport):
        return transport(request)
    raise TypeError(f"unsupported transport: {type(transport).__name__}")


def _safe_text(response: httpx.Response) -> str:
    try:
        return response.text
    except Exception:  # pragma: no cover - defensive
        return ""


def _describe_validation_error(exc: Exception) -> list[dict[str, Any]]:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            return [
                {"loc": [str(part) for part in item.get("loc", ())], "msg": item.get("msg", "")}
                for item in errors()
            ][:10]
        except Exception:  # pragma: no cover - defensive
            pass
    return [{"msg": str(exc)}]


def extract_json_payload(text: str) -> Any | None:
    """Pull a JSON object out of a model response.

    Handles fenced blocks, leading prose, and trailing text. Returns None when
    nothing parses.
    """
    if text is None:
        return None
    candidate = text.strip()
    if not candidate:
        return None

    if candidate.startswith("```"):
        lines = candidate.splitlines()
        body = [line for line in lines if not line.strip().startswith("```")]
        candidate = "\n".join(body).strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    for opening, closing in (("{", "}"), ("[", "]")):
        start = candidate.find(opening)
        while start != -1:
            depth = 0
            in_string = False
            escape = False
            for index in range(start, len(candidate)):
                char = candidate[index]
                if in_string:
                    if escape:
                        escape = False
                    elif char == "\\":
                        escape = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == opening:
                    depth += 1
                elif char == closing:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(candidate[start : index + 1])
                        except json.JSONDecodeError:
                            break
            start = candidate.find(opening, start + 1)
    return None


class OpenAICompatibleProvider(BaseProvider):
    """Adapter for /chat/completions style APIs (Groq, Cerebras, NVIDIA, OpenRouter)."""

    def complete(self, prompt: str, role: Role, *, timeout: float | None = None) -> ProviderResult:
        self._check_configured()
        effective_timeout = timeout or self.config.timeout_seconds
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a structured-output component. You answer with JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        if self.config.supports_json_mode:
            body["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        response = self._request(
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            method="POST",
            headers=headers,
            json_body=body,
            timeout=effective_timeout,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        payload = json.loads(response.text or "{}")
        choices = payload.get("choices") or []
        if not choices:
            raise AIOutputInvalidError(
                f"provider '{self.name}' returned no choices",
                details={"provider": self.name, "payload_keys": sorted(payload.keys())},
            )
        message = choices[0].get("message") or {}
        text = message.get("content")
        if isinstance(text, list):  # some providers return content parts
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        if not isinstance(text, str) or not text.strip():
            raise AIOutputInvalidError(
                f"provider '{self.name}' returned an empty response",
                details={"provider": self.name},
            )

        usage = payload.get("usage") or {}
        return self._parse_and_validate(
            text,
            role,
            provider=self.name,
            model=str(payload.get("model") or self.config.model),
            latency_ms=latency_ms,
            attempts=1,
            usage={key: usage.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens") if usage.get(key) is not None},
        )


class GeminiProvider(BaseProvider):
    """Adapter for the Gemini REST generateContent API."""

    _MODEL_PREFIX = "models/"

    def complete(self, prompt: str, role: Role, *, timeout: float | None = None) -> ProviderResult:
        self._check_configured()
        effective_timeout = timeout or self.config.timeout_seconds
        model = self.config.model
        if not model.startswith(self._MODEL_PREFIX):
            model = f"{self._MODEL_PREFIX}{model}"

        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }
        if self.config.supports_json_mode:
            body["generationConfig"]["responseSchema"] = json.loads(_schema_hint(role))

        url = (
            f"{self.config.base_url.rstrip('/')}/{model}:generateContent"
            f"?key={self.config.api_key}"
        )
        started = time.perf_counter()
        response = self._send(
            httpx.Request("POST", url, json=body, headers={"Content-Type": "application/json"}),
            effective_timeout,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        payload = json.loads(response.text or "{}")
        candidates = payload.get("candidates") or []
        if not candidates:
            error = payload.get("error") or {}
            raise ProviderUnavailableError(
                f"provider '{self.name}' returned no candidates"
                + (f": {error.get('message')}" if error.get("message") else ""),
                details={"provider": self.name},
            )
        parts = ((candidates[0].get("content") or {}).get("parts")) or []
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        if not text.strip():
            raise AIOutputInvalidError(
                f"provider '{self.name}' returned an empty response",
                details={"provider": self.name},
            )

        usage_meta = payload.get("usageMetadata") or {}
        usage = {
            key: usage_meta.get(key)
            for key in ("promptTokenCount", "candidatesTokenCount", "totalTokenCount")
            if usage_meta.get(key) is not None
        }
        return self._parse_and_validate(
            text,
            role,
            provider=self.name,
            model=self.config.model,
            latency_ms=latency_ms,
            attempts=1,
            usage=usage,
        )


PROVIDER_ADAPTERS: dict[str, type[BaseProvider]] = {
    "gemini": GeminiProvider,
    "groq": OpenAICompatibleProvider,
    "cerebras": OpenAICompatibleProvider,
    "nvidia": OpenAICompatibleProvider,
    "openrouter": OpenAICompatibleProvider,
    "openai_compatible": OpenAICompatibleProvider,
}


def build_provider(config: ProviderConfig, *, transport: Transport = None) -> BaseProvider:
    adapter = PROVIDER_ADAPTERS.get(config.name)
    if adapter is None:
        raise ProviderNotConfiguredError(
            f"unknown AI_PROVIDER '{config.name}'; supported: {sorted(PROVIDER_ADAPTERS)}"
        )
    return adapter(config, transport=transport)


def build_chain(
    config: AIConfig | None = None,
    *,
    primary_transport: Transport = None,
    fallback_transport: Transport = None,
) -> list[BaseProvider]:
    """Primary -> fallback -> (caller handles the typed error)."""
    active = config or get_config()
    chain: list[BaseProvider] = [build_provider(active.primary, transport=primary_transport)]
    if active.fallback:
        chain.append(build_provider(active.fallback, transport=fallback_transport))
    return chain


# --------------------------------------------------------------------------- #
# post-validation guards
# --------------------------------------------------------------------------- #


def verify_evidence_refs(refs: list[str], allowed: set[str]) -> None:
    """Reject a response that cites evidence ids which do not exist."""
    unknown = sorted({ref for ref in refs if ref not in allowed})
    if unknown:
        raise HallucinatedEvidenceError(
            "model cited evidence ids that do not exist in the dataset: "
            + ", ".join(unknown[:5]),
            details={"unknown_refs": unknown[:10]},
        )


def raise_if_insufficient(role: Role, validated: StrictModel) -> None:
    """`insufficient_context` is an honest answer, not an error, for explain."""
    if getattr(validated, "insufficient_context", False) and role is Role.EXPLAIN:
        raise ContextInsufficientError(
            "the model reported that the retrieved evidence is insufficient to answer the question"
        )