"""Stage 2/3 pipeline: plan generation, DSL generation, and validation retries."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from json import JSONDecodeError

from pydantic import ValidationError

from app.config import settings
from app.llm import generate_text_sync, get_model
from app.pipeline.prompts.generation import (
    DSL_SYSTEM,
    DSL_USER,
    PLAN_SYSTEM,
    PLAN_USER,
    RETRY_USER,
)
from app.schemas.game import GameSchema


RetryCallback = Callable[[int, ValidationError], Awaitable[None]]

ALLOWED_OPERATION_NAMES = {
    "spawn_from_manifest",
    "shuffle",
    "deal",
    "move",
    "move_all_except_top",
    "set_global",
    "set_player_var",
    "mutate_global",
    "mutate_player_var",
    "branch",
    "advance_turn",
    "transition_phase",
    "trigger_routine",
    "prompt",
    "game_over",
    "log",
    "reveal",
    "evaluate_hand",
    "compare_hands",
    "add_score",
    "collect_to_pot",
    "award_pot",
    "for_each_player",
    "check_group",
    "peek",
    "insert_at",
    "choose_player",
    "eliminate_player",
    "choose_from_zone",
}
CONDITION_OP_NAMES = {"eq", "neq", "gt", "lt", "gte", "lte", "and", "or", "not", "has_matching", "is_alive"}


def _response_format(schema_name: str, schema: dict) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name,
            "schema": schema,
            "strict": True,
        },
    }


def _codex_kwargs() -> dict:
    effort = settings.CODEX_REASONING_EFFORT.strip().lower()
    if effort in {"low", "medium", "high"}:
        return {"reasoning_effort": effort}
    return {}


def _generate_with_codex(*, codex, prompt: str, system: str, **kwargs) -> str:
    request_kwargs = {**_codex_kwargs(), **kwargs}
    try:
        return generate_text_sync(
            codex,
            prompt=prompt,
            system=system,
            **request_kwargs,
        ).text
    except Exception:  # noqa: BLE001
        if "reasoning_effort" not in request_kwargs:
            raise
        fallback_kwargs = {
            k: v for k, v in request_kwargs.items() if k != "reasoning_effort"
        }
        return generate_text_sync(
            codex,
            prompt=prompt,
            system=system,
            **fallback_kwargs,
        ).text


def _sanitize_generated_json(node):
    """Light cleanup for common model drift before strict validation."""

    if isinstance(node, list):
        return [_sanitize_generated_json(item) for item in node]
    if not isinstance(node, dict):
        return node

    sanitized = {key: _sanitize_generated_json(value) for key, value in node.items()}
    op_value = sanitized.get("op")
    if not isinstance(op_value, str):
        return sanitized

    if op_value == "prompt":
        options = sanitized.get("options")
        if isinstance(options, str):
            sanitized["options"] = [options]

    if op_value in ALLOWED_OPERATION_NAMES or op_value in CONDITION_OP_NAMES:
        return sanitized

    payload = {key: value for key, value in sanitized.items() if key != "op"}
    return {
        "op": "trigger_routine",
        "name": f"_unsupported_{op_value}",
        "args": {
            "source_op": op_value,
            "payload": payload,
        },
    }


def _normalize_json_text(text: str) -> str:
    """Normalize model output to compact-valid JSON text."""

    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    try:
        parsed = json.loads(candidate)
    except JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Model output did not include a JSON object.") from None
        parsed = json.loads(candidate[start : end + 1])

    parsed = _sanitize_generated_json(parsed)
    return json.dumps(parsed, separators=(",", ":"))


async def generate_game_plan(
    research_output: str,
    codex_model_id: str | None = None,
) -> str:
    """Generate a natural-language game architecture plan."""

    codex = get_model("openai", codex_model_id or settings.DEFAULT_CODEX_MODEL)
    return _generate_with_codex(
        codex=codex,
        prompt=PLAN_USER.format(research_output=research_output),
        system=PLAN_SYSTEM,
    )


async def generate_dsl_json(
    game_plan: str,
    json_schema: dict,
    uno_example: str,
    codex_model_id: str | None = None,
) -> str:
    """Generate game DSL JSON constrained by the provided schema."""

    codex = get_model("openai", codex_model_id or settings.DEFAULT_CODEX_MODEL)
    raw_output = _generate_with_codex(
        codex=codex,
        prompt=DSL_USER.format(
            json_schema=json.dumps(json_schema, indent=2),
            uno_example=uno_example,
            game_plan=game_plan,
        ),
        system=DSL_SYSTEM,
        response_format=_response_format("game_schema", json_schema),
    ).text
    return _normalize_json_text(raw_output)


async def retry_with_errors(
    raw_json: str,
    validation_errors: str,
    json_schema: dict,
    codex_model_id: str | None = None,
) -> str:
    """Ask Codex to correct invalid JSON using validator feedback."""

    codex = get_model("openai", codex_model_id or settings.DEFAULT_CODEX_MODEL)
    allowed_ops = ", ".join(sorted(ALLOWED_OPERATION_NAMES))
    retry_prompt = (
        RETRY_USER.format(validation_errors=validation_errors)
        + "\n\nCurrent JSON:\n"
        + raw_json
        + "\n\nAllowed op values (use ONLY these exact op strings):\n"
        + allowed_ops
    )
    corrected = _generate_with_codex(
        codex=codex,
        prompt=retry_prompt,
        system=DSL_SYSTEM,
        response_format=_response_format("game_schema", json_schema),
    ).text
    return _normalize_json_text(corrected)


async def validate_and_retry(
    raw_json: str,
    json_schema: dict,
    max_retries: int | None = None,
    codex_model_id: str | None = None,
    on_retry: RetryCallback | None = None,
) -> tuple[GameSchema, str]:
    """Validate JSON into GameSchema with retry loop on ValidationError."""

    retries = max_retries if max_retries is not None else settings.PIPELINE_MAX_RETRIES
    current_json = raw_json
    for attempt in range(retries):
        try:
            schema = GameSchema.model_validate_json(current_json)
            return schema, current_json
        except ValidationError as exc:
            if attempt == retries - 1:
                raise
            if on_retry:
                await on_retry(attempt + 1, exc)
            current_json = await retry_with_errors(
                raw_json=current_json,
                validation_errors=str(exc),
                json_schema=json_schema,
                codex_model_id=codex_model_id,
            )

    raise RuntimeError("Unreachable validation retry state.")
