"""The four role prompts (v1).

Each prompt states the role, the single task, the exact output schema, and two
grounding rules: use only the provided context, and return
`insufficient_context: true` rather than guessing.
"""

from __future__ import annotations

import json
from typing import Any

from .retrieval import RetrievedContext
from .schemas import EvidenceItem, Role

GROUNDING_RULES = (
    "Use only the provided context. Do not use outside knowledge.\n"
    "If the provided context is insufficient, set insufficient_context to true and say so "
    "in the relevant text field. Do not guess.\n"
    "Reference evidence only by the exact ids given in the context. Never invent an id.\n"
    "Return a single JSON object and nothing else. No prose, no markdown fence."
)

SCHEMA_INSTRUCTIONS: dict[Role, str] = {
    Role.EXTRACT: (
        "Return JSON with exactly these fields:\n"
        '{"request_id": string|null, "supplier": string|null, "items": [string], '
        '"amount": number|null, "currency": string|null, "department": string|null, '
        '"requester": string|null, "insufficient_context": boolean, '
        '"evidence_refs": [string], "notes": string}'
    ),
    Role.UNDERSTAND: (
        "Return JSON with exactly these fields:\n"
        '{"step_id": string|null, "step_name": string, "purpose": string, "actor_role": string, '
        '"insufficient_context": boolean, "evidence_refs": [string]}'
    ),
    Role.EXPLAIN: (
        "Return JSON with exactly these fields:\n"
        '{"step_id": string|null, "question": string, "summary": string, "answer": string, '
        '"confidence": number between 0 and 1, "evidence_refs": [string], '
        '"assumptions": [string], "conflicts": [string], "insufficient_context": boolean}\n'
        "Write summary as one sentence. Write answer as 3-5 sentences that state what the step "
        "does and why it exists in this company's actual process. confidence must reflect how well "
        "the cited evidence supports the answer: lower it when evidence is thin, dated, or in "
        "conflict. When two evidence items disagree, name both ids in conflicts."
    ),
    Role.CLASSIFY: (
        "Return JSON with exactly these fields:\n"
        '{"step_id": string|null, "automation_class": "SAFE"|"HUMAN_REVIEW"|"HUMAN_REQUIRED", '
        '"reason": string, "confidence": number between 0 and 1, "evidence_refs": [string], '
        '"requires_approval": boolean, "insufficient_context": boolean}\n'
        "Classify how far this step can be automated:\n"
        "- SAFE: deterministic, verifiable, reversible. It can run automatically.\n"
        "- HUMAN_REVIEW: an AI proposal is acceptable but a person must confirm it.\n"
        "- HUMAN_REQUIRED: judgement, financial commitment, or irreversible. Hard stop. "
        "requires_approval must be true."
    ),
}


def render_context(evidence: list[EvidenceItem], events: list[dict[str, Any]], *, event_limit: int = 8) -> str:
    blocks: list[str] = []
    if evidence:
        rendered = [
            {"ref": item.ref, "type": item.type, "title": item.title, "snippet": item.snippet}
            for item in evidence
        ]
        blocks.append("EVIDENCE:\n" + json.dumps(rendered, ensure_ascii=False, indent=2))
    else:
        blocks.append("EVIDENCE:\n[] (no relevant evidence was retrieved)")

    trimmed_events = [
        {
            "id": event.get("id"),
            "action": event.get("action"),
            "timestamp": event.get("timestamp"),
            "entity": event.get("entity"),
            "metadata": event.get("metadata"),
        }
        for event in events[:event_limit]
    ]
    if trimmed_events:
        blocks.append("RECENT EVENTS:\n" + json.dumps(trimmed_events, ensure_ascii=False, indent=2))
    return "\n\n".join(blocks)


def _step_block(context: RetrievedContext) -> str:
    step = context.step
    return json.dumps(
        {
            "step_id": step.get("id"),
            "step_name": step.get("name"),
            "step_type": step.get("type"),
            "actor_role": step.get("actor_role"),
            "description": step.get("description"),
        },
        ensure_ascii=False,
        indent=2,
    )


def build_prompt(role: Role, context: RetrievedContext, *, question: str | None = None) -> str:
    step_block = _step_block(context)
    evidence_block = render_context(context.evidence, context.events)
    schema_block = SCHEMA_INSTRUCTIONS[role]

    if role is Role.EXTRACT:
        task = (
            "You are an extraction component. Extract the structured fields of the purchase "
            "request from the events below."
        )
        payload = f"REQUEST EVENTS:\n{json.dumps(context.events[:8], ensure_ascii=False, indent=2)}"
        if context.evidence:
            payload += f"\n\nSUPPORTING EVIDENCE:\n{evidence_block}"
    elif role is Role.UNDERSTAND:
        task = (
            "You are a workflow understanding component. From the events below, state what this "
            "step does, why it is in the workflow, and which role performs it."
        )
        payload = f"STEP:\n{step_block}\n\n{evidence_block}"
    elif role is Role.EXPLAIN:
        task = (
            "You are a workflow explanation component. Answer the question using the evidence "
            "below. The question is always: 'Why does this step exist?'"
        )
        payload = f"QUESTION: {question or 'Why does this step exist?'}\n\nSTEP:\n{step_block}\n\n{evidence_block}"
    else:
        task = (
            "You are an automation safety classifier. Decide how far this step can be automated "
            "given the evidence below. You advise only; you never instruct anyone to take an action."
        )
        payload = f"STEP:\n{step_block}\n\n{evidence_block}"

    return f"{task}\n\n{payload}\n\nOUTPUT SCHEMA:\n{schema_block}\n\nRULES:\n{GROUNDING_RULES}"