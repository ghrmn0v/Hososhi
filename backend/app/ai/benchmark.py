"""Eval-set benchmark runner.

Same fixed cases for every configured provider. Records only measured values:
schema validity, field-level correctness, latency p50/p95, failure rate and
consistency (each case run twice).

    python -m app.ai.benchmark                 # every provider in the eval set
    python -m app.ai.benchmark --provider groq # one provider
    python -m app.ai.benchmark --repeat 1      # skip the consistency pass

Writes data/benchmark/results.json. No number in that file is authored by hand.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .config import AIConfig, ProviderConfig, get_config, reset_config_cache
from .errors import AIError
from .pipeline import AIService, Invocation, call_provider
from .prompts import build_prompt
from .provider import BaseProvider, build_provider
from .retrieval import EvidenceStore, get_store, known_evidence_refs
from .safety import classify_safety
from .schemas import (
    AutomationClassification,
    ExtractionResult,
    Role,
    StepExplanation,
    StepUnderstanding,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_SET_RELPATH = Path("data") / "benchmark" / "eval_set.json"
RESULTS_RELPATH = Path("data") / "benchmark" / "results.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_eval_set(path: Path | None = None) -> dict[str, Any]:
    resolved = path or (REPO_ROOT / EVAL_SET_RELPATH)
    with resolved.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@dataclass
class CaseOutcome:
    case_id: str
    role: str
    step_id: str
    run_index: int
    ok: bool
    schema_valid: bool
    correctness: float | None = None
    latency_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None
    repair_used: bool = False
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderReport:
    provider: str
    model: str
    configured: bool
    cases_run: int = 0
    schema_valid: int = 0
    correctness_scores: list[float] = field(default_factory=list)
    latencies_ms: list[int] = field(default_factory=list)
    failures: int = 0
    error_codes: dict[str, int] = field(default_factory=dict)
    repeat_mismatches: int = 0
    repeats_compared: int = 0
    outcomes: list[CaseOutcome] = field(default_factory=list)

    def record(self, outcome: CaseOutcome) -> None:
        self.outcomes.append(outcome)
        self.cases_run += 1
        if outcome.schema_valid:
            self.schema_valid += 1
            self.latencies_ms.append(outcome.latency_ms)
        else:
            self.failures += 1
            code = outcome.error_code or "UNKNOWN"
            self.error_codes[code] = self.error_codes.get(code, 0) + 1
        if outcome.correctness is not None:
            self.correctness_scores.append(outcome.correctness)

    def summarise(self) -> dict[str, Any]:
        latencies = sorted(self.latencies_ms)
        return {
            "provider": self.provider,
            "model": self.model,
            "configured": self.configured,
            "cases_run": self.cases_run,
            "schema_validity_pct": _pct(self.schema_valid, self.cases_run),
            "correctness_pct": _pct(1.0, 1.0) if not self.correctness_scores else round(
                statistics.fmean(self.correctness_scores) * 100, 2
            ),
            "failure_rate_pct": _pct(self.failures, self.cases_run),
            "latency_p50_ms": _percentile(latencies, 50),
            "latency_p95_ms": _percentile(latencies, 95),
            "latency_min_ms": min(latencies) if latencies else None,
            "latency_max_ms": max(latencies) if latencies else None,
            "consistency_pct": _pct(
                self.repeats_compared - self.repeat_mismatches, self.repeats_compared
            ),
            "repeat_runs_compared": self.repeats_compared,
            "repeat_mismatches": self.repeat_mismatches,
            "error_codes": dict(sorted(self.error_codes.items())),
        }


def _pct(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return round(numerator / denominator * 100, 2)


def _percentile(values: Sequence[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return int(round(ordered[lower] * (1 - weight) + ordered[upper] * weight))


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #


def _values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, float) or isinstance(actual, float):
        try:
            return abs(float(actual) - float(expected)) <= 0.01
        except (TypeError, ValueError):
            return False
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.strip().lower() == expected.strip().lower()
    return actual == expected


def score_case(case: dict[str, Any], result: Any, *, allowed_refs: set[str]) -> tuple[float, dict[str, Any]]:
    """Field-level correctness in [0, 1], plus a detail dict for the report."""
    expected = case.get("expected") or {}
    detail: dict[str, Any] = {"checked": [], "missed": []}

    if isinstance(result, ExtractionResult):
        for field_name in case.get("checked_fields", []):
            if field_name in expected:
                matched = _values_equal(getattr(result, field_name, None), expected[field_name])
                detail["checked"].append(field_name)
                if not matched:
                    detail["missed"].append(
                        {"field": field_name, "expected": expected[field_name], "actual": getattr(result, field_name, None)}
                    )
    elif isinstance(result, StepUnderstanding):
        if expected.get("step_id") is not None:
            matched = result.step_id == expected["step_id"]
            detail["checked"].append("step_id")
            if not matched:
                detail["missed"].append({"field": "step_id", "expected": expected["step_id"], "actual": result.step_id})
        for phrase in expected.get("must_mention_any", []):
            if phrase in result.purpose.lower() or phrase in result.step_name.lower():
                detail.setdefault("phrases_hit", []).append(phrase)
        detail["phrases_required"] = expected.get("must_mention_any", [])
        detail["phrases_hit"] = sorted(set(detail.get("phrases_hit", [])))
    elif isinstance(result, StepExplanation):
        required = set(expected.get("required_refs") or [])
        forbidden = set(expected.get("forbidden_refs") or [])
        cited = set(result.evidence_refs)
        detail["cited_refs"] = sorted(cited)
        detail["unknown_refs"] = sorted(cited - allowed_refs)
        if required:
            detail["checked"].append("evidence_refs")
            if not (required & cited):
                detail["missed"].append({"field": "evidence_refs", "expected": sorted(required), "actual": sorted(cited)})
        if forbidden and (forbidden & cited):
            detail["missed"].append({"field": "forbidden_refs", "hit": sorted(forbidden & cited)})
        low = expected.get("min_confidence")
        high = expected.get("max_confidence")
        if low is not None or high is not None:
            detail["checked"].append("confidence")
            detail["confidence"] = result.confidence
            if low is not None and result.confidence < low:
                detail["missed"].append({"field": "confidence", "expected_min": low, "actual": result.confidence})
            if high is not None and result.confidence > high:
                detail["missed"].append({"field": "confidence", "expected_max": high, "actual": result.confidence})
        text = f"{result.answer} {result.summary}".lower()
        detail["phrases_required"] = expected.get("must_mention_any", [])
        detail["phrases_hit"] = [p for p in expected.get("must_mention_any", []) if p in text]
    elif isinstance(result, AutomationClassification):
        allowed = expected.get("allowed_classes")
        forbidden = expected.get("forbidden_classes")
        detail["checked"].append("automation_class")
        detail["automation_class"] = result.automation_class.value
        safety_failure = False
        if forbidden and result.automation_class.value in forbidden:
            detail["missed"].append(
                {"field": "automation_class", "forbidden": forbidden, "actual": result.automation_class.value}
            )
            safety_failure = True
        elif allowed and result.automation_class.value not in allowed:
            detail["missed"].append(
                {"field": "automation_class", "allowed": allowed, "actual": result.automation_class.value}
            )
        if "requires_approval" in expected:
            detail["checked"].append("requires_approval")
            if result.requires_approval != expected["requires_approval"]:
                detail["missed"].append(
                    {"field": "requires_approval", "expected": expected["requires_approval"], "actual": result.requires_approval}
                )
        # A safety-critical miss is not a partial credit case: the model proposed
        # a class the case forbids, so the case is scored as failed outright.
        detail["safety_failure"] = safety_failure

    checked = len(detail.get("checked") or []) + len(expected.get("must_mention_any") or [])
    missed = len(detail.get("missed") or [])
    if expected.get("must_mention_any"):
        missed += max(0, len(expected["must_mention_any"]) - len(detail.get("phrases_hit") or []))
    if detail.get("safety_failure"):
        return 0.0, detail
    score = 1.0 if checked == 0 else max(0.0, (checked - missed) / checked)
    return round(score, 4), detail


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #


class BenchmarkRunner:
    def __init__(
        self,
        eval_set: dict[str, Any] | None = None,
        *,
        store: EvidenceStore | None = None,
        config: AIConfig | None = None,
    ) -> None:
        self.eval_set = eval_set or load_eval_set()
        self.store = store or get_store()
        self.config = config or get_config()
        self.allowed_refs = known_evidence_refs(self.store)
        self.service = AIService(store=self.store, config=self.config)

    def providers(self, names: Sequence[str] | None = None) -> list[ProviderConfig]:
        configured = [self.config.primary]
        if self.config.fallback:
            configured.append(self.config.fallback)
        if names:
            wanted = {name.lower() for name in names}
            configured = [provider for provider in configured if provider.name in wanted]
        return configured

    def run_provider(
        self,
        provider_config: ProviderConfig,
        *,
        repeat: int = 2,
        transport: Any = None,
    ) -> ProviderReport:
        report = ProviderReport(
            provider=provider_config.name,
            model=provider_config.model,
            configured=provider_config.is_configured,
        )
        if not provider_config.is_configured:
            report.cases_run = 0
            return report

        provider: BaseProvider = build_provider(provider_config, transport=transport)

        for case in self.eval_set["cases"]:
            runs = max(1, repeat)
            first_signature: str | None = None
            for run_index in range(runs):
                outcome = self._run_case(case, provider, run_index)
                report.record(outcome)
                if run_index == 0:
                    first_signature = outcome.detail.get("signature")
                elif outcome.detail.get("signature") is not None and first_signature is not None:
                    report.repeats_compared += 1
                    if outcome.detail["signature"] != first_signature:
                        report.repeat_mismatches += 1
        return report

    def _run_case(self, case: dict[str, Any], provider: BaseProvider, run_index: int) -> CaseOutcome:
        role = Role(case["role"])
        context = self.service.retrieve(case["step_id"], request_id=case.get("request_id"))
        prompt = build_prompt(role, context, question=case.get("prompt_context"))

        started = time.perf_counter()
        try:
            invocation: Invocation = call_provider(
                prompt, role, chain=[provider], config=self.config, repair_attempts=1
            )
        except AIError as exc:
            return CaseOutcome(
                case_id=case["id"],
                role=case["role"],
                step_id=case["step_id"],
                run_index=run_index,
                ok=False,
                schema_valid=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error_code=exc.code,
                error_message=exc.message,
            )
        except Exception as exc:  # unexpected - still recorded, never swallowed
            return CaseOutcome(
                case_id=case["id"],
                role=case["role"],
                step_id=case["step_id"],
                run_index=run_index,
                ok=False,
                schema_valid=False,
                error_code="UNEXPECTED_ERROR",
                error_message=f"{exc.__class__.__name__}: {exc}",
            )

        result = invocation.result.validated
        if result is None:  # pragma: no cover - call_provider raises before this
            return CaseOutcome(
                case_id=case["id"],
                role=case["role"],
                step_id=case["step_id"],
                run_index=run_index,
                ok=False,
                schema_valid=False,
                latency_ms=invocation.latency_ms,
                error_code="AI_OUTPUT_INVALID",
            )

        score, detail = score_case(case, result, allowed_refs=self.allowed_refs)

        if isinstance(result, AutomationClassification):
            # A model must not be able to talk the backend out of a hard stop.
            enforced = classify_safety(
                context.step,
                model_class=result.automation_class,
                model_reason=result.reason,
                model_confidence=result.confidence,
            )
            detail["safety_enforced_class"] = enforced.automation_class.value
            detail["safety_override"] = enforced.safety_override
            if enforced.automation_class.value in (case["expected"].get("forbidden_classes") or []):
                score = 0.0
                detail["missed"].append(
                    {
                        "field": "safety_override",
                        "note": "model proposed SAFE but the safety rubric forced a stricter class",
                    }
                )

        detail["signature"] = json.dumps(
            {
                "automation_class": getattr(result, "automation_class", None) and getattr(result.automation_class, "value", None),
                "evidence_refs": sorted(getattr(result, "evidence_refs", []) or []),
                "confidence": getattr(result, "confidence", None),
            },
            sort_keys=True,
        )

        return CaseOutcome(
            case_id=case["id"],
            role=case["role"],
            step_id=case["step_id"],
            run_index=run_index,
            ok=score >= 1.0,
            schema_valid=True,
            correctness=score,
            latency_ms=invocation.latency_ms,
            error_code=None if score >= 1.0 else "INCORRECT",
            repair_used=invocation.result.repair_used,
            detail=detail,
        )


def build_results(
    reports: list[ProviderReport],
    *,
    repeat: int,
    eval_set_version: str,
    config: AIConfig | None = None,
) -> dict[str, Any]:
    active = config or get_config()
    return {
        "generated_at": _now_iso(),
        "eval_set": {
            "path": str(EVAL_SET_RELPATH.as_posix()),
            "version": eval_set_version,
            "case_count": 10,
            "runs_per_case": repeat,
        },
        "environment": {
            "provider_config": active.describe(),
            "note": "Latency figures are from this machine and this moment only; they are not an SLA.",
        },
        "providers": [report.summarise() for report in reports],
        "per_case": {
            report.provider: [asdict(outcome) for outcome in report.outcomes] for report in reports
        },
    }


def unmeasured_results(*, active_config: AIConfig) -> dict[str, Any]:
    """Written when no provider is usable.

    Contains no performance or quality numbers at all, because none were
    measured. Only the configuration that was inspected.
    """
    return {
        "generated_at": _now_iso(),
        "status": "not_measured",
        "reason": (
            "No AI provider was configured, so no request was made. "
            "There are deliberately no latency, validity or correctness figures in this file."
        ),
        "eval_set": {
            "path": str(EVAL_SET_RELPATH.as_posix()),
            "version": "eval-v1",
            "case_count": 10,
            "runs_per_case": 0,
        },
        "environment": {"provider_config": active_config.describe()},
        "providers": [],
        "per_case": {},
    }


def render_table(results: dict[str, Any]) -> str:
    """Short readable table. Measured values only; 'n/a' where nothing was measured."""
    header = (
        "| provider/model | schema validity % | correctness % | p50 ms | p95 ms | failure % | consistency % |\n"
        "|---|---|---|---|---|---|---|"
    )
    rows: list[str] = []
    if not results.get("providers"):
        status = results.get("status", "no data")
        rows.append(f"| _no provider measured_ | {status} | n/a | n/a | n/a | n/a | n/a |")
    for entry in results["providers"]:
        label = f"{entry['provider']}/{entry['model'] or 'unset'}"
        if not entry["configured"] or not entry["cases_run"]:
            rows.append(f"| {label} | not configured | n/a | n/a | n/a | n/a | n/a |")
            continue
        rows.append(
            "| {label} | {sv} | {cr} | {p50} | {p95} | {fr} | {cs} |".format(
                label=label,
                sv=entry["schema_validity_pct"],
                cr=entry["correctness_pct"],
                p50=entry["latency_p50_ms"],
                p95=entry["latency_p95_ms"],
                fr=entry["failure_rate_pct"],
                cs=entry["consistency_pct"],
            )
        )
    return header + "\n" + "\n".join(rows)


def write_results(results: dict[str, Any], path: Path | None = None) -> Path:
    target = path or (REPO_ROOT / RESULTS_RELPATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2, sort_keys=False)
        handle.write("\n")
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hososhi AI provider benchmark")
    parser.add_argument("--provider", action="append", help="limit to one provider (repeatable)")
    parser.add_argument("--repeat", type=int, default=2, help="runs per case, for the consistency measure")
    parser.add_argument("--eval-set", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--no-write", action="store_true", help="print only, do not write results.json")
    args = parser.parse_args(argv)

    reset_config_cache()
    eval_set = load_eval_set(args.eval_set)
    runner = BenchmarkRunner(eval_set)
    providers = runner.providers(args.provider)

    if not providers:
        print("No AI provider is configured. Set AI_PROVIDER and AI_API_KEY (see .env.example).")
        print("Nothing was measured, so no benchmark table can be produced.")
        return 2

    if not any(provider.is_configured for provider in providers):
        print("No AI provider is configured. Set AI_PROVIDER and AI_API_KEY (see .env.example).")
        print("Nothing was measured, so no benchmark table can be produced.")
        if not args.no_write:
            target = write_results(unmeasured_results(active_config=get_config()), args.out)
            print(f"\nwritten (no measurements): {target}")
        return 2

    reports: list[ProviderReport] = []
    for provider_config in providers:
        report = runner.run_provider(provider_config, repeat=max(1, args.repeat))
        reports.append(report)
        summary = report.summarise()
        if not provider_config.is_configured:
            print(f"{provider_config.name}: not configured (no key), skipped")
            continue
        print(
            f"{provider_config.name}/{provider_config.model}: "
            f"schema_validity={summary['schema_validity_pct']}% "
            f"correctness={summary['correctness_pct']}% "
            f"p50={summary['latency_p50_ms']}ms p95={summary['latency_p95_ms']}ms "
            f"failure={summary['failure_rate_pct']}% consistency={summary['consistency_pct']}%"
        )

    results = build_results(
        reports,
        repeat=max(1, args.repeat),
        eval_set_version=eval_set.get("version", "unknown"),
    )
    print()
    print(render_table(results))

    if not args.no_write:
        target = write_results(results, args.out)
        print(f"\nwritten: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())