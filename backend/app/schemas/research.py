"""Schemas for structured Stage 1 research output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ResearchValue = str | int | float | bool | None


class CardTypeResearch(BaseModel):
    """A distinct card type extracted from researched rules."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        description="Card type name, e.g. 'Skip', 'Wild Draw Four', 'Exploding Kitten'.",
    )
    count: int = Field(..., ge=0, description="Number of cards for this type.")
    count_rule: str | None = Field(
        None,
        description=(
            "Optional formula when card count depends on player count, "
            "e.g. 'players - 1'."
        ),
    )
    properties: dict[str, object] = Field(
        default_factory=dict,
        description="Card attributes like color, suit, rank, value, or tags.",
    )
    effect: str = Field(
        "",
        description="Human-readable effect summary for this card type.",
    )
    category: str | None = Field(
        None,
        description="Optional grouping label such as number/action/wild/cat.",
    )


class ZoneResearch(BaseModel):
    """A game zone extracted from researched rules."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Zone key, e.g. draw_pile.")
    display_name: str = Field(..., description="Human-readable zone name.")
    description: str = Field("", description="Purpose of the zone.")
    visibility: str = Field(
        ...,
        description="Who can see cards in this zone (hidden/top_only/owner_only/all).",
    )
    per_player: bool = Field(
        False,
        description="Whether each player gets an instance of this zone.",
    )


class TurnPhaseResearch(BaseModel):
    """One phase in the researched turn structure."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Phase name.")
    description: str = Field(..., description="What happens during the phase.")
    mandatory: bool = Field(
        True,
        description="Whether this phase must be completed when reached.",
    )


class SpecialMechanic(BaseModel):
    """A mechanic toggle surfaced to users during rule editing."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Short mechanic name.")
    description: str = Field(..., description="What this mechanic changes.")
    enabled: bool = Field(
        True,
        description="Whether the mechanic is enabled in the edited rules.",
    )
    category: Literal["core", "optional", "house_rule"] = Field(
        "core",
        description="Classification of the mechanic.",
    )


class CardEffectResearch(BaseModel):
    """A researched card effect tied to a specific card type."""

    model_config = ConfigDict(extra="forbid")

    card_name: str = Field(..., description="Card type this effect belongs to.")
    trigger: Literal["on_play", "on_draw", "on_discard", "combo", "other"] = Field(
        "on_play",
        description="When this effect triggers.",
    )
    description: str = Field(..., description="Natural language effect behavior.")
    targets_player: bool = Field(
        False,
        description="Whether this effect requires selecting another player.",
    )


class ResearchedRules(BaseModel):
    """Structured rules document editable by the frontend."""

    model_config = ConfigDict(extra="forbid")

    game_name: str = Field(..., description="Card game name.")
    player_count_min: int = Field(..., ge=1, description="Minimum supported players.")
    player_count_max: int = Field(..., ge=1, description="Maximum supported players.")
    estimated_play_time_minutes: int | None = Field(
        None,
        ge=1,
        description="Estimated game duration in minutes.",
    )
    win_condition_type: str = Field(
        ...,
        description=(
            "Type of win condition such as first_empty_hand, last_alive, "
            "highest_score, most_sets, best_hand, or custom."
        ),
    )
    win_condition_description: str = Field(
        ...,
        description="Detailed description of how the winner is determined.",
    )

    card_types: list[CardTypeResearch] = Field(
        ...,
        description="Deck composition list of all card types.",
    )
    zones: list[ZoneResearch] = Field(
        ...,
        description="List of zones present in the game.",
    )
    turn_phases: list[TurnPhaseResearch] = Field(
        ...,
        description="Ordered turn phases.",
    )
    card_effects: list[CardEffectResearch] = Field(
        default_factory=list,
        description="Detailed per-card effects.",
    )
    special_mechanics: list[SpecialMechanic] = Field(
        default_factory=list,
        description="Optional/core/house mechanics discovered during research.",
    )

    has_interrupts: bool = Field(
        False,
        description="Whether the game includes out-of-turn reactions.",
    )
    has_player_elimination: bool = Field(
        False,
        description="Whether players can be removed before game end.",
    )
    has_combos: bool = Field(
        False,
        description="Whether multi-card combo plays are allowed.",
    )
    has_scoring: bool = Field(
        False,
        description="Whether scoring points is part of win evaluation.",
    )
    has_betting: bool = Field(
        False,
        description="Whether betting/pot mechanics are part of gameplay.",
    )

    raw_rules_text: str = Field(
        ...,
        description="Original researched markdown rules text.",
    )
    additional_rules: str | None = Field(
        None,
        description="Optional user-authored rule adjustments.",
    )

    @model_validator(mode="after")
    def validate_player_bounds(self) -> "ResearchedRules":
        if self.player_count_max < self.player_count_min:
            raise ValueError("player_count_max must be >= player_count_min")
        return self
