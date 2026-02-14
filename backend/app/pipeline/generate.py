"""Stage 2/3 pipeline: plan generation, DSL generation, and validation retries."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from json import JSONDecodeError
import logging

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
logger = logging.getLogger(__name__)
CODEX_FALLBACK_MODEL_IDS = (
    "gpt-5.2-codex",
    "gpt-5.1-codex",
    "gpt-5-codex",
    "gpt-5.2",
    "gpt-5.1",
    "gpt-5",
    "gpt-5-chat-latest",
    "gpt-4.1",
)

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
        },
    }


def _codex_kwargs() -> dict:
    effort = settings.CODEX_REASONING_EFFORT.strip().lower()
    if effort in {"low", "medium", "high"}:
        return {"reasoning_effort": effort}
    return {}


def _codex_model_candidates(preferred_model_id: str) -> list[str]:
    candidates = [preferred_model_id]
    for candidate in CODEX_FALLBACK_MODEL_IDS:
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _is_model_not_found_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "model_not_found" in message
        or "does not exist or you do not have access" in message
        or "not a chat model" in message
        or "not supported in the v1/chat/completions endpoint" in message
        or "only supported in v1/responses" in message
    )


def _generate_with_codex(*, codex_model_id: str, prompt: str, system: str, **kwargs) -> str:
    last_error: Exception | None = None
    for candidate_model in _codex_model_candidates(codex_model_id):
        codex = get_model("openai", candidate_model)
        request_kwargs = {**_codex_kwargs(), **kwargs}
        logger.info(
            "codex_request stage=generation candidate_model=%s reasoning_effort=%s",
            candidate_model,
            request_kwargs.get("reasoning_effort"),
        )
        try:
            text = generate_text_sync(
                codex,
                prompt=prompt,
                system=system,
                **request_kwargs,
            ).text
            logger.info(
                "codex_request_success stage=generation model=%s response_chars=%s",
                candidate_model,
                len(text),
            )
            return text
        except Exception as exc:  # noqa: BLE001
            if _is_model_not_found_error(exc):
                last_error = exc
                logger.warning(
                    "codex_request_fallback stage=generation model=%s reason=%s",
                    candidate_model,
                    str(exc),
                )
                continue
            if "reasoning_effort" not in request_kwargs:
                raise
            fallback_kwargs = {
                k: v for k, v in request_kwargs.items() if k != "reasoning_effort"
            }
            try:
                logger.info(
                    "codex_request_retry_without_reasoning stage=generation model=%s",
                    candidate_model,
                )
                text = generate_text_sync(
                    codex,
                    prompt=prompt,
                    system=system,
                    **fallback_kwargs,
                ).text
                logger.info(
                    "codex_request_success stage=generation model=%s response_chars=%s",
                    candidate_model,
                    len(text),
                )
                return text
            except Exception as fallback_exc:  # noqa: BLE001
                if _is_model_not_found_error(fallback_exc):
                    last_error = fallback_exc
                    logger.warning(
                        "codex_request_fallback stage=generation model=%s reason=%s",
                        candidate_model,
                        str(fallback_exc),
                    )
                    continue
                raise

    if last_error:
        raise last_error
    raise RuntimeError("Unable to generate with configured or fallback Codex models.")


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

    codex_model = codex_model_id or settings.DEFAULT_CODEX_MODEL
    return _generate_with_codex(
        codex_model_id=codex_model,
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

    codex_model = codex_model_id or settings.DEFAULT_CODEX_MODEL
    raw_output = _generate_with_codex(
        codex_model_id=codex_model,
        prompt=DSL_USER.format(
            json_schema=json.dumps(json_schema, indent=2),
            uno_example=uno_example,
            game_plan=game_plan,
        ),
        system=DSL_SYSTEM,
        response_format=_response_format("game_schema", json_schema),
    )
    return _normalize_json_text(raw_output)


async def retry_with_errors(
    raw_json: str,
    validation_errors: str,
    json_schema: dict,
    codex_model_id: str | None = None,
) -> str:
    """Ask Codex to correct invalid JSON using validator feedback."""

    codex_model = codex_model_id or settings.DEFAULT_CODEX_MODEL
    allowed_ops = ", ".join(sorted(ALLOWED_OPERATION_NAMES))
    retry_prompt = (
        RETRY_USER.format(validation_errors=validation_errors)
        + "\n\nCurrent JSON:\n"
        + raw_json
        + "\n\nAllowed op values (use ONLY these exact op strings):\n"
        + allowed_ops
    )
    corrected = _generate_with_codex(
        codex_model_id=codex_model,
        prompt=retry_prompt,
        system=DSL_SYSTEM,
        response_format=_response_format("game_schema", json_schema),
    )
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
