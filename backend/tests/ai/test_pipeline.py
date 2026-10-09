"""The pipeline: evidence-backed explanation, endpoint contracts, fallback behaviour."""

from __future__ import annotations

import pytest

from app.ai.config import ProviderConfig
from app.ai.errors import AIOutputInvalidError, ProviderNotConfiguredError, ProviderUnavailableError
from app.ai.pipeline import AIService, AIServiceCache, default_service
from app.ai.schemas import AutomationClass, Role

from tests.ai.conftest import StubProvider, make_config, make_service

GOOD_EXPLAIN = {
    "step_id": "stp_price",
    "question": "Why does this step exist?",
    "summary": "Price is verified because a variance tolerance policy applies.",
    "answer": (
        "The Verify Price step exists to enforce POL-PR-07, which limits catalogue price variance. "
        "A 22 percent deviation was recorded on pr_0001, and INC-38 shows what happened when this "
        "check was skipped. The step therefore acts before any spend is committed."
    ),
    "confidence": 0.87,
    "evidence_refs": ["POL-PR-07", "INC-38"],
}


def _service_with(payloads, store, **config_kwargs):
    return make_service(store, [StubProvider(payloads=payloads)], config=make_config(**config_kwargs))


# --------------------------------------------------------------------------- #
# endpoint 6 - step intelligence
# --------------------------------------------------------------------------- #


def test_intelligence_returns_answer_evidence_confidence_and_model(store):
    service = _service_with({Role.EXPLAIN: GOOD_EXPLAIN}, store)
    response = service.explain_step("stp_price")

    assert response.step_id == "stp_price"
    assert response.question == "Why does this step exist?"
    assert response.answer.strip()
    assert response.summary.strip()
    assert 0.0 <= response.confidence <= 1.0
    assert response.evidence, "at least one evidence item is required"
    assert response.model == "stub/stub-model"
    assert response.generated_at.endswith("Z")
    assert response.fallback_used is False


def test_intelligence_evidence_ids_exist_in_the_dataset(store):
    service = _service_with({Role.EXPLAIN: GOOD_EXPLAIN}, store)
    allowed = {record["id"] for _, record in store.all_records()}
    for item in service.explain_step("stp_price").evidence:
        assert item.ref in allowed


def test_intelligence_honours_the_frozen_response_shape(store):
    from app.ai.schemas import StepIntelligenceResponse

    service = _service_with({Role.EXPLAIN: GOOD_EXPLAIN}, store)
    payload = service.explain_step("stp_price").model_dump()
    assert set(StepIntelligenceResponse.model_fields).issubset(payload)
    assert set(payload["evidence"][0]) >= {"ref", "type", "title", "snippet", "relevance", "date"}


def test_hallucinated_evidence_id_is_rejected(store):
    bad = dict(GOOD_EXPLAIN, evidence_refs=["POL-PR-07", "POL-DOES-NOT-EXIST"])
    from app.ai.errors import HallucinatedEvidenceError

    with pytest.raises(HallucinatedEvidenceError):
        _service_with({Role.EXPLAIN: bad}, store).explain_step("stp_price")


def test_insufficient_context_is_an_honest_answer_not_an_error(store):
    payload = dict(
        GOOD_EXPLAIN,
        summary="The evidence does not support an answer.",
        answer="The retrieved evidence is insufficient to explain this step.",
        confidence=0.0,
        evidence_refs=[],
        insufficient_context=True,
    )
    response = _service_with({Role.EXPLAIN: payload}, store).explain_step("stp_price")
    assert response.insufficient_context is True
    assert response.confidence == 0.0
    assert "insufficient" in response.answer.lower()


def test_unknown_step_raises_key_error(store):
    with pytest.raises(KeyError):
        _service_with({Role.EXPLAIN: GOOD_EXPLAIN}, store).explain_step("stp_nope")


def test_intelligence_is_cached_for_the_demo(store):
    provider = StubProvider(payloads={Role.EXPLAIN: GOOD_EXPLAIN})
    service = make_service(
        store,
        [provider],
        config=make_config(cache_enabled=True, cache_ttl_seconds=60),
    )
    service.cache = AIServiceCache(ttl_seconds=60)
    first = service.explain_step("stp_price")
    second = service.explain_step("stp_price")
    assert provider.calls == 1
    assert first.answer == second.answer


def test_cache_can_be_disabled(store):
    provider = StubProvider(payloads={Role.EXPLAIN: GOOD_EXPLAIN})
    service = make_service(store, [provider])
    service.explain_step("stp_price")
    service.explain_step("stp_price")
    assert provider.calls == 2


# --------------------------------------------------------------------------- #
# endpoint 7 - evidence list
# --------------------------------------------------------------------------- #


def test_evidence_endpoint_returns_ranked_items_with_ids(store):
    response = _service_with({Role.EXPLAIN: GOOD_EXPLAIN}, store).list_evidence(step_id="stp_price")
    assert response.workflow_id == "wf_purchase_request"
    assert response.step_id == "stp_price"
    assert response.returned == len(response.evidence)
    assert response.evidence[0].ref == "POL-PR-07"
    assert all(item.type in {"policy", "decision", "incident", "event"} for item in response.evidence)
    assert "scores" in response.retrieval


def test_evidence_endpoint_honours_the_type_filter(store):
    response = _service_with({}, store).list_evidence(step_id="stp_price", evidence_type="decision")
    assert response.evidence
    assert {item.type for item in response.evidence} == {"decision"}


def test_evidence_endpoint_requires_a_step(store):
    with pytest.raises(KeyError):
        _service_with({}, store).list_evidence(step_id="stp_missing")


# --------------------------------------------------------------------------- #
# endpoint 8 - automation analysis
# --------------------------------------------------------------------------- #


def test_analyze_returns_the_frozen_contract_shape(store):
    from app.ai.schemas import AutomationAnalyzeResponse

    response = _service_with({}, store).analyze_automation("wf_purchase_request")
    payload = response.model_dump()
    assert set(AutomationAnalyzeResponse.model_fields).issubset(payload)
    assert payload["policy_rules_version"] == "safety-rules-v1"
    assert set(payload["summary"]) == {"safe", "human_review", "human_required"}
    assert payload["summary"]["human_required"] >= 2


def test_analyze_covers_every_step(store):
    response = _service_with({}, store).analyze_automation("wf_purchase_request")
    assert {step.step_id for step in response.steps} == {step["id"] for step in store.steps}


def test_analyze_unknown_workflow_raises(store):
    with pytest.raises(KeyError):
        _service_with({}, store).analyze_automation("wf_does_not_exist")


# --------------------------------------------------------------------------- #
# deterministic fallback
# --------------------------------------------------------------------------- #


def test_no_provider_falls_back_to_a_labelled_deterministic_answer(store):
    config = make_config(
        primary=ProviderConfig(name="groq", model="m", api_key=None, base_url="https://api.groq.com/openai/v1")
    )
    response = make_service(store, [], config=config).explain_step("stp_price")

    assert response.fallback_used is True
    assert response.model == "deterministic-fallback"
    assert "POL-PR-07" in response.answer
    assert response.evidence[0].ref == "POL-PR-07"
    assert any("not generated by a language model" in note for note in response.assumptions)


def test_deterministic_fallback_never_claims_more_than_the_evidence(store):
    config = make_config(
        primary=ProviderConfig(name="groq", model="m", api_key=None, base_url="https://api.groq.com/openai/v1")
    )
    response = make_service(store, [], config=config).explain_step("stp_price")
    assert response.confidence <= 0.5


def test_deterministic_fallback_can_be_disabled(store):
    config = make_config(
        primary=ProviderConfig(name="groq", model="m", api_key=None, base_url="https://api.groq.com/openai/v1"),
        allow_deterministic_fallback=False,
    )
    with pytest.raises(ProviderNotConfiguredError):
        make_service(store, [], config=config).explain_step("stp_price")


def test_provider_failure_falls_back_but_stays_truthful(store):
    service = _service_with({}, store)
    service._providers = lambda: [
        type(
            "Dead",
            (),
            {
                "name": "dead",
                "model": "dead-model",
                "complete": lambda *a, **k: (_ for _ in ()).throw(ProviderUnavailableError("down")),
            },
        )()
    ]
    response = service.explain_step("stp_price")
    assert response.fallback_used is True
    assert response.model == "deterministic-fallback"


def test_malformed_output_never_reaches_the_frontend_as_valid_data(store):
    """Either a typed 422 or a labelled deterministic answer - never raw text."""
    service = _service_with({Role.EXPLAIN: "this is definitely not json"}, store)
    with pytest.raises(AIOutputInvalidError) as excinfo:
        service.explain_step("stp_price")
    assert excinfo.value.code == "AI_OUTPUT_INVALID"
    assert excinfo.value.http_status == 422


def test_malformed_output_is_distinct_from_a_provider_outage(store):
    """Malformed output is a 422. An outage is a graceful labelled answer."""
    from app.ai.errors import ProviderUnavailableError

    malformed = _service_with({Role.EXPLAIN: "{oops"}, store)
    with pytest.raises(AIOutputInvalidError):
        malformed.explain_step("stp_price")

    def dead(*args, **kwargs):
        raise ProviderUnavailableError("provider is down")

    outage = make_service(store, [StubProvider(payloads={Role.EXPLAIN: GOOD_EXPLAIN})])
    outage._providers = lambda: [type("Dead", (), {"name": "dead", "model": "m", "complete": staticmethod(dead)})()]
    response = outage.explain_step("stp_price")
    assert response.fallback_used is True
    assert response.model == "deterministic-fallback"


# --------------------------------------------------------------------------- #
# other roles
# --------------------------------------------------------------------------- #


def test_extract_role(store):
    payload = {"request_id": "pr_0001", "supplier": "AzLab Supplies", "amount": 18400.0, "department": "Operations", "evidence_refs": ["POL-PR-01"]}
    result = _service_with({Role.EXTRACT: payload}, store).extract("stp_extract", )
    assert result.supplier == "AzLab Supplies"
    assert result.amount == 18400.0


def test_understand_role(store):
    payload = {"step_id": "stp_price", "step_name": "Verify Price", "purpose": "compare catalogue price", "actor_role": "Procurement Specialist", "evidence_refs": ["POL-PR-07"]}
    result = _service_with({Role.UNDERSTAND: payload}, store).understand("stp_price")
    assert result.step_id == "stp_price"
    assert result.actor_role == "Procurement Specialist"


def test_meta_discloses_real_provider_configuration(store):
    config = make_config(
        primary=ProviderConfig(name="groq", model="llama-test", api_key="secret-value", base_url="https://api.groq.com/openai/v1")
    )
    meta = make_service(store, [], config=config).meta()
    assert meta["ai_provider"] == "groq"
    assert meta["ai_model"] == "llama-test"
    assert meta["ai_provider_configured"] is True
    assert meta["ai_dataset"] == "synthetic"
    assert meta["ai_policy_rules_version"] == "safety-rules-v1"
    assert "secret-value" not in str(meta)


def test_default_service_constructs_without_a_provider(store, monkeypatch):
    """Importing and constructing must not require a reachable provider."""
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    service = default_service()
    assert isinstance(service, AIService)
    assert service.config.primary.is_configured is False


def test_ai_output_invalid_error_is_422():
    assert AIOutputInvalidError("x").http_status == 422


def test_automation_class_enum_never_leaks_a_third_value(store):
    response = _service_with({}, store).analyze_automation("wf_purchase_request")
    allowed = {AutomationClass.SAFE, AutomationClass.HUMAN_REVIEW, AutomationClass.HUMAN_REQUIRED}
    assert {step.automation_class for step in response.steps} <= allowed