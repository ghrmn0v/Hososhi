from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_RETRIES = 1
DEFAULT_CONTEXT_EVIDENCE_CAP = 12
DEFAULT_CONTEXT_EVENT_CAP = 15
DEFAULT_CACHE_TTL_SECONDS = 900

SUPPORTED_PROVIDERS = ("gemini", "groq", "cerebras", "nvidia", "openrouter", "openai_compatible")

# Base URLs are read from env with these defaults. They are configuration, not
# published rate limits / pricing / capability claims.
PROVIDER_DEFAULT_BASE_URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "groq": "https://api.groq.com/openai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "openai_compatible": "",
}


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ProviderConfig:
    """Everything needed to talk to one provider. Never contains key values in logs."""

    name: str
    model: str
    api_key: str | None
    base_url: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    supports_json_mode: bool = True

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key) and bool(self.base_url)

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "supports_json_mode": self.supports_json_mode,
            "api_key_present": self.is_configured,
        }


@dataclass(frozen=True)
class AIConfig:
    primary: ProviderConfig
    fallback: ProviderConfig | None = None
    context_evidence_cap: int = DEFAULT_CONTEXT_EVIDENCE_CAP
    context_event_cap: int = DEFAULT_CONTEXT_EVENT_CAP
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    cache_enabled: bool = True
    allow_deterministic_fallback: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        return {
            "primary": self.primary.describe(),
            "fallback": self.fallback.describe() if self.fallback else None,
            "context_evidence_cap": self.context_evidence_cap,
            "context_event_cap": self.context_event_cap,
            "cache_enabled": self.cache_enabled,
            "allow_deterministic_fallback": self.allow_deterministic_fallback,
        }


def _build_provider(
    name: str | None,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
) -> ProviderConfig:
    provider_name = (name or "").strip().lower()
    resolved_key = api_key
    resolved_base = base_url

    if not provider_name:
        return ProviderConfig(
            name="none",
            model=model or "",
            api_key=None,
            base_url="",
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        )

    default_base = PROVIDER_DEFAULT_BASE_URLS.get(provider_name)
    if resolved_base is None:
        resolved_base = default_base or ""

    if resolved_key is None:
        # Per-provider key env vars, so primary and fallback can differ.
        resolved_key = _env(f"AI_{provider_name.upper()}_API_KEY") or _env("AI_API_KEY")

    if model is None:
        resolved_model = _env(f"AI_{provider_name.upper()}_MODEL") or _env("AI_MODEL") or ""
    else:
        resolved_model = model

    return ProviderConfig(
        name=provider_name,
        model=resolved_model,
        api_key=resolved_key,
        base_url=resolved_base,
        timeout_seconds=_env_float("AI_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        max_retries=_env_int("AI_MAX_RETRIES", DEFAULT_MAX_RETRIES),
        supports_json_mode=_env_bool("AI_SUPPORTS_JSON_MODE", True),
    )


@lru_cache(maxsize=1)
def get_config() -> AIConfig:
    return _load_config()


def _load_config() -> AIConfig:
    primary = _build_provider(
        _env("AI_PROVIDER"),
        _env("AI_MODEL"),
        _env("AI_API_KEY"),
        _env("AI_BASE_URL"),
    )
    fallback_name = _env("AI_FALLBACK_PROVIDER")
    fallback: ProviderConfig | None = None
    if fallback_name:
        fallback = _build_provider(
            fallback_name,
            _env("AI_FALLBACK_MODEL"),
            _env("AI_FALLBACK_API_KEY"),
            _env("AI_FALLBACK_BASE_URL"),
        )
        if not fallback.is_configured:
            fallback = None

    return AIConfig(
        primary=primary,
        fallback=fallback,
        context_evidence_cap=_env_int("AI_CONTEXT_EVIDENCE_CAP", DEFAULT_CONTEXT_EVIDENCE_CAP),
        context_event_cap=_env_int("AI_CONTEXT_EVENT_CAP", DEFAULT_CONTEXT_EVENT_CAP),
        cache_ttl_seconds=_env_int("AI_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS),
        cache_enabled=_env_bool("AI_CACHE_ENABLED", True),
        allow_deterministic_fallback=_env_bool("AI_ALLOW_DETERMINISTIC_FALLBACK", True),
    )


def reset_config_cache() -> None:
    """Tests and PHASE 0 key loading use this after mutating os.environ."""
    get_config.cache_clear()