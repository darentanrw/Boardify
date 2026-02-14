"""Core game components shared by the top-level DSL schema."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.operations import Operation
from app.schemas.primitives import PrimitiveValue, ValueRef


class OnEmpty(BaseModel):
    """Zone behavior triggered when the zone runs out of cards."""

    model_config = ConfigDict(extra="forbid")

    sequence: list[Operation] = Field(..., description="Operations run when zone becomes empty.")


class Zone(BaseModel):
    """Zone definition controlling card layout and visibility."""

    model_config = ConfigDict(extra="forbid")

    behavior: str = Field(..., description="stack, hand_fan, spread, grid, etc.")
    visibility: str = Field(..., description="hidden, top_only, owner_only, all, etc.")
    per_player: bool = Field(False, description="Whether each player has a copy of this zone.")
    on_empty: OnEmpty | None = Field(None, description="Optional empty-zone handler.")
    on_draw: list[Operation] | None = Field(
        None,
        description=(
            "Optional sequence triggered after a card is drawn from this zone. "
            "Use $args.drawn_card references for drawn-card logic."
        ),
    )


class DeckManifestEntry(BaseModel):
    """Card template expansion entry for deck creation."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Template id, can include placeholders.")
    template_vars: dict[str, list[PrimitiveValue]] = Field(
        default_factory=dict,
        description="Placeholder values used to expand card combinations.",
    )
    data: dict[str, ValueRef] = Field(
        default_factory=dict,
        description="Card data payload for generated cards.",
    )
    img: str | None = Field(None, description="Optional card image key/path.")
    per_combination: int = Field(
        1,
        ge=1,
        description="Copies generated for each template variable combination.",
    )


class CardEffect(BaseModel):
    """Declarative card effect mapping used by effect-evaluation routines."""

    model_config = ConfigDict(extra="forbid")

    match: dict[str, ValueRef] = Field(
        default_factory=dict,
        description="Field-value map used to match cards.",
    )
    sequence: list[Operation] = Field(..., description="Operations executed when match passes.")


class VariableSpec(BaseModel):
    """Type/default definition for engine variables."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(..., description="Variable type label (number/string/boolean/etc.).")
    default: ValueRef = Field(None, description="Default variable value.")


class Variables(BaseModel):
    """Container for global and per-player variable declarations."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    global_: dict[str, VariableSpec] = Field(
        default_factory=dict,
        alias="global",
        description="Global game variables.",
    )
    per_player: dict[str, VariableSpec] = Field(
        default_factory=dict,
        description="Variables maintained per player.",
    )
