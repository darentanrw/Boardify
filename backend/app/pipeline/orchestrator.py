"""Pipeline orchestrator chaining research, generation, and validation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.config import settings
from app.pipeline.generate import generate_dsl_json, generate_game_plan, validate_and_retry
from app.pipeline.research import research_game
from app.schemas.game import GameSchema


StageCallback = Callable[..., Awaitable[None]]


def _load_example(name: str) -> str:
    """Load an example DSL JSON file from app/examples."""

    return (Path(__file__).resolve().parents[1] / "examples" / name).read_text()


@dataclass
class PipelineArtifacts:
    """Artifacts produced by the generation pipeline."""

    schema: GameSchema
    research_output: str
    game_plan: str
    raw_json: str


async def generate_game_dsl(
    game_name: str,
    player_count: int | None = None,
    research: str | None = None,
    max_retries: int | None = None,
    on_stage: StageCallback | None = None,
) -> PipelineArtifacts:
    """Run full pipeline: research -> plan -> dsl -> validation."""

    retries = max_retries if max_retries is not None else settings.PIPELINE_MAX_RETRIES

    if research is None:
        if on_stage:
            await on_stage("research", "started")
        stage1 = await research_game(
            game_name=game_name,
            player_count=player_count,
            codex_model_id=settings.DEFAULT_CODEX_MODEL,
        )
        research_output = stage1.serialized_rules_text
        if on_stage:
            await on_stage("research", "done")
    else:
        research_output = research
        if on_stage:
            await on_stage("research", "done", detail="using provided rules")

    if on_stage:
        await on_stage("plan", "started")
    game_plan = await generate_game_plan(
        research_output=research_output,
        codex_model_id=settings.DEFAULT_CODEX_MODEL,
    )
    if on_stage:
        await on_stage("plan", "done")

    if on_stage:
        await on_stage("dsl", "started")
    json_schema = GameSchema.model_json_schema()
    uno_example = _load_example("uno.json")
    raw_json = await generate_dsl_json(
        game_plan=game_plan,
        json_schema=json_schema,
        uno_example=uno_example,
        codex_model_id=settings.DEFAULT_CODEX_MODEL,
    )
    if on_stage:
        await on_stage("dsl", "done")

    if on_stage:
        await on_stage("validation", "started")

    async def _on_retry(attempt: int, error: ValidationError) -> None:
        if on_stage:
            await on_stage(
                "validation",
                "retry",
                attempt=attempt,
                detail=str(error),
            )

    schema, corrected_json = await validate_and_retry(
        raw_json=raw_json,
        json_schema=json_schema,
        max_retries=retries,
        codex_model_id=settings.DEFAULT_CODEX_MODEL,
        on_retry=_on_retry,
    )

    if on_stage:
        await on_stage("validation", "done")

    return PipelineArtifacts(
        schema=schema,
        research_output=research_output,
        game_plan=game_plan,
        raw_json=corrected_json,
    )
