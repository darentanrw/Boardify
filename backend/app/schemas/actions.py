"""Action and FSM schemas for gameplay orchestration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.operations import Operation
from app.schemas.primitives import Condition


class ReactionWindow(BaseModel):
    """Reaction window opened after an action resolves."""

    model_config = ConfigDict(extra="forbid")

    eligible_card_type: str = Field(
        ...,
        description="Card type that can be used to react, e.g. nope.",
    )
    allows_chain: bool = Field(
        True,
        description="Whether reactions can be reacted to again.",
    )
    timeout_seconds: int | None = Field(
        None,
        ge=1,
        description="Optional timeout before the window closes.",
    )


class Action(BaseModel):
    """Player-triggered action in the FSM."""

    model_config = ConfigDict(extra="forbid")

    phase: str | list[str] = Field(
        ...,
        description="Phase(s) where action is available.",
    )
    trigger: Literal["click_card", "click_zone", "click_button", "reaction"] | str = Field(
        ...,
        description="UI trigger type.",
    )
    source_zone: str | None = Field(None, description="Source zone for card/zone interactions.")
    mutex_group: str | None = Field(
        None,
        description="Optional mutual-exclusion action group.",
    )
    max_per_turn: int | None = Field(
        None,
        ge=1,
        description="Maximum uses per turn; null means unlimited.",
    )
    card_count: int = Field(
        1,
        ge=1,
        description="Cards required for this action (combo support).",
    )
    card_match_rule: Literal["same_type", "all_different"] | None = Field(
        None,
        description="Combo matching rule when card_count > 1.",
    )
    any_phase: bool = Field(
        False,
        description="Whether action can be played out of normal turn order.",
    )
    reaction_window: ReactionWindow | None = Field(
        None,
        description="Optional follow-up reaction window.",
    )
    conditions: list[Condition] = Field(
        default_factory=list,
        description="All conditions that must pass before action can execute.",
    )
    sequence: list[Operation] = Field(..., description="Operations executed by this action.")
    ui_label: str | None = Field(None, description="Button label for click_button actions.")


class FSM(BaseModel):
    """Finite state machine definition for the game loop."""

    model_config = ConfigDict(extra="forbid")

    turn_phases: list[str] = Field(..., min_length=1, description="Ordered phase names.")
    routines: dict[str, list[Operation]] = Field(
        default_factory=dict,
        description="Named operation sequences callable by trigger_routine.",
    )
    actions: dict[str, Action] = Field(
        default_factory=dict,
        description="Action map keyed by action id.",
    )
