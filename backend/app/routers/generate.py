"""Game DSL generation endpoints (SSE + polling fallback)."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from enum import Enum
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.pipeline.orchestrator import PipelineArtifacts, generate_game_dsl

router = APIRouter(prefix="/generate", tags=["generate"])


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
    attempt: int | None = None
    detail: str | None = None
    elapsed_ms: int | None = None


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
        if status == StageStatus.started.value:
            stage_starts[stage] = now
        elif status == StageStatus.done.value:
            started = stage_starts.get(stage)
            timings[stage] = 0 if started is None else int((now - started) * 1000)

        _jobs[job_id]["stage"] = stage
        _jobs[job_id]["status"] = status
        if attempt is not None:
            _jobs[job_id]["attempt"] = attempt
        if detail:
            _jobs[job_id]["detail"] = detail
        _jobs[job_id]["stages_elapsed_ms"] = timings

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
            "result": GenerateResult(
                game_name=request.game_name,
                dsl=artifacts.schema.model_dump(by_alias=True),
                research_output=artifacts.research_output,
                stages_elapsed_ms=timings,
            ).model_dump(),
        }
    except Exception as exc:  # noqa: BLE001
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "error",
            "stage": _jobs.get(job_id, {}).get("stage", "unknown"),
            "error": str(exc),
        }


@router.post("")
async def generate_game(request: GenerateRequest):
    """Generate a game DSL with SSE-streamed progress events."""

    async def event_stream():
        stage_starts: dict[str, float] = {}
        timings: dict[str, int] = {}
        event_queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

        async def on_stage(
            stage: str,
            status: str,
            attempt: int | None = None,
            detail: str | None = None,
        ) -> None:
            now = time.monotonic()
            payload = StageEvent(stage=stage, status=StageStatus(status))

            if status == StageStatus.started.value:
                stage_starts[stage] = now
            elif status == StageStatus.done.value:
                started = stage_starts.get(stage)
                elapsed = 0 if started is None else int((now - started) * 1000)
                payload.elapsed_ms = elapsed
                timings[stage] = elapsed

            if attempt is not None:
                payload.attempt = attempt
            if detail:
                payload.detail = detail

            await event_queue.put(("stage", payload.model_dump(exclude_none=True)))

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
                event_type, payload = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                yield sse_event(event_type, payload)
            except asyncio.TimeoutError:
                continue

        try:
            artifacts: PipelineArtifacts = pipeline_task.result()
        except Exception as exc:  # noqa: BLE001
            yield sse_event("error", {"message": str(exc)})
            return

        yield sse_event("research_output", {"rules": artifacts.research_output})
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
        "result": None,
    }
    background_tasks.add_task(_run_pipeline_job, job_id, request)
    return AsyncJobResult(job_id=job_id)


@router.get("/{job_id}")
async def get_job_status(job_id: str):
    """Polling status endpoint for async jobs."""

    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
