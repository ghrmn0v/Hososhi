"""The AI pipeline: retrieval -> provider -> structured output -> validation.

Pipeline roles: extract, understand, explain, classify.

Rules enforced here:
* only a bounded context from retrieval.py reaches a prompt
* every response is validated against a Pydantic schema
* every cited evidence id must exist in the dataset
* the safety rubric overrides the model's classification
* provider failure falls back, then degrades to a clearly-labelled
  deterministic response with fallback_used=True
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from . import retrieval as retrieval_module
from .config import AIConfig, get_config
from .errors import (
    AIError,
    AIOutputInvalidError,
    ContextInsufficientError,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
    RateLimitedError,
    TimeoutError_,
)
from .prompts import build_prompt
from .provider import BaseProvider, ProviderResult, build_chain, verify_evidence_refs
from .retrieval import EvidenceStore, RetrievedContext, known_evidence_refs, retrieve_context
from .safety import (
    POLICY_RULES_VERSION,
    SafetyDecision,
    apply_amount_threshold,
    classify_safety,
)
from .schemas import (
    AutomationAnalyzeResponse,
    AutomationClassification,
    AutomationClass,
    AutomationStepResult,
    AutomationSummary,
    EvidenceItem,
    EvidenceListResponse,
    ExtractionResult,
    Role,
    StepExplanation,
    StepIntelligenceResponse,
    StepUnderstanding,
)

# Truncation limits keep any single evidence item from dominating a prompt.
MAX_SNIPPET_CHARS = 320


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _trim(items: Sequence[EvidenceItem], limit: int = MAX_SNIPPET_CHARS) -> list[EvidenceItem]:
    trimmed: list[EvidenceItem] = []
    for item in items:
        trimmed.append(
            item if len(item.snippet) <= limit else item.model_copy(update={"snippet": item.snippet[: limit - 1] + "…"})
        )
    return trimmed


# --------------------------------------------------------------------------- #
# in-process cache so the demo is not latency-bound
# --------------------------------------------------------------------------- #


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


@dataclass
class AIServiceCache:
    ttl_seconds: int = 900
    _entries: dict[str, _CacheEntry] = field(default_factory=dict)

    def get(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= time.time():
            self._entries.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any) -> None:
        self._entries[key] = _CacheEntry(value, time.time() + self.ttl_seconds)

    def clear(self) -> None:
        self._entries.clear()

    def warm(self, entries: dict[str, Any], ttl_seconds: int | None = None) -> None:
        self.clear()
        for key, value in entries.items():
            if ttl_seconds is not None:
                self._entries[key] = _CacheEntry(value, time.time() + ttl_seconds)
            else:
                self.set(key, value)


_CACHE = AIServiceCache()


def get_cache() -> AIServiceCache:
    return _CACHE


def _cache_key(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


# --------------------------------------------------------------------------- #
# provider invocation with fallback chain
# --------------------------------------------------------------------------- #


@dataclass
class Invocation:
    result: ProviderResult
    provider: str
    model: str
    latency_ms: int
    attempts: int
    fallback_used: bool
    errors: list[str] = field(default_factory=list)


def call_provider(
    prompt: str,
    role: Role,
    *,
    chain: Sequence[BaseProvider] | None = None,
    config: AIConfig | None = None,
    timeout: float | None = None,
    repair_attempts: int = 1,
) -> Invocation:
    """primary -> fallback. Raises the last typed error if everything fails."""
    active_config = config or get_config()
    providers = list(chain) if chain is not None else build_chain(active_config)
    if not providers:
        raise ProviderNotConfiguredError(
            "no AI provider is configured for this call (set AI_PROVIDER and AI_API_KEY)"
        )
    errors: list[str] = []

    invalid_errors: list[str] = []

    for index, provider in enumerate(providers):
        try:
            result = provider.complete(prompt, role, timeout=timeout)
        except AIOutputInvalidError as exc:
            # Malformed body: one repair attempt, then AI_OUTPUT_INVALID.
            invalid_errors.append(f"{provider.name}: {exc.code}: {exc.message}")
            result = None
            for _ in range(max(0, repair_attempts)):
                try:
                    result = provider.complete(prompt + REPAIR_SUFFIX, role, timeout=timeout)
                    break
                except AIOutputInvalidError as repair_exc:
                    invalid_errors.append(f"{provider.name}: repair failed: {repair_exc.message}")
                except AIError as repair_exc:
                    errors.append(f"{provider.name}: repair failed: {repair_exc.code}")
                    break
            if result is None:
                continue
        except AIError as exc:
            errors.append(f"{provider.name}: {exc.code}: {exc.message}")
            continue

        if result.validated is None:  # pragma: no cover - adapters raise instead
            invalid_errors.append(f"{provider.name}: AI_OUTPUT_INVALID")
            continue

        return Invocation(
            result=result,
            provider=provider.name,
            model=result.model or provider.model,
            latency_ms=result.latency_ms,
            attempts=result.attempts,
            fallback_used=index > 0,
            errors=errors,
        )

    if invalid_errors and not errors:
        raise AIOutputInvalidError(
            "every configured provider returned output that failed schema validation",
            details={"attempts": invalid_errors},
        )
    if errors and any("RATE_LIMITED" in item for item in errors):
        raise RateLimitedError(
            "every configured provider was rate limited",
            details={"attempts": errors},
        )
    if errors and any("TIMEOUT" in item for item in errors):
        raise TimeoutError_(
            "every configured provider timed out",
            details={"attempts": errors},
        )
    raise ProviderUnavailableError(
        "no configured AI provider could serve the request",
        details={"attempts": errors},
    )


REPAIR_SUFFIX = (
    "\n\nYour previous response could not be parsed or validated. Return ONLY a single "
    "valid JSON object matching the output schema exactly. No markdown, no explanation."
)


# --------------------------------------------------------------------------- #
# deterministic fallback (clearly labelled, never silent)
# --------------------------------------------------------------------------- #


def _deterministic_explanation(context: RetrievedContext, *, generated_at: str) -> StepIntelligenceResponse:
    step = context.step
    refs = context.evidence_refs
    if not refs:
        return StepIntelligenceResponse(
            step_id=str(step["id"]),
            question="Why does this step exist?",
            summary="Not enough evidence in the dataset to explain this step.",
            answer=(
                "No relevant policy, decision or incident was retrieved for this step, so Hososhi "
                "cannot ground an explanation. This is a fallback response produced without a model "
                "call; no AI output was generated."
            ),
            confidence=0.0,
            evidence=[],
            model="deterministic-fallback",
            generated_at=generated_at,
            fallback_used=True,
            insufficient_context=True,
            assumptions=["No model provider was available; no model output is present in this answer."],
        )

    top = context.evidence[:3]
    summary = f"This step exists because {top[0].title} ({top[0].ref}) applies to this request."
    answer = (
        f"The step '{step.get('name')}' performs: {step.get('description', '').strip()} "
        f"According to {top[0].title} ({top[0].ref}), {top[0].snippet} "
        + (
            f"A further relevant item is {top[1].title} ({top[1].ref})."
            if len(top) > 1
            else "No further items were retrieved."
        )
        + " This answer was assembled deterministically from the retrieved evidence because no AI "
        "provider was available; it was not generated by a language model."
    )
    return StepIntelligenceResponse(
        step_id=str(step["id"]),
        question="Why does this step exist?",
        summary=summary,
        answer=answer,
        confidence=round(min(top[0].relevance, 0.5), 4),
        evidence=top,
        model="deterministic-fallback",
        generated_at=generated_at,
        fallback_used=True,
        assumptions=[
            "Deterministic fallback: no model provider answered. This text was not generated by a language model."
        ],
    )


# --------------------------------------------------------------------------- #
# public service API
# --------------------------------------------------------------------------- #


class AIService:
    """The module Developer 1's core backend calls. No FastAPI imports here."""

    def __init__(
        self,
        *,
        config: AIConfig | None = None,
        store: EvidenceStore | None = None,
        chain: Sequence[BaseProvider] | None = None,
        cache: AIServiceCache | None = None,
        provider_factory: Callable[[], Sequence[BaseProvider]] | None = None,
    ) -> None:
        self.config = config or get_config()
        self.store = store or retrieval_module.get_store()
        self._chain = list(chain) if chain is not None else None
        self._provider_factory = provider_factory
        self.cache = cache if cache is not None else _CACHE

    # -- plumbing ---------------------------------------------------------- #

    def _providers(self) -> Sequence[BaseProvider]:
        if self._provider_factory is not None:
            return self._provider_factory()
        if self._chain is not None:
            return self._chain
        return build_chain(self.config)

    def retrieve(
        self,
        step_id: str,
        *,
        evidence_type: str | None = None,
        request_id: str | None = None,
    ) -> RetrievedContext:
        return retrieve_context(
            step_id,
            store=self.store,
            config=self.config,
            evidence_type=evidence_type,
            request_id=request_id,
        )

    def _invoke(
        self,
        role: Role,
        context: RetrievedContext,
        *,
        question: str | None = None,
        timeout: float | None = None,
    ) -> Invocation:
        prompt = build_prompt(role, context, question=question)
        return call_provider(
            prompt,
            role,
            chain=self._providers(),
            config=self.config,
            timeout=timeout,
        )

    # -- role: extract ----------------------------------------------------- #

    def extract(self, step_id: str, *, timeout: float | None = None) -> ExtractionResult:
        context = self.retrieve(step_id)
        invocation = self._invoke(Role.EXTRACT, context, timeout=timeout)
        result = invocation.result.validated
        assert isinstance(result, ExtractionResult)
        verify_evidence_refs(result.evidence_refs, known_evidence_refs(self.store))
        return result

    # -- role: understand -------------------------------------------------- #

    def understand(self, step_id: str, *, timeout: float | None = None) -> StepUnderstanding:
        context = self.retrieve(step_id)
        invocation = self._invoke(Role.UNDERSTAND, context, timeout=timeout)
        result = invocation.result.validated
        assert isinstance(result, StepUnderstanding)
        verify_evidence_refs(result.evidence_refs, known_evidence_refs(self.store))
        return result

    # -- role: explain (endpoint 6) ---------------------------------------- #

    def explain_step(
        self,
        step_id: str,
        *,
        question: str | None = None,
        timeout: float | None = None,
        request_id: str | None = None,
        use_cache: bool = True,
    ) -> StepIntelligenceResponse:
        step = self.store.get_step(step_id)
        if step is None:
            raise KeyError(step_id)

        key = _cache_key("intelligence", step_id, question or "why", request_id or "-")
        if use_cache and self.config.cache_enabled:
            cached = self.cache.get(key)
            if cached is not None:
                return cached.model_copy(update={"generated_at": _now_iso()})

        context = self.retrieve(step_id, request_id=request_id)
        generated_at = _now_iso()
        evidence = _trim(context.evidence)

        try:
            invocation = self._invoke(Role.EXPLAIN, context, question=question, timeout=timeout)
        except ContextInsufficientError:
            response = StepIntelligenceResponse(
                step_id=step_id,
                question=question or "Why does this step exist?",
                summary="The retrieved evidence is not sufficient to answer the question.",
                answer=(
                    "The evidence retrieved for this step does not support a grounded answer. "
                    "Hososhi is reporting insufficient context rather than guessing."
                ),
                confidence=0.0,
                evidence=evidence,
                model=(self.config.primary.model or "unknown"),
                generated_at=generated_at,
                fallback_used=False,
                insufficient_context=True,
                assumptions=["Model reported insufficient_context for the retrieved evidence."],
            )
            if use_cache and self.config.cache_enabled:
                self.cache.set(key, response)
            return response
        except ProviderNotConfiguredError:
            if not self.config.allow_deterministic_fallback:
                raise
            response = _deterministic_explanation(context, generated_at=generated_at)
            if use_cache and self.config.cache_enabled:
                self.cache.set(key, response)
            return response
        except (ProviderUnavailableError, RateLimitedError, TimeoutError_):
            if not self.config.allow_deterministic_fallback:
                raise
            response = _deterministic_explanation(context, generated_at=generated_at)
            if use_cache and self.config.cache_enabled:
                self.cache.set(key, response)
            return response

        result = invocation.result.validated
        assert isinstance(result, StepExplanation)
        verify_evidence_refs(result.evidence_refs, known_evidence_refs(self.store))

        by_ref = {item.ref: item for item in evidence}
        cited = [by_ref[ref] for ref in result.evidence_refs if ref in by_ref]

        response = StepIntelligenceResponse(
            step_id=step_id,
            question=result.question or question or "Why does this step exist?",
            summary=result.summary or result.answer[:200],
            answer=result.answer,
            confidence=result.confidence,
            evidence=_trim(cited) if cited else evidence,
            model=f"{invocation.provider}/{invocation.model}",
            generated_at=generated_at,
            fallback_used=invocation.fallback_used,
            insufficient_context=result.insufficient_context,
            assumptions=result.assumptions,
            conflicts=result.conflicts,
        )
        if use_cache and self.config.cache_enabled:
            self.cache.set(key, response)
        return response

    # -- endpoint 7 -------------------------------------------------------- #

    def list_evidence(
        self,
        workflow_id: str | None = None,
        *,
        step_id: str | None,
        evidence_type: str | None = None,
    ) -> EvidenceListResponse:
        context = self.retrieve(step_id, evidence_type=evidence_type)
        items = _trim(context.evidence)
        return EvidenceListResponse(
            workflow_id=workflow_id or (self.store.workflow or {}).get("id"),
            step_id=step_id,
            evidence=items,
            returned=len(items),
            retrieval=context.describe(),
        )

    # -- role: classify (endpoint 8) --------------------------------------- #

    def analyze_automation(
        self,
        workflow_id: str,
        *,
        step_ids: Sequence[str] | None = None,
        amounts: dict[str, float | None] | None = None,
        timeout: float | None = None,
    ) -> AutomationAnalyzeResponse:
        known_workflow_id = (self.store.workflow or {}).get("id")
        if known_workflow_id and workflow_id and workflow_id != known_workflow_id:
            raise KeyError(f"unknown workflow id: {workflow_id}")

        steps = [step for step in self.store.steps if not step_ids or step.get("id") in step_ids]
        if not steps:
            raise KeyError(f"no steps found for workflow {workflow_id}")

        results: list[AutomationStepResult] = []
        model_label = f"{self.config.primary.name}/{self.config.primary.model}" if self.config.primary.is_configured else "deterministic-fallback"
        fallback_used = False
        generated_at = _now_iso()

        for step in steps:
            step_id = str(step["id"])
            context = self.retrieve(step_id)
            conflicting = _has_conflicting_evidence(context)
            model_class: AutomationClass | None = None
            model_reason = ""
            model_confidence = 0.0
            insufficient = False
            refs: list[str] = []

            if not self.config.primary.is_configured:
                # No provider at all: the rubric classifies, and the response is
                # labelled as deterministic so the UI and the submission can say so.
                fallback_used = True
            else:
                try:
                    invocation = self._invoke(Role.CLASSIFY, context, timeout=timeout)
                    raw = invocation.result.validated
                    assert isinstance(raw, AutomationClassification)
                    verify_evidence_refs(raw.evidence_refs, known_evidence_refs(self.store))
                    model_class = raw.automation_class
                    model_reason = raw.reason
                    model_confidence = raw.confidence
                    insufficient = raw.insufficient_context
                    refs = raw.evidence_refs
                    model_label = f"{invocation.provider}/{invocation.model}"
                    fallback_used = fallback_used or invocation.fallback_used
                except (
                    ProviderNotConfiguredError,
                    ProviderUnavailableError,
                    RateLimitedError,
                    TimeoutError_,
                    AIOutputInvalidError,
                    ContextInsufficientError,
                ):
                    fallback_used = True

            decision: SafetyDecision = classify_safety(
                step,
                model_class=model_class,
                model_reason=model_reason,
                model_confidence=model_confidence,
                insufficient_context=insufficient or not context.evidence,
                conflicting_evidence=conflicting,
            )
            amount = (amounts or {}).get(step_id)
            decision = apply_amount_threshold(decision, amount=amount)

            results.append(
                AutomationStepResult(
                    step_id=step_id,
                    name=str(step.get("name") or ""),
                    automation_class=decision.automation_class,
                    reason=decision.reason,
                    confidence=decision.confidence,
                    requires_approval=decision.requires_approval,
                    safety_override=decision.safety_override,
                    override_reason=decision.override_reason,
                    evidence_refs=refs or context.evidence_refs[:3],
                    model=model_label if model_class is not None else "deterministic-fallback",
                )
            )

        summary = AutomationSummary(
            safe=sum(1 for item in results if item.automation_class is AutomationClass.SAFE),
            human_review=sum(1 for item in results if item.automation_class is AutomationClass.HUMAN_REVIEW),
            human_required=sum(1 for item in results if item.automation_class is AutomationClass.HUMAN_REQUIRED),
        )
        return AutomationAnalyzeResponse(
            workflow_id=workflow_id,
            policy_rules_version=POLICY_RULES_VERSION,
            summary=summary,
            steps=results,
            model=model_label,
            generated_at=generated_at,
            fallback_used=fallback_used,
        )

    # -- disclosure ------------------------------------------------------- #

    def meta(self) -> dict[str, Any]:
        config = self.config.describe()
        return {
            "ai_provider": config["primary"]["provider"],
            "ai_model": config["primary"]["model"],
            "ai_fallback_provider": (config["fallback"] or {}).get("provider") if config["fallback"] else None,
            "ai_fallback_model": (config["fallback"] or {}).get("model") if config["fallback"] else None,
            "ai_provider_configured": config["primary"]["api_key_present"],
            "ai_policy_rules_version": POLICY_RULES_VERSION,
            "ai_context_evidence_cap": config["context_evidence_cap"],
            "ai_context_event_cap": config["context_event_cap"],
            "ai_dataset": "synthetic",
            "generated_at": _now_iso(),
        }


CONFLICT_RELEVANCE_FLOOR = 0.40

_PERMITTING_MARKERS = (
    "do not require",
    "does not require",
    "not require manager",
    "may be converted directly",
    "without manager approval",
)
_REQUIRING_MARKERS = (
    "must be approved",
    "must not",
    "requires approval",
    "requires explicit",
    "is mandatory",
)
_UNRESOLVED_MARKERS = ("unresolved", "left open", "no decision", "pending decision")


def _step_topic_tokens(step: dict[str, Any]) -> set[str]:
    """Stems of the step's own declared keywords only - not the shared topic hints."""
    return retrieval_module._stems(
        retrieval_module._tokenize(" ".join(str(k) for k in step.get("keywords") or []))
    )


# One shared keyword ("request", "amount") is too weak to call a piece of
# evidence about this step. Two independent ones is the bar.
TOPICAL_OVERLAP_MIN = 2


def _is_topical(item: EvidenceItem, step_tokens: set[str]) -> bool:
    item_tokens = retrieval_module._stems(
        retrieval_module._tokenize(f"{item.title} {item.snippet}")
    )
    return len(step_tokens & item_tokens) >= TOPICAL_OVERLAP_MIN


# A policy conflict only changes a *classification* when the step is itself a
# policy/threshold check. For every other step the same conflict lowers the
# explanation's confidence but does not change what the step may be.
CONFLICT_SENSITIVE_STEP_TYPES = {"policy_check"}
CONFLICT_SENSITIVE_KEYWORDS = ("policy", "rule", "threshold", "compliance", "allowance")


def _is_conflict_sensitive(step: dict[str, Any]) -> bool:
    if str(step.get("type") or "").lower() in CONFLICT_SENSITIVE_STEP_TYPES:
        return True
    keywords = " ".join(str(k).lower() for k in step.get("keywords") or [])
    return any(marker in keywords for marker in CONFLICT_SENSITIVE_KEYWORDS)


def _has_conflicting_evidence(context: RetrievedContext) -> bool:
    """Do the *retrieved, topically relevant* evidence items for this step disagree?

    Scoped deliberately, so an unrelated contradiction elsewhere in the dataset
    cannot downgrade an ordinary step:

    * only policy-check / threshold steps are considered;
    * only items retrieval already scored above the relevance floor count;
    * an item must share at least two keyword stems with the step, so a single
      shared word like "request" is not enough.
    """
    if not _is_conflict_sensitive(context.step):
        return False

    relevant = [item for item in context.evidence if item.relevance >= CONFLICT_RELEVANCE_FLOOR]
    if not relevant:
        return False

    step_tokens = _step_topic_tokens(context.step)
    topical = [item for item in relevant if _is_topical(item, step_tokens)]
    if not topical:
        return False

    policies = [item for item in topical if item.type == "policy"]
    permitting = [item for item in policies if any(m in item.snippet.lower() for m in _PERMITTING_MARKERS)]
    requiring = [item for item in policies if any(m in item.snippet.lower() for m in _REQUIRING_MARKERS)]
    if len(policies) >= 2 and permitting and requiring:
        return True

    decisions = [item for item in topical if item.type == "decision"]
    if any(any(marker in item.snippet.lower() for marker in _UNRESOLVED_MARKERS) for item in decisions):
        return True

    return False


def default_service() -> AIService:
    return AIService()


def serialize_for_log(payload: Any) -> str:
    """Small helper used by tests; keeps logging compact and key-free."""
    return json.dumps(payload if isinstance(payload, dict) else payload.model_dump(), sort_keys=True, default=str)


__all__ = [
    "AIService",
    "AIServiceCache",
    "default_service",
    "call_provider",
    "serialize_for_log",
]