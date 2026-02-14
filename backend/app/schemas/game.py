"""Top-level game DSL schema and semantic cross-reference validators."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.actions import Action, FSM
from app.schemas.components import CardEffect, DeckManifestEntry, Variables, Zone
from app.schemas.operations import (
    AddScoreOp,
    AwardPotOp,
    BranchOp,
    CheckGroupOp,
    ChooseFromZoneOp,
    CollectToPotOp,
    DealOp,
    EliminatePlayerOp,
    ForEachPlayerOp,
    InsertAtOp,
    MoveAllExceptTopOp,
    MoveOp,
    MutateGlobalOp,
    MutatePlayerVarOp,
    Operation,
    PeekOp,
    RevealOp,
    SetGlobalOp,
    SetPlayerVarOp,
    ShuffleOp,
    TransitionPhaseOp,
    TriggerRoutineOp,
)
from app.schemas.primitives import CompoundCondition, LeafCondition, NotCondition, PlayerCount


class GameMeta(BaseModel):
    """Top-level game metadata."""

    model_config = ConfigDict(extra="forbid")

    game_name: str = Field(..., description="Display name for the game.")
    version: str | None = Field(None, description="DSL version string.")
    player_count: PlayerCount = Field(..., description="Supported player range.")
    win_condition: str = Field(..., description="High-level win condition identifier.")


class Assets(BaseModel):
    """Asset and manifest definitions for the game."""

    model_config = ConfigDict(extra="forbid")

    deck_manifest: list[DeckManifestEntry] = Field(
        default_factory=list,
        description="Card template entries used during setup.",
    )


class GameSchema(BaseModel):
    """Generalized card game DSL schema."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    meta: GameMeta
    assets: Assets
    zones: dict[str, Zone]
    variables: Variables
    card_effects: list[CardEffect] = Field(default_factory=list)
    fsm: FSM

    @model_validator(mode="after")
    def validate_references(self) -> "GameSchema":
        zone_names = set(self.zones.keys())
        phase_names = set(self.fsm.turn_phases)
        routine_names = set(self.fsm.routines.keys())
        global_var_names = set(self.variables.global_.keys())
        per_player_var_names = set(self.variables.per_player.keys())

        for action_name, action in self.fsm.actions.items():
            self._validate_action_reference(action_name, action, zone_names, phase_names)

        for op in self._iter_all_operations():
            self._validate_operation_references(
                op=op,
                zone_names=zone_names,
                phase_names=phase_names,
                routine_names=routine_names,
                global_var_names=global_var_names,
                per_player_var_names=per_player_var_names,
            )

        return self

    @model_validator(mode="after")
    def validate_reaction_windows(self) -> "GameSchema":
        actions_with_windows: list[tuple[str, Action]] = [
            (name, action)
            for name, action in self.fsm.actions.items()
            if action.reaction_window is not None
        ]
        if not actions_with_windows:
            return self

        reactive_actions = [
            action for action in self.fsm.actions.values() if action.any_phase
        ]
        if not reactive_actions:
            raise ValueError(
                "At least one any_phase action is required when reaction_window is used."
            )

        for action_name, action in actions_with_windows:
            eligible_card_type = action.reaction_window.eligible_card_type
            if not any(
                self._action_can_react_with_card_type(candidate, eligible_card_type)
                for candidate in reactive_actions
            ):
                raise ValueError(
                    f"Action '{action_name}' opens reaction_window for card type "
                    f"'{eligible_card_type}' but no any_phase action can play it."
                )

        return self

    def _iter_all_operations(self) -> Iterable[Operation]:
        for zone in self.zones.values():
            if zone.on_empty:
                yield from self._walk_operations(zone.on_empty.sequence)
            if zone.on_draw:
                yield from self._walk_operations(zone.on_draw)

        for effect in self.card_effects:
            yield from self._walk_operations(effect.sequence)

        for sequence in self.fsm.routines.values():
            yield from self._walk_operations(sequence)

        for action in self.fsm.actions.values():
            yield from self._walk_operations(action.sequence)

    def _walk_operations(self, sequence: list[Operation]) -> Iterable[Operation]:
        for op in sequence:
            yield op
            if isinstance(op, BranchOp):
                yield from self._walk_operations(op.if_true)
                yield from self._walk_operations(op.if_false)
            elif isinstance(op, ForEachPlayerOp):
                yield from self._walk_operations(op.sequence)

    @staticmethod
    def _normalize_zone_ref(zone_ref: str) -> str | None:
        if zone_ref.startswith("$zone."):
            tail = zone_ref.removeprefix("$zone.")
            return tail.split(".", 1)[0] if tail else None
        if zone_ref.startswith("$"):
            return None
        return zone_ref

    @staticmethod
    def _is_valid_zone_ref(zone_ref: str, zone_names: set[str]) -> bool:
        normalized = GameSchema._normalize_zone_ref(zone_ref)
        if normalized is None:
            return True
        return normalized in zone_names

    @staticmethod
    def _validate_action_reference(
        action_name: str,
        action: Action,
        zone_names: set[str],
        phase_names: set[str],
    ) -> None:
        if action.source_zone and not GameSchema._is_valid_zone_ref(
            action.source_zone, zone_names
        ):
            raise ValueError(
                f"Action '{action_name}' references unknown source zone '{action.source_zone}'."
            )

        phases = [action.phase] if isinstance(action.phase, str) else list(action.phase)
        for phase in phases:
            if phase not in phase_names:
                raise ValueError(
                    f"Action '{action_name}' references unknown phase '{phase}'."
                )

    @staticmethod
    def _validate_operation_references(
        op: Operation,
        zone_names: set[str],
        phase_names: set[str],
        routine_names: set[str],
        global_var_names: set[str],
        per_player_var_names: set[str],
    ) -> None:
        def check_zone(value: str | None, field_name: str) -> None:
            if value and not GameSchema._is_valid_zone_ref(value, zone_names):
                raise ValueError(
                    f"Operation '{op.op}' references unknown zone '{value}' in '{field_name}'."
                )

        if isinstance(op, ShuffleOp | RevealOp | PeekOp):
            check_zone(op.zone, "zone")
        elif isinstance(op, DealOp):
            check_zone(op.from_, "from")
            if op.to not in {"all_players"}:
                check_zone(op.to, "to")
        elif isinstance(op, MoveOp):
            check_zone(op.from_, "from")
            check_zone(op.to, "to")
        elif isinstance(op, MoveAllExceptTopOp):
            check_zone(op.from_, "from")
            check_zone(op.to, "to")
        elif isinstance(op, InsertAtOp):
            check_zone(op.zone, "zone")
        elif isinstance(op, ChooseFromZoneOp):
            check_zone(op.zone, "zone")
        elif isinstance(op, CheckGroupOp):
            check_zone(op.zone, "zone")
        elif isinstance(op, TransitionPhaseOp):
            if op.to not in phase_names:
                raise ValueError(
                    f"Operation 'transition_phase' references unknown phase '{op.to}'."
                )
        elif isinstance(op, TriggerRoutineOp):
            if op.name not in routine_names and not op.name.startswith("_"):
                raise ValueError(
                    f"Operation 'trigger_routine' references unknown routine '{op.name}'."
                )
        elif isinstance(op, SetGlobalOp | MutateGlobalOp):
            if op.key not in global_var_names:
                raise ValueError(
                    f"Operation '{op.op}' references unknown global variable '{op.key}'."
                )
        elif isinstance(op, SetPlayerVarOp | MutatePlayerVarOp):
            if op.key not in per_player_var_names:
                raise ValueError(
                    f"Operation '{op.op}' references unknown per_player variable '{op.key}'."
                )
        elif isinstance(op, CollectToPotOp | AwardPotOp):
            if op.pot_key not in global_var_names:
                raise ValueError(
                    f"Operation '{op.op}' references unknown global pot key '{op.pot_key}'."
                )
        elif isinstance(op, AddScoreOp | EliminatePlayerOp):
            return

    @staticmethod
    def _action_can_react_with_card_type(action: Action, card_type: str) -> bool:
        if not action.conditions:
            return True
        return any(
            GameSchema._condition_matches_card_type(condition, card_type)
            for condition in action.conditions
        )

    @staticmethod
    def _condition_matches_card_type(condition: object, card_type: str) -> bool:
        if isinstance(condition, LeafCondition):
            values = (condition.val1, condition.val2)
            return (
                condition.op == "eq"
                and "$card.data.type" in values
                and card_type in values
            )
        if isinstance(condition, CompoundCondition):
            return any(
                GameSchema._condition_matches_card_type(arg, card_type)
                for arg in condition.args
            )
        if isinstance(condition, NotCondition):
            return GameSchema._condition_matches_card_type(condition.arg, card_type)
        return False
