"""Stage 1 pipeline: research rules and parse into structured form."""

from __future__ import annotations

import json
from dataclasses import dataclass
from json import JSONDecodeError

from pydantic import ValidationError

from app.config import settings
from app.llm import generate_text_sync, get_model
from app.pipeline.prompts.parse_research import PARSE_SYSTEM, PARSE_USER
from app.pipeline.prompts.research import RESEARCH_SYSTEM, RESEARCH_USER
from app.schemas.research import ResearchedRules


def _response_format(schema_name: str, schema: dict) -> dict:
    """Build OpenAI json_schema response format payload."""

    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name,
            "schema": schema,
            "strict": True,
        },
    }


def _codex_kwargs() -> dict:
    """Common OpenAI kwargs for Codex-like reasoning models."""

    effort = settings.CODEX_REASONING_EFFORT.strip().lower()
    if effort in {"low", "medium", "high"}:
        return {"reasoning_effort": effort}
    return {}


def _generate_with_codex(*, codex, prompt: str, system: str, **kwargs) -> str:
    """Generate text and gracefully retry without reasoning if unsupported."""

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


def _load_json_from_llm(text: str) -> dict:
    """Parse JSON from model output, tolerating fenced blocks."""

    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    try:
        data = json.loads(candidate)
        if not isinstance(data, dict):
            raise ValueError("Expected top-level JSON object.")
        return data
    except JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Could not parse JSON object from model output.") from None
        data = json.loads(candidate[start : end + 1])
        if not isinstance(data, dict):
            raise ValueError("Expected top-level JSON object.")
        return data


def parse_researched_rules(
    raw_rules_text: str,
    codex_model_id: str | None = None,
    parse_max_retries: int | None = None,
) -> ResearchedRules:
    """Use Codex to parse markdown research text into ResearchedRules JSON."""

    schema = ResearchedRules.model_json_schema()
    codex = get_model("openai", codex_model_id or settings.DEFAULT_CODEX_MODEL)
    retries = max(
        1,
        parse_max_retries if parse_max_retries is not None else settings.PIPELINE_MAX_RETRIES,
    )
    base_prompt = PARSE_USER.format(
        raw_rules_text=raw_rules_text,
        research_schema=json.dumps(schema, indent=2),
    )
    current_prompt = base_prompt
    for attempt in range(retries):
        parsed_text = _generate_with_codex(
            codex=codex,
            prompt=current_prompt,
            system=PARSE_SYSTEM,
            response_format=_response_format("researched_rules", schema),
        )

        payload = _load_json_from_llm(parsed_text)
        payload.setdefault("raw_rules_text", raw_rules_text)
        try:
            return ResearchedRules.model_validate(payload)
        except ValidationError as exc:
            if attempt == retries - 1:
                raise
            current_prompt = (
                f"{base_prompt}\n\n"
                f"Your previous JSON failed validation:\n{exc}\n\n"
                "Previous JSON:\n"
                f"{json.dumps(payload, indent=2)}\n\n"
                "Fix the JSON so it satisfies the schema exactly. Output ONLY valid JSON."
            )

    raise RuntimeError("Unreachable parse retry state.")


def _format_property_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return str(value)


def serialize_to_rules_text(rules: ResearchedRules) -> str:
    """Convert structured ResearchedRules back into markdown for Stage 2."""

    sections: list[str] = []

    sections.append(f"# {rules.game_name}")
    sections.append(f"Players: {rules.player_count_min}-{rules.player_count_max}")
    if rules.estimated_play_time_minutes:
        sections.append(f"Play time: ~{rules.estimated_play_time_minutes} minutes")
    sections.append(
        f"Win condition: {rules.win_condition_type} -- {rules.win_condition_description}"
    )

    sections.append("\n## DECK COMPOSITION")
    for card_type in rules.card_types:
        count_note = f" ({card_type.count_rule})" if card_type.count_rule else ""
        props = (
            ", ".join(
                f"{k}={_format_property_value(v)}" for k, v in card_type.properties.items()
            )
            if card_type.properties
            else ""
        )
        sections.append(
            f"- {card_type.name}: {card_type.count} cards{count_note}. {props}. {card_type.effect}"
        )

    sections.append("\n## GAME ZONES")
    for zone in rules.zones:
        sections.append(
            f"- {zone.display_name} ({zone.name}): {zone.description}. Visibility: {zone.visibility}"
        )

    sections.append("\n## TURN STRUCTURE")
    for index, phase in enumerate(rules.turn_phases, start=1):
        marker = "(mandatory)" if phase.mandatory else "(optional)"
        sections.append(f"{index}. {phase.name}: {phase.description} {marker}")

    sections.append("\n## CARD EFFECTS")
    for effect in rules.card_effects:
        sections.append(f"- {effect.card_name} ({effect.trigger}): {effect.description}")

    sections.append("\n## SPECIAL MECHANICS")
    for mechanic in rules.special_mechanics:
        if mechanic.enabled:
            sections.append(f"- {mechanic.name}: {mechanic.description}")
        else:
            sections.append(f"- ~~{mechanic.name}~~: DISABLED BY USER")

    if rules.additional_rules:
        sections.append(f"\n## ADDITIONAL RULES (USER)\n{rules.additional_rules}")

    return "\n".join(sections)


@dataclass
class ResearchArtifacts:
    """Outputs produced by Stage 1 research."""

    raw_rules_text: str
    parsed_rules: ResearchedRules
    serialized_rules_text: str


async def research_game(
    game_name: str,
    player_count: int | None = None,
    perplexity_model_id: str | None = None,
    codex_model_id: str | None = None,
) -> ResearchArtifacts:
    """Run Perplexity research and parse output into structured rules."""

    perplexity = get_model("perplexity", perplexity_model_id or settings.DEFAULT_PERPLEXITY_MODEL)
    prompt = RESEARCH_USER.format(game_name=game_name)
    if player_count is not None:
        prompt = (
            f"{prompt}\n\nAssume a typical game with {player_count} players for any dynamic card counts."
        )

    raw_rules_text = generate_text_sync(
        perplexity,
        prompt=prompt,
        system=RESEARCH_SYSTEM,
    ).text

    parsed_rules = parse_researched_rules(
        raw_rules_text=raw_rules_text,
        codex_model_id=codex_model_id,
    )
    serialized_rules_text = serialize_to_rules_text(parsed_rules)
    return ResearchArtifacts(
        raw_rules_text=raw_rules_text,
        parsed_rules=parsed_rules,
        serialized_rules_text=serialized_rules_text,
    )
