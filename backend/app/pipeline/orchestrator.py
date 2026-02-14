"""Pipeline orchestrator chaining research, generation, and validation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from pathlib import Path
import time

from pydantic import ValidationError

from app.config import settings
from app.pipeline.generate import generate_dsl_json, generate_game_plan, validate_and_retry
from app.pipeline.research import research_game
from app.schemas.game import GameSchema


StageCallback = Callable[..., Awaitable[None]]
logger = logging.getLogger(__name__)


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
    pipeline_start = time.monotonic()

    def _summarize_validation_error(error: ValidationError, max_len: int = 320) -> str:
        text = str(error).replace("\n", " ")
        return text if len(text) <= max_len else f"{text[:max_len]}..."

    logger.info(
        "pipeline_start game=%s player_count=%s retries=%s research_override=%s codex_model=%s",
        game_name,
        player_count,
        retries,
        research is not None,
        settings.DEFAULT_CODEX_MODEL,
    )

    if research is None:
        if on_stage:
            await on_stage(
                "research",
                "started",
                detail="Running Perplexity research and parsing structured rules",
            )
        research_start = time.monotonic()
        stage1 = await research_game(
            game_name=game_name,
            player_count=player_count,
            codex_model_id=settings.DEFAULT_CODEX_MODEL,
        )
        research_output = stage1.serialized_rules_text
        research_elapsed = int((time.monotonic() - research_start) * 1000)
        logger.info(
            "pipeline_stage_done stage=research elapsed_ms=%s game=%s raw_chars=%s card_types=%s",
            research_elapsed,
            game_name,
            len(stage1.raw_rules_text),
            len(stage1.parsed_rules.card_types),
        )
        if on_stage:
            await on_stage(
                "research",
                "done",
                detail=(
                    "Research parsed successfully: "
                    f"{len(stage1.parsed_rules.card_types)} card types, "
                    f"{len(stage1.parsed_rules.zones)} zones"
                ),
            )
    else:
        research_output = research
        logger.info(
            "pipeline_stage_done stage=research elapsed_ms=0 game=%s mode=override rules_chars=%s",
            game_name,
            len(research_output),
        )
        if on_stage:
            await on_stage(
                "research",
                "done",
                detail="Using provided research_override rules (Stage 1 skipped)",
            )

    if on_stage:
        await on_stage(
            "plan",
            "started",
            detail="Generating architecture plan from researched rules",
        )
    plan_start = time.monotonic()
    game_plan = await generate_game_plan(
        research_output=research_output,
        codex_model_id=settings.DEFAULT_CODEX_MODEL,
    )
    plan_elapsed = int((time.monotonic() - plan_start) * 1000)
    logger.info(
        "pipeline_stage_done stage=plan elapsed_ms=%s game=%s plan_chars=%s",
        plan_elapsed,
        game_name,
        len(game_plan),
    )
    if on_stage:
        await on_stage(
            "plan",
            "done",
            detail=f"Plan generated ({len(game_plan)} characters)",
        )

    if on_stage:
        await on_stage(
            "dsl",
            "started",
            detail="Generating DSL JSON constrained by GameSchema JSON schema",
        )
    dsl_start = time.monotonic()
    json_schema = GameSchema.model_json_schema()
    uno_example = _load_example("uno.json")
    exploding_example = _load_example("exploding_kittens.json")
    reference_examples = (
        "### Uno\n"
        f"{uno_example}\n\n"
        "### Exploding Kittens\n"
        f"{exploding_example}"
    )
    raw_json = await generate_dsl_json(
        game_plan=game_plan,
        json_schema=json_schema,
        uno_example=reference_examples,
        codex_model_id=settings.DEFAULT_CODEX_MODEL,
    )
    dsl_elapsed = int((time.monotonic() - dsl_start) * 1000)
    logger.info(
        "pipeline_stage_done stage=dsl elapsed_ms=%s game=%s json_chars=%s",
        dsl_elapsed,
        game_name,
        len(raw_json),
    )
    if on_stage:
        await on_stage(
            "dsl",
            "done",
            detail=f"Generated candidate DSL JSON ({len(raw_json)} characters)",
        )

    if on_stage:
        await on_stage(
            "validation",
            "started",
            detail=f"Validating DSL (max retries: {retries})",
        )
    validation_start = time.monotonic()

    async def _on_retry(attempt: int, error: ValidationError) -> None:
        summary = _summarize_validation_error(error)
        logger.warning(
            "pipeline_stage_retry stage=validation game=%s attempt=%s detail=%s",
            game_name,
            attempt,
            summary,
        )
        if on_stage:
            await on_stage(
                "validation",
                "retry",
                attempt=attempt,
                detail=summary,
            )

    schema, corrected_json = await validate_and_retry(
        raw_json=raw_json,
        json_schema=json_schema,
        max_retries=retries,
        codex_model_id=settings.DEFAULT_CODEX_MODEL,
        on_retry=_on_retry,
    )

    validation_elapsed = int((time.monotonic() - validation_start) * 1000)
    total_elapsed = int((time.monotonic() - pipeline_start) * 1000)
    logger.info(
        "pipeline_complete game=%s validation_elapsed_ms=%s total_elapsed_ms=%s",
        game_name,
        validation_elapsed,
        total_elapsed,
    )
    if on_stage:
        await on_stage(
            "validation",
            "done",
            detail="Validation succeeded",
        )

    return PipelineArtifacts(
        schema=schema,
        research_output=research_output,
        game_plan=game_plan,
        raw_json=corrected_json,
    )
