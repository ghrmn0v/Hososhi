"""AI layer for Hososhi. Developer 2 owns everything under backend/app/ai/."""

from __future__ import annotations

from .config import AIConfig, ProviderConfig, get_config, reset_config_cache
from .errors import (
    AIError,
    AIOutputInvalidError,
    ContextInsufficientError,
    HallucinatedEvidenceError,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
    RateLimitedError,
    TimeoutError_,
)
from .pipeline import AIService, AIServiceCache, default_service, get_cache
from .provider import BaseProvider, build_chain, build_provider
from .safety import POLICY_RULES_VERSION, classify_safety
from .schemas import (
    AutomationClass,
    AutomationAnalyzeResponse,
    EvidenceItem,
    Role,
    StepIntelligenceResponse,
)

__all__ = [
    "AIConfig",
    "ProviderConfig",
    "get_config",
    "reset_config_cache",
    "AIError",
    "AIOutputInvalidError",
    "ContextInsufficientError",
    "HallucinatedEvidenceError",
    "ProviderNotConfiguredError",
    "ProviderUnavailableError",
    "RateLimitedError",
    "TimeoutError_",
    "AIService",
    "AIServiceCache",
    "default_service",
    "get_cache",
    "BaseProvider",
    "build_chain",
    "build_provider",
    "POLICY_RULES_VERSION",
    "classify_safety",
    "AutomationClass",
    "AutomationAnalyzeResponse",
    "EvidenceItem",
    "Role",
    "StepIntelligenceResponse",
]