"""Benchmark harness. Everything here is offline; real numbers come from a run."""

from __future__ import annotations

import json

import httpx
import pytest

from app.ai.benchmark import (
    BenchmarkRunner,
    build_results,
    load_eval_set,
    render_table,
    score_case,
    write_results,
)
from app.ai.config import ProviderConfig
from app.ai.schemas import (
    AutomationClassification,
    ExtractionResult,
    Role,
    StepExplanation,
    StepUnderstanding,
)

from tests.ai.conftest import REPO_ROOT, make_config, openai_text_handler

CORRECT_EXTRACTION = ExtractionResult(request_id="pr_0001", supplier="AzLab Supplies", amount=18400.0, department="Operations")


def _correct_payload_for(role: Role, case: dict) -> dict:
    """A response that satisfies the case's expected values, per role."""
    expected = case["expected"]
    if role is Role.EXTRACT:
        return {key: expected.get(key) for key in ("request_id", "supplier", "amount", "department") if key in expected} | {
            "evidence_refs": [],
        }
    if role is Role.UNDERSTAND:
        payload = {"step_id": expected.get("step_id"), "step_name": expected.get("step_id", ""), "purpose": "", "actor_role": expected.get("actor_role", ""), "evidence_refs": []}
        for phrase in expected.get("must_mention_any", []):
            payload["purpose"] = f"{payload['purpose']} {phrase}".strip()
        return payload
    if role is Role.EXPLAIN:
        text = " ".join(expected.get("must_mention_any", []))
        return {
            "summary": f"cited {', '.join(expected.get('required_refs', []))}",
            "answer": f"This step exists because {text}.",
            "confidence": (expected.get("min_confidence", 0.5) + expected.get("max_confidence", 0.9)) / 2,
            "evidence_refs": expected.get("required_refs", []),
        }
    allowed = expected.get("allowed_classes") or ["HUMAN_REVIEW"]
    return {
        "automation_class": allowed[0],
        "reason": "per the rubric",
        "confidence": 0.8,
        "evidence_refs": [],
        "requires_approval": expected.get("requires_approval", False),
    }


# --------------------------------------------------------------------------- #
# eval set integrity
# --------------------------------------------------------------------------- #


def test_eval_set_exists_and_has_ten_cases():
    eval_set = load_eval_set()
    assert len(eval_set["cases"]) == 10
    assert {case["id"] for case in eval_set["cases"]} == {f"EV-{index:02d}" for index in range(1, 11)}


def test_eval_set_covers_all_four_roles():
    roles = {case["role"] for case in load_eval_set()["cases"]}
    assert roles == {"extract", "understand", "explain", "classify"}


def test_eval_set_step_ids_exist(store):
    ids = {step["id"] for step in store.steps}
    for case in load_eval_set()["cases"]:
        assert case["step_id"] in ids


def test_eval_set_required_refs_exist(store):
    allowed = {record["id"] for _, record in store.all_records()}
    for case in load_eval_set()["cases"]:
        for ref in case["expected"].get("required_refs", []):
            assert ref in allowed


def test_eval_set_forbids_safe_on_the_approval_step():
    case = next(case for case in load_eval_set()["cases"] if case["id"] == "EV-10")
    assert case["step_id"] == "stp_approval"
    assert "SAFE" in case["expected"]["forbidden_classes"]
    assert case["expected"]["requires_approval"] is True


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #


def test_score_case_rewards_a_correct_extraction():
    case = next(case for case in load_eval_set()["cases"] if case["id"] == "EV-01")
    score, detail = score_case(case, CORRECT_EXTRACTION, allowed_refs=set())
    assert score == 1.0
    assert detail["missed"] == []


def test_score_case_penalises_a_wrong_field():
    case = next(case for case in load_eval_set()["cases"] if case["id"] == "EV-01")
    wrong = ExtractionResult(request_id="pr_0001", supplier="Someone Else", amount=1.0, department="Operations")
    score, detail = score_case(case, wrong, allowed_refs=set())
    assert 0.0 < score < 1.0
    assert detail["missed"]


def test_score_case_flags_a_missing_required_reference():
    case = next(case for case in load_eval_set()["cases"] if case["id"] == "EV-05")
    result = StepExplanation(summary="s", answer="a", confidence=0.8, evidence_refs=["DEC-104"])
    score, detail = score_case(case, result, allowed_refs={"DEC-104"})
    assert score < 1.0
    assert detail["missed"]


def test_score_case_detects_an_unknown_reference():
    case = next(case for case in load_eval_set()["cases"] if case["id"] == "EV-05")
    result = StepExplanation(summary="s", answer="a", confidence=0.8, evidence_refs=["POL-PR-07", "POL-FAKE"])
    _score, detail = score_case(case, result, allowed_refs={"POL-PR-07"})
    assert detail["unknown_refs"] == ["POL-FAKE"]


def test_score_case_checks_confidence_band():
    case = next(case for case in load_eval_set()["cases"] if case["id"] == "EV-06")
    overconfident = StepExplanation(summary="s", answer="policy", confidence=0.99, evidence_refs=["POL-PR-01"])
    score, detail = score_case(case, overconfident, allowed_refs={"POL-PR-01"})
    assert detail["missed"]
    assert score < 1.0


def test_score_case_flags_a_forbidden_class():
    case = next(case for case in load_eval_set()["cases"] if case["id"] == "EV-09")
    result = AutomationClassification(automation_class="SAFE", reason="r", confidence=0.9, requires_approval=False)
    score, detail = score_case(case, result, allowed_refs=set())
    assert detail["missed"]
    assert score == 0.0


def test_score_case_checks_phrase_coverage():
    case = next(case for case in load_eval_set()["cases"] if case["id"] == "EV-05")
    good = StepExplanation(summary="price variance", answer="the catalogue price variance rule", confidence=0.8, evidence_refs=["POL-PR-07"])
    _score, detail = score_case(case, good, allowed_refs={"POL-PR-07"})
    assert detail["phrases_hit"]


# --------------------------------------------------------------------------- #
# runner, driven by a mocked transport
# --------------------------------------------------------------------------- #


def _transports_for(config):
    eval_set = load_eval_set()
    by_role: dict[str, list[dict]] = {}
    for case in eval_set["cases"]:
        by_role.setdefault(case["role"], []).append(case)

    # The prompt's first line names the component unambiguously.
    role_by_first_line = {
        "extraction component": "extract",
        "understanding component": "understand",
        "explanation component": "explain",
        "safety classifier": "classify",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content.decode())["messages"][-1]["content"]
        first_line = prompt.splitlines()[0]
        role = next(
            (value for marker, value in role_by_first_line.items() if marker in first_line),
            None,
        )
        cases = by_role.get(role or "", [])
        if not cases:
            return openai_text_handler('{"unexpected": true}')(request)
        case = cases.pop(0) if len(cases) > 1 else cases[0]
        return openai_text_handler(json.dumps(_correct_payload_for(Role(case["role"]), case)))(request)

    return httpx.MockTransport(handler)


def test_runner_produces_a_full_report(store):
    config = make_config()
    runner = BenchmarkRunner(store=store, config=config)
    report = runner.run_provider(config.primary, repeat=2, transport=_transports_for(config))
    summary = report.summarise()

    assert summary["cases_run"] == 20  # 10 cases x 2 runs
    assert summary["schema_validity_pct"] == 100.0
    assert summary["failure_rate_pct"] == 0.0
    assert summary["latency_p50_ms"] is not None
    assert summary["latency_p95_ms"] is not None
    assert summary["consistency_pct"] is not None


def test_runner_records_failures_rather_than_hiding_them(store):
    config = make_config()
    runner = BenchmarkRunner(store=store, config=config)
    report = runner.run_provider(config.primary, repeat=1, transport=httpx.MockTransport(lambda r: openai_text_handler("nope")(r)))
    summary = report.summarise()
    assert summary["schema_validity_pct"] == 0.0
    assert summary["failure_rate_pct"] == 100.0
    assert summary["error_codes"]["AI_OUTPUT_INVALID"] == 10


def test_unconfigured_provider_runs_nothing_and_says_so(store):
    config = make_config(primary=ProviderConfig(name="groq", model="m", api_key=None, base_url="https://api.groq.com/openai/v1"))
    runner = BenchmarkRunner(store=store, config=config)
    report = runner.run_provider(config.primary, repeat=1)
    assert report.summarise()["cases_run"] == 0
    assert report.summarise()["configured"] is False


def test_safety_override_drives_correctness_to_zero(store):
    """The rubric must be able to fail a case, not merely annotate it."""
    config = make_config()
    runner = BenchmarkRunner(store=store, config=config)

    def always_safe(request: httpx.Request) -> httpx.Response:
        return openai_text_handler(json.dumps({"automation_class": "SAFE", "reason": "r", "confidence": 0.99, "evidence_refs": [], "requires_approval": False}))(request)

    report = runner.run_provider(config.primary, repeat=1, transport=httpx.MockTransport(always_safe))
    approval_case = next(outcome for outcome in report.outcomes if outcome.case_id == "EV-10")
    assert approval_case.correctness == 0.0
    assert approval_case.detail["safety_override"] is True


def test_results_json_and_table_are_generated(store, tmp_path):
    config = make_config()
    runner = BenchmarkRunner(store=store, config=config)
    report = runner.run_provider(config.primary, repeat=1, transport=_transports_for(config))
    results = build_results([report], repeat=1, eval_set_version="eval-v1", config=config)

    target = write_results(results, tmp_path / "results.json")
    payload = json.loads(target.read_text())
    assert payload["eval_set"]["case_count"] == 10
    assert payload["providers"][0]["provider"] == "groq"
    assert payload["providers"][0]["model"] == "test-model"
    assert "note" in payload["environment"]
    assert len(payload["per_case"]["groq"]) == 10

    table = render_table(results)
    assert "| provider/model |" in table
    assert "groq/test-model" in table


def test_main_without_a_provider_reports_nothing_measured(monkeypatch, capsys):
    from app.ai.benchmark import main

    for key in ("AI_PROVIDER", "AI_API_KEY", "AI_MODEL", "AI_FALLBACK_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    exit_code = main(["--no-write"])
    captured = capsys.readouterr().out
    assert exit_code == 2
    assert "Nothing was measured" in captured


def test_unmeasured_results_carry_no_numbers(monkeypatch, tmp_path):
    from app.ai.benchmark import main, unmeasured_results

    for key in ("AI_PROVIDER", "AI_API_KEY", "AI_MODEL", "AI_FALLBACK_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    exit_code = main(["--out", str(tmp_path / "results.json")])
    assert exit_code == 2

    payload = json.loads((tmp_path / "results.json").read_text())
    assert payload["status"] == "not_measured"
    assert payload["providers"] == []
    # No measured figures: every metric key is absent, not zero.
    text = (tmp_path / "results.json").read_text()
    for metric in ("latency_p50_ms", "latency_p95_ms", "schema_validity_pct", "failure_rate_pct", "consistency_pct"):
        assert metric not in text


def test_table_marks_unmeasured_providers_as_not_configured(store):
    from app.ai.benchmark import unmeasured_results

    table = render_table(unmeasured_results(active_config=make_config()))
    assert "n/a" in table


def test_latency_numbers_are_not_an_sla(store):
    config = make_config()
    runner = BenchmarkRunner(store=store, config=config)
    report = runner.run_provider(config.primary, repeat=1, transport=_transports_for(config))
    results = build_results([report], repeat=1, eval_set_version="eval-v1", config=config)
    assert "not an SLA" in results["environment"]["note"]