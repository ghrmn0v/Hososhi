"""Metrics: baseline replay from the dataset, and live instrumentation of a run.

Every value returned by these functions came from a computation over real rows or
from real recorded timestamps. Anything not computed is None with source "none".
"""

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.discovery import ACTION_CATALOG
from app.models import MetricSnapshot, RunStep, WorkflowEvent, WorkflowRun
from app.schemas import MetricBlock, ResultsDelta, ResultsResponse

MEASUREMENT_METHOD = (
    "baseline = deterministic replay of synthetic event timestamps; "
    "ai_assisted = wall-clock timestamps recorded by the backend during this run, "
    "including any time the run spent waiting for a human decision"
)

# Why the two sides must not be differenced into a speedup claim.
#
# Both sides span "one purchase request, first event to last event", so the
# boundaries do match. What does not match is the work performed inside that
# interval:
#
#   baseline    synthetic replay of a human performing the steps, where seeded
#               handling gaps (including a 25-190 minute manager approval gap)
#               account for essentially all of the elapsed time.
#   ai_assisted real wall-clock time for the backend executing deterministic
#               in-process functions. These functions do no I/O and no model
#               inference, so they return in well under a millisecond.
#
# The delta therefore measures "human handling time vs. local function
# execution time". It is a true measurement of both intervals, but it is not a
# measurement of a product improvement, and no speedup or saving claim should be
# derived from it. Presenting 99.99% would be technically computed and
# substantively meaningless.
COMPARABILITY_NOTE = (
    "Boundaries match (one request, first event to last event) but the work "
    "inside them does not. baseline is a synthetic replay in which seeded human "
    "handling gaps dominate the elapsed time; ai_assisted is real wall-clock "
    "time for local deterministic functions that perform no I/O and no model "
    "inference. Treat delta as a description of the seeded scenario, not as a "
    "speedup. Do not publish a percentage improvement from these numbers."
)

SOURCE_BASELINE = "replayed_from_dataset"
SOURCE_LIVE = "measured_in_this_run"
SOURCE_NONE = "none"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo else value


def replay_baseline(db: Session, request_id: str) -> MetricBlock:
    """Replay one request's observed events and measure the human-only path."""
    events = list(
        db.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.request_id == request_id)
            .order_by(WorkflowEvent.timestamp, WorkflowEvent.id)
        ).all()
    )
    if not events:
        return MetricBlock(
            label="Human-only (synthetic replay)",
            source=SOURCE_NONE,
            total_duration_ms=None,
            manual_steps=None,
            human_decisions=None,
            automation_rate=None,
            errors=None,
        )

    stamps = [e.timestamp for e in events if e.timestamp]
    if len(stamps) < 2:
        return MetricBlock(label="Human-only (synthetic replay)", source=SOURCE_NONE)

    total_duration_ms = (max(stamps) - min(stamps)).total_seconds() * 1000

    # Manual steps = distinct workflow steps a human performed in the observed run.
    observed_steps = {ACTION_CATALOG[e.action][0] for e in events if e.action in ACTION_CATALOG}
    manual_steps = len(observed_steps)

    # Human decisions = approval events.
    human_decisions = sum(1 for e in events if e.action == "approve_request")

    # Errors = events flagged as retries or policy violations in metadata.
    errors = sum(
        1
        for e in events
        if (e.metadata_json or {}).get("retry") or (e.metadata_json or {}).get("violations")
    )

    automation_rate = 0.0 if manual_steps == 0 else round(
        (manual_steps - human_decisions) / manual_steps, 4
    )

    return MetricBlock(
        label="Human-only (synthetic replay)",
        source=SOURCE_BASELINE,
        total_duration_ms=round(total_duration_ms, 2),
        manual_steps=manual_steps,
        human_decisions=human_decisions,
        automation_rate=automation_rate,
        errors=errors,
        measurement_scope=(
            f"{events[0].timestamp.isoformat()} to {events[-1].timestamp.isoformat()}; "
            "synthetic event timestamps, elapsed time a human would spend"
        ),
    )


def measure_run(db: Session, run: WorkflowRun) -> MetricBlock:
    """Measure the AI-assisted run from timestamps the backend actually recorded."""
    run_steps = list(
        db.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.id)).all()
    )
    if not run_steps:
        return MetricBlock(label="Automated execution (measured)", source=SOURCE_NONE)

    started = [_as_naive(rs.started_at) for rs in run_steps if rs.started_at]
    finished = [_as_naive(rs.finished_at) for rs in run_steps if rs.finished_at]
    if not started or not finished:
        return MetricBlock(label="Automated execution (measured)", source=SOURCE_NONE)

    total_duration_ms = (max(finished) - min(started)).total_seconds() * 1000

    total_steps = len(run_steps)
    automated = sum(1 for rs in run_steps if rs.actor == "system")
    human_decisions = sum(1 for rs in run_steps if rs.actor and rs.actor != "system")
    errors = sum(1 for rs in run_steps if rs.state == "failed")

    automation_rate = 0.0 if total_steps == 0 else round(automated / total_steps, 4)

    work_ms = sum(rs.duration_ms or 0 for rs in run_steps)
    return MetricBlock(
        label="Automated execution (measured)",
        source=SOURCE_LIVE,
        total_duration_ms=round(total_duration_ms, 2),
        manual_steps=human_decisions,
        human_decisions=human_decisions,
        automation_rate=automation_rate,
        errors=errors,
        measurement_scope=(
            f"{min(started).isoformat()} to {max(finished).isoformat()}; "
            f"wall-clock including {round(total_duration_ms - work_ms, 2)} ms spent "
            "waiting on a human decision, "
            f"{work_ms} ms of local deterministic step execution, "
            "no model inference"
        ),
    )


def _delta(baseline: MetricBlock, assisted: MetricBlock) -> ResultsDelta:
    duration_ms = None
    duration_percent = None
    if baseline.total_duration_ms is not None and assisted.total_duration_ms is not None:
        duration_ms = round(baseline.total_duration_ms - assisted.total_duration_ms, 2)
        if baseline.total_duration_ms:
            duration_percent = round(duration_ms / baseline.total_duration_ms * 100, 2)

    human_interventions = None
    if baseline.human_decisions is not None and assisted.human_decisions is not None:
        human_interventions = baseline.human_decisions - assisted.human_decisions

    return ResultsDelta(
        duration_ms=duration_ms,
        duration_percent=duration_percent,
        human_interventions=human_interventions,
    )


def build_results(db: Session, run: WorkflowRun) -> ResultsResponse:
    baseline = replay_baseline(db, run.request_id)
    assisted = measure_run(db, run)

    runs_count = db.scalar(
        select(func.count()).select_from(WorkflowRun).where(WorkflowRun.workflow_id == run.workflow_id)
    ) or 0

    is_measured = (
        baseline.source != SOURCE_NONE
        and assisted.source != SOURCE_NONE
        and baseline.total_duration_ms is not None
        and assisted.total_duration_ms is not None
    )

    ai_calls = db.scalar(
        select(func.count())
        .select_from(MetricSnapshot)
        .where(MetricSnapshot.run_id == run.id, MetricSnapshot.phase == "ai_call")
    ) or 0

    return ResultsResponse(
        run_id=run.id,
        workflow_id=run.workflow_id,
        measured_at=utcnow(),
        measurement_method=MEASUREMENT_METHOD,
        runs_count=runs_count,
        baseline=baseline,
        ai_assisted=assisted,
        delta=_delta(baseline, assisted),
        is_measured=is_measured,
        is_comparable=False,
        comparability_note=COMPARABILITY_NOTE if is_measured else None,
        ai_call_count=ai_calls,
    )


def record_snapshot(
    db: Session, run_id: str, phase: str, metrics: dict[str, float | None], source: str
) -> None:
    now = utcnow()
    for key, value in metrics.items():
        db.add(
            MetricSnapshot(
                run_id=run_id,
                phase=phase,
                metric_key=key,
                metric_value=value,
                source=source if value is not None else SOURCE_NONE,
                measured_at=now,
            )
        )
    db.commit()