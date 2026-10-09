"""Provider failure handling: timeout, rate limit, 5xx, malformed, auth (AI-08)."""

from __future__ import annotations

import httpx
import pytest

import dataclasses
import json

from app.ai.config import ProviderConfig
from app.ai.errors import (
    AIError,
    AIOutputInvalidError,
    AuthError,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
    RateLimitedError,
    TimeoutError_,
)
from app.ai.pipeline import call_provider
from app.ai.provider import GeminiProvider, OpenAICompatibleProvider, build_chain, build_provider
from app.ai.schemas import Role

from tests.ai.conftest import make_config, openai_text_handler, status_handler, timeout_handler

VALID_EXPLAIN_PAYLOAD = {
    "summary": "s",
    "answer": "Because POL-PR-07 sets a price variance tolerance.",
    "confidence": 0.8,
    "evidence_refs": ["POL-PR-07"],
}


def _provider(handler, config=None):
    active = config or make_config()
    return build_provider(active.primary, transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------------- #
# typed errors, no tracebacks
# --------------------------------------------------------------------------- #


def test_timeout_is_typed_and_retryable():
    provider = _provider(timeout_handler)
    with pytest.raises(TimeoutError_) as excinfo:
        provider.complete("p", Role.EXPLAIN)
    assert excinfo.value.code == "TIMEOUT"
    assert excinfo.value.retryable is True
    assert excinfo.value.http_status == 503


def test_rate_limit_is_typed_and_429():
    provider = _provider(status_handler(429))
    with pytest.raises(RateLimitedError) as excinfo:
        provider.complete("p", Role.EXPLAIN)
    assert excinfo.value.code == "RATE_LIMITED"
    assert excinfo.value.http_status == 429
    assert excinfo.value.retryable is True


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_5xx_is_provider_unavailable(status):
    provider = _provider(status_handler(status))
    with pytest.raises(ProviderUnavailableError) as excinfo:
        provider.complete("p", Role.EXPLAIN)
    assert excinfo.value.code == "PROVIDER_UNAVAILABLE"
    assert excinfo.value.http_status == 503


@pytest.mark.parametrize("status", [401, 403])
def test_bad_key_is_auth_error_and_not_retryable(status):
    provider = _provider(status_handler(status))
    with pytest.raises(AuthError) as excinfo:
        provider.complete("p", Role.EXPLAIN)
    assert excinfo.value.retryable is False


def test_malformed_json_is_ai_output_invalid():
    provider = _provider(openai_text_handler("this is not json at all"))
    with pytest.raises(AIOutputInvalidError) as excinfo:
        provider.complete("p", Role.EXPLAIN)
    assert excinfo.value.http_status == 422


def test_empty_response_is_ai_output_invalid():
    provider = _provider(openai_text_handler("   "))
    with pytest.raises(AIOutputInvalidError):
        provider.complete("p", Role.EXPLAIN)


def test_no_choices_is_ai_output_invalid():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "m"})

    with pytest.raises(AIOutputInvalidError):
        _provider(handler).complete("p", Role.EXPLAIN)


def test_missing_required_field_is_ai_output_invalid():
    provider = _provider(openai_text_handler('{"summary": "s"}'))  # no answer, no confidence
    with pytest.raises(AIOutputInvalidError):
        provider.complete("p", Role.EXPLAIN)


def test_unknown_classification_value_is_rejected_at_the_provider():
    payload = {"automation_class": "AUTOMATED", "reason": "r", "confidence": 0.5, "requires_approval": False}
    provider = _provider(openai_text_handler(__import__("json").dumps(payload)))
    with pytest.raises(AIOutputInvalidError):
        provider.complete("p", Role.CLASSIFY)


def test_unconfigured_provider_raises_typed_error_not_attribute_error():
    config = make_config(primary=ProviderConfig(name="groq", model="m", api_key=None, base_url="https://api.groq.com/openai/v1"))
    provider = build_provider(config.primary)
    with pytest.raises(ProviderNotConfiguredError) as excinfo:
        provider.complete("p", Role.EXPLAIN)
    assert excinfo.value.code == "PROVIDER_UNAVAILABLE"


def test_unknown_provider_name_is_rejected_at_build_time():
    with pytest.raises(ProviderNotConfiguredError):
        build_provider(ProviderConfig(name="not-a-provider", model="m", api_key="k", base_url="https://x"))


# --------------------------------------------------------------------------- #
# error envelope shape (shared contract)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError_("t"),
        RateLimitedError("r"),
        ProviderUnavailableError("u"),
        AIOutputInvalidError("i"),
    ],
)
def test_error_envelope_matches_the_frozen_contract(error: AIError):
    envelope = error.to_envelope("req_test123")
    assert set(envelope) == {"error"}
    assert set(envelope["error"]) == {"code", "message", "retryable", "request_id"}
    assert envelope["error"]["request_id"] == "req_test123"
    assert isinstance(envelope["error"]["retryable"], bool)


# --------------------------------------------------------------------------- #
# fallback chain
# --------------------------------------------------------------------------- #


def test_fallback_provider_is_used_when_the_primary_fails(config):
    dead = build_provider(config.primary, transport=httpx.MockTransport(timeout_handler))
    alive = build_provider(
        dataclasses.replace(config.primary, name="cerebras", base_url="https://api.cerebras.ai/v1"),
        transport=httpx.MockTransport(openai_text_handler(json.dumps(VALID_EXPLAIN_PAYLOAD))),
    )
    invocation = call_provider("p", Role.EXPLAIN, chain=[dead, alive], config=config)
    assert invocation.fallback_used is True
    assert invocation.provider == "cerebras"
    assert invocation.errors and "TIMEOUT" in invocation.errors[0]


def test_all_providers_failing_raises_the_dominant_typed_error(config):
    dead = build_provider(config.primary, transport=httpx.MockTransport(timeout_handler))
    with pytest.raises(TimeoutError_):
        call_provider("p", Role.EXPLAIN, chain=[dead], config=config)


def test_all_providers_rate_limited_raises_rate_limited(config):
    limited = build_provider(config.primary, transport=httpx.MockTransport(status_handler(429)))
    with pytest.raises(RateLimitedError):
        call_provider("p", Role.EXPLAIN, chain=[limited], config=config)


def test_chain_from_config_has_primary_then_fallback():
    config = make_config(
        primary=ProviderConfig(name="groq", model="a", api_key="k", base_url="https://api.groq.com/openai/v1"),
        fallback=ProviderConfig(name="cerebras", model="b", api_key="k2", base_url="https://api.cerebras.ai/v1"),
    )
    chain = build_chain(config)
    assert [provider.name for provider in chain] == ["groq", "cerebras"]


def test_no_fallback_configured_means_a_single_element_chain():
    assert len(build_chain(make_config())) == 1


def test_malformed_body_gets_one_repair_attempt_then_invalid():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return openai_text_handler("still not json")(request)

    provider = _provider(handler)
    with pytest.raises(AIOutputInvalidError):
        call_provider("p", Role.EXPLAIN, chain=[provider], config=make_config(), repair_attempts=1)
    assert calls["n"] == 2  # original + exactly one repair


def test_repair_path_recovers_a_fenced_response():
    responses = ["```json\n" + __import__("json").dumps(VALID_EXPLAIN_PAYLOAD) + "\n```"]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        text = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return openai_text_handler(text)(request)

    # The fenced payload is valid after repair-free extraction, so one call suffices.
    invocation = call_provider("p", Role.EXPLAIN, chain=[_provider(handler)], config=make_config())
    assert invocation.result.validated is not None


# --------------------------------------------------------------------------- #
# adapter coverage
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["groq", "cerebras", "nvidia", "openrouter"])
def test_every_openai_compatible_provider_is_constructible(name):
    from app.ai.config import PROVIDER_DEFAULT_BASE_URLS

    config = ProviderConfig(name=name, model="m", api_key="k", base_url=PROVIDER_DEFAULT_BASE_URLS[name])
    provider = build_provider(config)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.describe()["api_key_present"] is True


def test_openai_compatible_requires_an_explicit_base_url():
    """A generic adapter has no default host: the team must state it."""
    config = ProviderConfig(name="openai_compatible", model="m", api_key="k", base_url="")
    assert config.is_configured is False
    assert build_provider(config).describe()["api_key_present"] is False
    with pytest.raises(ProviderNotConfiguredError):
        build_provider(config).complete("p", Role.EXPLAIN)


def test_gemini_adapter_parses_candidates():
    config = ProviderConfig(
        name="gemini",
        model="gemini-2.0-flash",
        api_key="k",
        base_url="https://generativelanguage.googleapis.com/v1beta",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "generateContent" in str(request.url)
        assert "responseMimeType" in request.content.decode()
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": __import__("json").dumps(VALID_EXPLAIN_PAYLOAD)}]}}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 20, "totalTokenCount": 30},
            },
        )

    provider = build_provider(config, transport=httpx.MockTransport(handler))
    result = provider.complete("p", Role.EXPLAIN)
    assert result.validated is not None
    assert result.usage["totalTokenCount"] == 30
    assert isinstance(provider, GeminiProvider)


def test_gemini_no_candidates_is_provider_unavailable():
    config = ProviderConfig(name="gemini", model="m", api_key="k", base_url="https://x/v1beta")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"message": "blocked"}})

    with pytest.raises(ProviderUnavailableError):
        build_provider(config, transport=httpx.MockTransport(handler)).complete("p", Role.EXPLAIN)


def test_api_key_is_never_in_the_describe_output():
    config = make_config()
    described = build_provider(config.primary).describe()
    assert described["api_key_present"] is True
    assert "api_key" not in described
    assert config.primary.api_key not in str(described)


def test_timeout_is_bounded_so_the_ui_cannot_hang():
    """A hung provider must surface as a typed error, not an unbounded wait."""
    import time

    provider = _provider(timeout_handler)
    started = time.perf_counter()
    with pytest.raises(TimeoutError_):
        provider.complete("p", Role.EXPLAIN, timeout=0.5)
    assert time.perf_counter() - started < 3.0