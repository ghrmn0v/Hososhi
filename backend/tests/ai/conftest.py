"""Shared fixtures for the AI test suite.

Two providers are always available in tests:

* `stub_provider` - deterministic, offline, records every prompt it was given
  (used for schema, grounding and cap assertions)
* `MockTransport` handlers for timeout / 429 / 500 / malformed-body paths
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.ai import retrieval as retrieval_module  # noqa: E402
from app.ai.config import AIConfig, ProviderConfig, reset_config_cache  # noqa: E402
from app.ai.pipeline import AIService, AIServiceCache  # noqa: E402
from app.ai.provider import OpenAICompatibleProvider, ProviderResult  # noqa: E402
from app.ai.retrieval import EvidenceStore  # noqa: E402
from app.ai.safety import POLICY_RULES_VERSION  # noqa: E402
from app.ai.schemas import AutomationClass, Role  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("AI_"):
            monkeypatch.delenv(key, raising=False)
    reset_config_cache()
    retrieval_module.reset_store_cache()
    yield
    reset_config_cache()
    retrieval_module.reset_store_cache()


@pytest.fixture(scope="session")
def dataset_path() -> Path:
    return REPO_ROOT / "data" / "evidence" / "evidence.json"


@pytest.fixture
def store(dataset_path: Path) -> EvidenceStore:
    return EvidenceStore(retrieval_module.load_dataset(dataset_path))


def make_config(**overrides: Any) -> AIConfig:
    base = AIConfig(
        primary=ProviderConfig(
            name="groq",
            model="test-model",
            api_key="test-key",
            base_url="https://api.groq.com/openai/v1",
            timeout_seconds=1.0,
            max_retries=0,
        ),
        context_evidence_cap=12,
        context_event_cap=15,
        cache_enabled=False,
        allow_deterministic_fallback=True,
    )
    return replace(base, **overrides)


@pytest.fixture
def config() -> AIConfig:
    return make_config()


class StubProvider:
    """Returns canned validated payloads. Records prompts for cap assertions."""

    def __init__(self, name: str = "stub", payloads: dict[Role, Any] | None = None) -> None:
        self.name = name
        self.model = "stub-model"
        self.prompts: list[str] = []
        self.calls = 0
        self.payloads = payloads or {}
        self.sequence: list[Any] = []
        self.transport: httpx.MockTransport | None = None

    def complete(self, prompt: str, role: Role, *, timeout: float | None = None) -> ProviderResult:
        self.prompts.append(prompt)
        self.calls += 1
        if self.sequence:
            payload = self.sequence.pop(0)
            if isinstance(payload, Exception):
                raise payload
            text = payload if isinstance(payload, str) else json.dumps(payload)
            return self._result(text, role)
        payload = self.payloads.get(role)
        if payload is None:
            from app.ai.errors import ProviderNotConfiguredError

            raise ProviderNotConfiguredError(
                f"StubProvider was given no payload for role {role}; the test did not set one up"
            )
        return self._result(payload if isinstance(payload, str) else json.dumps(payload), role)

    def _result(self, text: str, role: Role) -> ProviderResult:
        from app.ai.provider import extract_json_payload

        payload = extract_json_payload(text)
        validated = None
        if isinstance(payload, dict):
            from app.ai.schemas import ROLE_SCHEMAS

            try:
                validated = ROLE_SCHEMAS[role].model_validate(payload)
            except Exception:
                validated = None
        return ProviderResult(
            text=text,
            model=self.model,
            provider=self.name,
            latency_ms=12,
            attempts=1,
            validated=validated,
        )

    def describe(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "api_key_present": True}


def make_service(store: EvidenceStore, providers: list[Any], *, config: AIConfig | None = None) -> AIService:
    return AIService(
        config=config or make_config(),
        store=store,
        provider_factory=lambda: providers,
        cache=AIServiceCache(ttl_seconds=0),
    )


@pytest.fixture
def stub_provider() -> StubProvider:
    return StubProvider()


# --------------------------------------------------------------------------- #
# transport-level failure simulation
# --------------------------------------------------------------------------- #


def make_transport(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def timeout_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("simulated timeout", request=request)


def status_handler(code: int, body: dict[str, Any] | None = None) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, json=body or {"error": {"message": "simulated"}})

    return handler


def openai_text_handler(text: str, model: str = "test-model") -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": model,
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            },
        )

    return handler


@pytest.fixture
def unconfigured_config() -> AIConfig:
    return make_config(
        primary=ProviderConfig(name="groq", model="test-model", api_key=None, base_url="https://api.groq.com/openai/v1")
    )


__all__ = [
    "REPO_ROOT",
    "POLICY_RULES_VERSION",
    "AutomationClass",
    "StubProvider",
    "make_config",
    "make_service",
    "make_transport",
    "timeout_handler",
    "status_handler",
    "openai_text_handler",
    "OpenAICompatibleProvider",
]