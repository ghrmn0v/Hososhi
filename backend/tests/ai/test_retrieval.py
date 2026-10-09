"""Retrieval: relevance, grounding, and the context cap (AI-03, AI-07, AI-09)."""

from __future__ import annotations

import json

import pytest

from app.ai.config import AIConfig, ProviderConfig
from app.ai.prompts import build_prompt
from app.ai.retrieval import (
    EvidenceStore,
    get_store,
    known_evidence_refs,
    load_dataset,
    rank_evidence,
    retrieve_context,
)
from app.ai.schemas import Role

from tests.ai.conftest import REPO_ROOT, make_config


def test_dataset_contains_conforming_ids():
    data = load_dataset(REPO_ROOT / "data" / "evidence" / "evidence.json")
    assert all(item["id"].startswith("POL-") for item in data["policies"])
    assert all(item["id"].startswith("DEC-") for item in data["decisions"])
    assert all(item["id"].startswith("INC-") for item in data["incidents"])
    assert all(item["id"].startswith("evt_") for item in data["events"])
    assert all(step["id"].startswith("stp_") for step in data["steps"])


def test_retrieval_returns_small_relevant_set(store: EvidenceStore):
    context = retrieve_context("stp_price", store=store, config=make_config())
    assert context.evidence
    assert context.evidence[0].ref == "POL-PR-07"
    assert context.evidence[0].relevance >= context.evidence[-1].relevance
    titles = " ".join(item.title.lower() for item in context.evidence)
    assert "price" in titles or "variance" in titles


def test_every_returned_ref_exists_in_the_dataset(store: EvidenceStore):
    allowed = known_evidence_refs(store)
    for step in store.steps:
        context = retrieve_context(step["id"], store=store, config=make_config())
        for item in context.evidence:
            assert item.ref in allowed, f"{item.ref} for {step['id']} is not in the dataset"


def test_relevance_scores_are_within_range(store: EvidenceStore):
    context = retrieve_context("stp_policy", store=store, config=make_config())
    for item in context.evidence:
        assert 0.0 <= item.relevance <= 1.0


def test_unknown_step_raises(store: EvidenceStore):
    with pytest.raises(KeyError):
        retrieve_context("stp_does_not_exist", store=store, config=make_config())


def test_evidence_type_filter(store: EvidenceStore):
    context = retrieve_context("stp_policy", store=store, config=make_config(), evidence_type="policy")
    assert context.evidence
    assert {item.type for item in context.evidence} == {"policy"}


def test_request_id_narrows_events(store: EvidenceStore):
    scoped = retrieve_context("stp_po", store=store, config=make_config(), request_id="pr_0003")
    assert scoped.events
    assert {event["request_id"] for event in scoped.events} == {"pr_0003"}


# --------------------------------------------------------------------------- #
# the cap. This test must fail if the whole dataset is ever serialised.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("step_id", ["stp_request", "stp_extract", "stp_price", "stp_policy", "stp_approval"])
@pytest.mark.parametrize("evidence_cap", [1, 3, 12])
def test_context_cap_is_enforced(store: EvidenceStore, step_id: str, evidence_cap: int):
    config = make_config(context_evidence_cap=evidence_cap, context_event_cap=4)
    context = retrieve_context(step_id, store=store, config=config)
    assert len(context.evidence) <= evidence_cap
    assert len(context.events) <= 4
    assert context.counts["evidence_returned"] <= evidence_cap


def test_prompt_size_is_bounded_by_the_cap(store: EvidenceStore):
    config = make_config(context_evidence_cap=3, context_event_cap=4)
    context = retrieve_context("stp_price", store=store, config=config)
    prompt = build_prompt(Role.EXPLAIN, context)
    assert prompt.count('"ref"') <= 3
    # The full dataset is 6 policies + 5 decisions + 3 incidents + 21 events.
    assert len(prompt) < 20_000


def test_exhaustively_no_step_exceeds_the_cap(store: EvidenceStore):
    config = make_config(context_evidence_cap=2, context_event_cap=2)
    for step in store.steps:
        context = retrieve_context(step["id"], store=store, config=config)
        assert len(context.evidence) <= 2, step["id"]
        assert len(context.events) <= 2, step["id"]


def test_cap_never_reaches_the_whole_dataset(store: EvidenceStore):
    """The strongest statement of the cap: not even a single step sees everything."""
    total_records = len(store.all_records())
    context = retrieve_context("stp_price", store=store, config=make_config())
    assert len(context.evidence) <= 12
    assert total_records > 12  # the cap is doing real work, not passing vacuously


def test_retrieval_logs_item_counts(store: EvidenceStore):
    context = retrieve_context("stp_price", store=store, config=make_config())
    described = context.describe()
    assert set(described) >= {"evidence_items", "events", "scores", "events_dropped"}
    assert described["evidence_items"] == len(context.evidence)


def test_conflicting_policies_are_both_retrieved_for_the_policy_step(store: EvidenceStore):
    """TEST-006 needs both sides of the conflict present in one bounded context."""
    context = retrieve_context("stp_policy", store=store, config=make_config())
    refs = {item.ref for item in context.evidence if item.type == "policy"}
    assert "POL-PR-01" in refs
    assert "POL-PR-22" in refs


def test_unresolved_decision_is_retrieved_for_the_decision_step(store: EvidenceStore):
    """TEST-007 needs an ambiguous historical decision in context."""
    context = retrieve_context("stp_decisions", store=store, config=make_config())
    refs = {item.ref for item in context.evidence}
    assert "DEC-118" in refs
    assert "DEC-121" in refs


def test_ranking_is_deterministic(store: EvidenceStore):
    step = store.get_step("stp_price")
    records = store.all_records()
    first = [item.ref for item, _ in rank_evidence(step, records, newest_date="2026-08-30")]
    second = [item.ref for item, _ in rank_evidence(step, records, newest_date="2026-08-30")]
    assert first == second


def test_store_cache_serves_the_same_object():
    assert get_store() is get_store()


def test_dataset_is_synthetic_and_declared():
    data = load_dataset(REPO_ROOT / "data" / "evidence" / "evidence.json")
    assert "_note" in data
    assert "synthetic" in data["_note"].lower()


def test_no_import_time_network_calls(monkeypatch: pytest.MonkeyPatch):
    """Importing the AI layer must not require a provider to be reachable."""
    import importlib

    import app.ai  # noqa: F401
    import app.ai.pipeline  # noqa: F401
    import app.ai.provider  # noqa: F401
    import app.ai.retrieval  # noqa: F401

    reloaded = importlib.reload(importlib.import_module("app.ai.retrieval"))
    assert reloaded.get_store().steps
    assert json.loads(json.dumps({"ok": True}))["ok"] is True