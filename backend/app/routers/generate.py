"""Game DSL generation endpoints (SSE + polling fallback)."""

from __future__ import annotations

import asyncio
import logging
import json
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.pipeline.orchestrator import PipelineArtifacts, generate_game_dsl

router = APIRouter(prefix="/generate", tags=["generate"])
logger = logging.getLogger(__name__)

STAGE_SEQUENCE = ["research", "plan", "dsl", "validation"]
STAGE_LABELS = {
    "research": "Stage 1 - Research",
    "plan": "Stage 2a - Game Plan",
    "dsl": "Stage 2b - DSL Generation",
    "validation": "Stage 3 - Validation",
}


class GenerateRequest(BaseModel):
    """All-in-one request running Stages 1-3 in one call."""

    game_name: str = Field(
        ...,
        description="Name of the card game, e.g. Exploding Kittens.",
    )
    player_count: int | None = Field(
        None,
        ge=1,
        description="Optional player count used for dynamic deck/card sizing.",
    )
    research_override: str | None = Field(
        None,
        description=(
            "If provided, skips Stage 1 research and uses this text as the "
            "rules document."
        ),
    )


class StageStatus(str, Enum):
    started = "started"
    done = "done"
    retry = "retry"
    error = "error"


class StageEvent(BaseModel):
    """SSE stage progress payload."""

    stage: str
    status: StageStatus
    stage_index: int | None = None
    stage_total: int | None = None
    stage_label: str | None = None
    progress_pct: int | None = None
    message: str | None = None
    attempt: int | None = None
    detail: str | None = None
    elapsed_ms: int | None = None
    timestamp: str | None = None


class GenerateResult(BaseModel):
    """Final generated DSL payload."""

    game_name: str
    dsl: dict[str, Any]
    research_output: str | None = None
    stages_elapsed_ms: dict[str, int]


class AsyncJobResult(BaseModel):
    """Response for the asynchronous polling endpoint."""

    job_id: str


_jobs: dict[str, dict[str, Any]] = {}


def sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Encode one SSE event."""

    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _default_stage_message(stage: str, status: str, attempt: int | None = None) -> str:
    if status == StageStatus.started.value:
        return {
            "research": "Researching and structuring game rules",
            "plan": "Designing the game architecture plan",
            "dsl": "Generating DSL JSON from the plan",
            "validation": "Validating generated DSL against schema",
        }.get(stage, "Processing stage")
    if status == StageStatus.done.value:
        return {
            "research": "Research stage completed",
            "plan": "Planning stage completed",
            "dsl": "DSL generation completed",
            "validation": "Validation passed",
        }.get(stage, "Stage completed")
    if status == StageStatus.retry.value:
        suffix = f" (attempt {attempt})" if attempt is not None else ""
        return f"Validation failed; retrying generation{suffix}"
    if status == StageStatus.error.value:
        return "Stage failed"
    return "Stage update"


def _progress_for(stage: str, status: str) -> tuple[int | None, int | None, int | None]:
    stage_total = len(STAGE_SEQUENCE)
    if stage not in STAGE_SEQUENCE:
        return None, stage_total, None
    stage_index = STAGE_SEQUENCE.index(stage) + 1
    if status == StageStatus.done.value:
        progress = int((stage_index / stage_total) * 100)
    else:
        progress = int(((stage_index - 1) / stage_total) * 100)
    return stage_index, stage_total, progress


def _build_stage_event_payload(
    *,
    stage: str,
    status: str,
    attempt: int | None = None,
    detail: str | None = None,
    elapsed_ms: int | None = None,
) -> dict[str, Any]:
    stage_index, stage_total, progress_pct = _progress_for(stage, status)
    stage_label = STAGE_LABELS.get(stage, stage.replace("_", " ").title())
    message = detail or _default_stage_message(stage, status, attempt=attempt)
    return StageEvent(
        stage=stage,
        status=StageStatus(status),
        stage_index=stage_index,
        stage_total=stage_total,
        stage_label=stage_label,
        progress_pct=progress_pct,
        message=message,
        attempt=attempt,
        detail=detail,
        elapsed_ms=elapsed_ms,
        timestamp=_utc_now_iso(),
    ).model_dump(exclude_none=True)


async def _run_pipeline_job(job_id: str, request: GenerateRequest) -> None:
    """Background worker for polling-based generation."""

    stage_starts: dict[str, float] = {}
    timings: dict[str, int] = {}

    async def on_stage(
        stage: str,
        status: str,
        attempt: int | None = None,
        detail: str | None = None,
    ) -> None:
        now = time.monotonic()
        elapsed_ms: int | None = None
        if status == StageStatus.started.value:
            stage_starts[stage] = now
        elif status == StageStatus.done.value:
            started = stage_starts.get(stage)
            elapsed_ms = 0 if started is None else int((now - started) * 1000)
            timings[stage] = elapsed_ms

        payload = _build_stage_event_payload(
            stage=stage,
            status=status,
            attempt=attempt,
            detail=detail,
            elapsed_ms=elapsed_ms,
        )
        logger.info("async_job=%s stage_update=%s", job_id, payload)

        _jobs[job_id]["stage"] = stage
        _jobs[job_id]["status"] = status
        if attempt is not None:
            _jobs[job_id]["attempt"] = attempt
        _jobs[job_id]["detail"] = detail
        _jobs[job_id]["message"] = payload.get("message")
        _jobs[job_id]["progress_pct"] = payload.get("progress_pct")
        _jobs[job_id]["updated_at"] = payload.get("timestamp")
        _jobs[job_id]["stages_elapsed_ms"] = timings
        _jobs[job_id]["history"].append(payload)

    try:
        artifacts = await generate_game_dsl(
            game_name=request.game_name,
            player_count=request.player_count,
            research=request.research_override,
            max_retries=settings.PIPELINE_MAX_RETRIES,
            on_stage=on_stage,
        )
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "done",
            "stage": "complete",
            "message": "Pipeline completed successfully",
            "progress_pct": 100,
            "updated_at": _utc_now_iso(),
            "result": GenerateResult(
                game_name=request.game_name,
                dsl=artifacts.schema.model_dump(by_alias=True),
                research_output=artifacts.research_output,
                stages_elapsed_ms=timings,
            ).model_dump(),
            "history": _jobs[job_id]["history"],
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("async_job=%s failed", job_id)
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "error",
            "stage": _jobs.get(job_id, {}).get("stage", "unknown"),
            "error": str(exc),
            "message": "Pipeline failed",
            "updated_at": _utc_now_iso(),
            "history": _jobs.get(job_id, {}).get("history", []),
        }


@router.post("")
async def generate_game(request: GenerateRequest):
    """Generate a game DSL with SSE-streamed progress events."""

    async def event_stream():
        stage_starts: dict[str, float] = {}
        timings: dict[str, int] = {}
        event_queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        current_stage = "research"
        current_stage_started = time.monotonic()
        last_heartbeat_at = time.monotonic()

        async def on_stage(
            stage: str,
            status: str,
            attempt: int | None = None,
            detail: str | None = None,
        ) -> None:
            nonlocal current_stage, current_stage_started
            now = time.monotonic()
            elapsed_ms: int | None = None

            if status == StageStatus.started.value:
                current_stage = stage
                current_stage_started = now
                stage_starts[stage] = now
            elif status == StageStatus.done.value:
                started = stage_starts.get(stage)
                elapsed = 0 if started is None else int((now - started) * 1000)
                elapsed_ms = elapsed
                timings[stage] = elapsed

            payload = _build_stage_event_payload(
                stage=stage,
                status=status,
                attempt=attempt,
                detail=detail,
                elapsed_ms=elapsed_ms,
            )
            logger.info("sse stage_update=%s", payload)
            await event_queue.put(("stage", payload))

        pipeline_task = asyncio.create_task(
            generate_game_dsl(
                game_name=request.game_name,
                player_count=request.player_count,
                research=request.research_override,
                max_retries=settings.PIPELINE_MAX_RETRIES,
                on_stage=on_stage,
            )
        )

        while not (pipeline_task.done() and event_queue.empty()):
            try:
                event_type, payload = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                yield sse_event(event_type, payload)
            except asyncio.TimeoutError:
                if pipeline_task.done():
                    continue
                now = time.monotonic()
                if now - last_heartbeat_at < 5.0:
                    continue
                heartbeat = {
                    "stage": current_stage,
                    "stage_label": STAGE_LABELS.get(
                        current_stage, current_stage.replace("_", " ").title()
                    ),
                    "message": f"Still working on {current_stage}",
                    "elapsed_ms": int((now - current_stage_started) * 1000),
                    "timestamp": _utc_now_iso(),
                }
                logger.info("sse heartbeat=%s", heartbeat)
                yield sse_event("heartbeat", heartbeat)
                last_heartbeat_at = now
                continue

        try:
            artifacts: PipelineArtifacts = pipeline_task.result()
        except Exception as exc:  # noqa: BLE001
            logger.exception("sse pipeline failed")
            error_stage_payload = _build_stage_event_payload(
                stage=current_stage,
                status=StageStatus.error.value,
                detail=str(exc),
            )
            yield sse_event("stage", error_stage_payload)
            yield sse_event("error", {"message": str(exc)})
            return

        yield sse_event("research_output", {"rules": artifacts.research_output})
        yield sse_event(
            "stage",
            {
                "stage": "complete",
                "status": StageStatus.done.value,
                "progress_pct": 100,
                "message": "Pipeline completed successfully",
                "timestamp": _utc_now_iso(),
            },
        )
        yield sse_event(
            "result",
            GenerateResult(
                game_name=request.game_name,
                dsl=artifacts.schema.model_dump(by_alias=True),
                research_output=artifacts.research_output,
                stages_elapsed_ms=timings,
            ).model_dump(),
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/async", response_model=AsyncJobResult)
async def generate_game_async(request: GenerateRequest, background_tasks: BackgroundTasks):
    """Start generation as a background task and return job_id."""

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "status": "running",
        "stage": "research",
        "message": "Queued for Stage 1 - Research",
        "progress_pct": 0,
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "history": [],
        "result": None,
    }
    logger.info("async_job=%s created for game=%s", job_id, request.game_name)
    background_tasks.add_task(_run_pipeline_job, job_id, request)
    return AsyncJobResult(job_id=job_id)


@router.get("/{job_id}")
async def get_job_status(job_id: str):
    """Polling status endpoint for async jobs."""

    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
