"""Relevant-context retrieval for the AI layer.

The whole company database is never sent to a provider. This module filters the
dataset down to the policies, decisions, incidents and events relevant to one
workflow step, scores each item with an explainable heuristic, and enforces a
hard cap on how many items reach a prompt.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

from .config import AIConfig, get_config
from .schemas import EvidenceItem, EvidenceType

_TOKEN_RE = re.compile(r"[a-z0-9_]+")

DEFAULT_DATASET_RELPATH = Path("data") / "evidence" / "evidence.json"

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Phrases that make a step "about" a topic, independent of the step's own title.
TOPIC_HINTS: dict[str, tuple[str, ...]] = {
    "price": ("price", "cost", "variance", "discount", "catalogue", "quote", "amount", "premium"),
    "policy": ("policy", "rule", "threshold", "compliance", "control", "allowance", "prohibit"),
    "supplier": ("supplier", "vendor", "preferred", "substitut", "catalogue item", "sourcing"),
    "approval": ("approval", "approver", "authoris", "authoriz", "sign off", "sign-off", "manager"),
    "decision": ("decision", "exception", "precedent", "historical", "past"),
    "order": ("purchase order", "po", "raise", "issue order"),
}


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _stem(word: str) -> str:
    for suffix in ("ing", "ers", "er", "es", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _stems(tokens: Iterable[str]) -> set[str]:
    return {_stem(t) for t in tokens}


def _topic_tokens(step: dict[str, Any]) -> set[str]:
    haystack = " ".join(
        [
            str(step.get("name") or ""),
            str(step.get("description") or ""),
            " ".join(step.get("keywords") or []),
        ]
    )
    tokens = _stems(_tokenize(haystack))
    extra: set[str] = set()
    for keywords in TOPIC_HINTS.values():
        for keyword in keywords:
            extra |= _stems(_tokenize(keyword))
    return tokens | extra


def _dates(value: Any) -> set[str]:
    """Extract id-like tokens (POL-*, DEC-*, INC-*) from a record."""
    tokens: set[str] = set()
    for key in ("linked_policy_id", "linked_decision_id", "evidence", "participants", "policy_ref"):
        raw = value.get(key) if isinstance(value, dict) else None
        if isinstance(raw, str):
            tokens.add(raw)
        elif isinstance(raw, list):
            tokens |= {str(item) for item in raw}
    return tokens


@dataclass(frozen=True)
class RetrievedContext:
    step: dict[str, Any]
    evidence: list[EvidenceItem]
    events: list[dict[str, Any]]
    counts: dict[str, int] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def evidence_refs(self) -> list[str]:
        return [item.ref for item in self.evidence]

    def describe(self) -> dict[str, Any]:
        return {
            "evidence_items": len(self.evidence),
            "events": len(self.events),
            "evidence_cap_reached": self.counts.get("evidence_dropped", 0) > 0,
            "events_dropped": self.counts.get("events_dropped", 0),
            "scores": self.scores,
        }


def _default_dataset_path() -> Path:
    candidate = _REPO_ROOT / DEFAULT_DATASET_RELPATH
    if candidate.exists():
        return candidate
    return Path.cwd() / DEFAULT_DATASET_RELPATH


def load_dataset(path: Path | None = None) -> dict[str, Any]:
    resolved = path or _default_dataset_path()
    with resolved.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=4)
def _load_cached(path_str: str, mtime: float) -> str:  # noqa: ARG001 - mtime is the cache key
    return json.dumps(load_dataset(Path(path_str)), sort_keys=True)


def load_dataset_cached(path: Path | None = None) -> dict[str, Any]:
    resolved = path or _default_dataset_path()
    stat = resolved.stat()
    return json.loads(_load_cached(str(resolved), stat.st_mtime))


class EvidenceStore:
    """In-memory view over the synthetic dataset, with a simple filter API.

    Developer 1 owns the real database. This store exists so the AI layer is
    runnable and testable on its own; `retrieve_context` takes plain records, so
    swapping this for a SQL query later does not change the AI layer.
    """

    def __init__(self, dataset: dict[str, Any]) -> None:
        self.dataset = dataset
        self.policies: list[dict[str, Any]] = list(dataset.get("policies") or [])
        self.decisions: list[dict[str, Any]] = list(dataset.get("decisions") or [])
        self.incidents: list[dict[str, Any]] = list(dataset.get("incidents") or [])
        self.events: list[dict[str, Any]] = list(dataset.get("events") or [])
        self.steps: list[dict[str, Any]] = list(dataset.get("steps") or [])
        self.workflow: dict[str, Any] = dict(dataset.get("workflow") or {})

    def get_step(self, step_id: str) -> dict[str, Any] | None:
        for step in self.steps:
            if step.get("id") == step_id:
                return step
        return None

    def all_records(self) -> list[tuple[EvidenceType, dict[str, Any]]]:
        records: list[tuple[EvidenceType, dict[str, Any]]] = []
        records += [("policy", item) for item in self.policies]
        records += [("decision", item) for item in self.decisions]
        records += [("incident", item) for item in self.incidents]
        return records

    def steps_for_event_actions(self) -> dict[str, str]:
        """action verb -> step id, so an event can be attributed to a step."""
        mapping: dict[str, str] = {}
        for step in self.steps:
            for keyword in step.get("keywords") or []:
                key = str(keyword).lower().replace(" ", "_")
                mapping.setdefault(key, step["id"])
        return mapping


@lru_cache(maxsize=1)
def get_store() -> EvidenceStore:
    return EvidenceStore(load_dataset_cached())


def reset_store_cache() -> None:
    get_store.cache_clear()


def _recency(date_value: str | None, newest: str | None) -> float:
    if not date_value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(str(date_value).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if newest:
        try:
            newest_dt = datetime.fromisoformat(str(newest).replace("Z", "+00:00"))
        except ValueError:
            newest_dt = parsed
        age_days = (newest_dt - parsed).days
    else:
        age_days = 0
    # 1.0 for today, decaying to 0.35 at ~2 years.
    return max(0.35, 1.0 - min(age_days, 730) / 1095.0)


def score_record(
    evidence_type: EvidenceType,
    record: dict[str, Any],
    step: dict[str, Any],
    *,
    newest_date: str | None,
    step_linked_refs: set[str],
) -> float:
    """Explainable relevance score in [0, 1].

    Components: topic token overlap, explicit id linkage to the step, department
    match, keyword hit in the step's keyword list, and recency decay.
    """
    if evidence_type == "policy":
        text = f"{record.get('title', '')} {record.get('rule', '')}"
    elif evidence_type == "decision":
        text = f"{record.get('title', '')} {record.get('reason', '')} {record.get('outcome', '')}"
    else:
        text = f"{record.get('title', '')} {record.get('impact', '')}"

    record_tokens = _stems(_tokenize(text))
    topic = _topic_tokens(step)
    overlap = topic & record_tokens
    token_score = len(overlap) / max(1, min(len(topic), 24))

    linked = 1.0 if (record.get("id") in step_linked_refs) else 0.0

    department = step.get("department")
    dept_score = 0.0
    if department and record.get("department"):
        dept_score = 1.0 if str(record["department"]).lower() == str(department).lower() else 0.0

    keywords = _stems(_tokenize(" ".join(step.get("keywords") or [])))
    keyword_score = 1.0 if keywords & record_tokens else 0.0

    recency = _recency(record.get("date") or record.get("effective_date"), newest_date)

    score = (
        0.45 * min(1.0, token_score * 2.0)
        + 0.25 * linked
        + 0.10 * dept_score
        + 0.10 * keyword_score
        + 0.10 * recency
    )
    return round(min(1.0, max(0.0, score)), 4)


def _snippet(record: dict[str, Any], evidence_type: EvidenceType, limit: int = 220) -> str:
    if evidence_type == "policy":
        text = str(record.get("rule") or "")
    elif evidence_type == "decision":
        text = str(record.get("reason") or "")
    else:
        text = str(record.get("impact") or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _step_linked_refs(store: EvidenceStore, step: dict[str, Any]) -> set[str]:
    """Ids that the step's own event history points at, plus the step's entity ids."""
    refs: set[str] = set()
    step_id = step.get("id")
    step_name = str(step.get("name") or "").lower()
    for event in store.events:
        action = str(event.get("action") or "").lower()
        if step_id and step_id.replace("stp_", "") in action:
            refs.add(str(event.get("entity_id")))
            metadata = event.get("metadata") or {}
            if metadata.get("policy_ref"):
                refs.add(str(metadata["policy_ref"]))
    refs |= {str(step_name)}  # harmless: never matches a POL-/DEC-/INC- id
    refs.discard(step_name)
    return {ref for ref in refs if ref.startswith(("POL-", "DEC-", "INC-", "po_", "apr_"))}


def _newest_date(store: EvidenceStore) -> str | None:
    dates: list[str] = []
    for record in store.policies:
        if record.get("effective_date"):
            dates.append(str(record["effective_date"]))
    for record in store.decisions + store.incidents:
        if record.get("date"):
            dates.append(str(record["date"]))
    return max(dates) if dates else None


def rank_evidence(
    step: dict[str, Any],
    records: Sequence[tuple[EvidenceType, dict[str, Any]]],
    *,
    newest_date: str | None = None,
    step_linked_refs: set[str] | None = None,
) -> list[tuple[EvidenceItem, float]]:
    linked = step_linked_refs if step_linked_refs is not None else set()
    scored: list[tuple[EvidenceItem, float]] = []
    for evidence_type, record in records:
        score = score_record(
            evidence_type,
            record,
            step,
            newest_date=newest_date,
            step_linked_refs=linked,
        )
        item = EvidenceItem(
            ref=str(record.get("id")),
            type=evidence_type,
            title=str(record.get("title") or ""),
            snippet=_snippet(record, evidence_type),
            relevance=score,
            date=str(record.get("date") or record.get("effective_date") or "") or None,
        )
        scored.append((item, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0].ref))
    return scored


def filter_events(
    store: EvidenceStore,
    step: dict[str, Any],
    *,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    """Events for one step: same request first, then the step's action family."""
    step_token = str(step.get("id") or "").replace("stp_", "")
    keywords = [k.lower() for k in step.get("keywords") or []]

    def matches(event: dict[str, Any]) -> bool:
        action = str(event.get("action") or "").lower()
        entity_id = str(event.get("entity_id") or "").lower()
        if step_token and (step_token in action or step_token in entity_id):
            return True
        return any(keyword in action for keyword in keywords)

    events = [event for event in store.events if matches(event)]
    if request_id:
        same_request = [event for event in events if event.get("request_id") == request_id]
        if same_request:
            return sorted(same_request, key=lambda event: str(event.get("timestamp")))
    return sorted(events, key=lambda event: str(event.get("timestamp")))


def retrieve_context(
    step_id: str,
    *,
    store: EvidenceStore | None = None,
    config: AIConfig | None = None,
    evidence_type: str | None = None,
    request_id: str | None = None,
) -> RetrievedContext:
    """Bounded, relevant context for one step. This is the only input to a prompt."""
    active_store = store or get_store()
    active_config = config or get_config()

    step = active_store.get_step(step_id)
    if step is None:
        raise KeyError(f"unknown step id: {step_id}")

    records = active_store.all_records()
    if evidence_type:
        records = [pair for pair in records if pair[0] == evidence_type]

    linked = _step_linked_refs(active_store, step)
    ranked = rank_evidence(step, records, newest_date=_newest_date(active_store), step_linked_refs=linked)

    evidence_cap = max(0, active_config.context_evidence_cap)
    event_cap = max(0, active_config.context_event_cap)

    kept = [item for item, _ in ranked[:evidence_cap]]
    events = filter_events(active_store, step, request_id=request_id)[:event_cap]
    dropped_evidence = max(0, len(ranked) - evidence_cap)

    return RetrievedContext(
        step=step,
        evidence=kept,
        events=events,
        counts={
            "evidence_considered": len(ranked),
            "evidence_returned": len(kept),
            "evidence_dropped": dropped_evidence,
            "events_returned": len(events),
            "events_dropped": max(0, len(events) - event_cap),
        },
        scores={item.ref: item.relevance for item in kept},
    )


def known_evidence_refs(store: EvidenceStore | None = None) -> set[str]:
    """Every ref that is allowed to be cited by a model response."""
    active_store = store or get_store()
    refs = {str(record["id"]) for _, record in active_store.all_records()}
    refs |= {str(event["id"]) for event in active_store.events}
    refs |= {str(step["id"]) for step in active_store.steps}
    return refs