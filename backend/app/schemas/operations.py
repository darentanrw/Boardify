"""Operation schemas and discriminated operation union."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.primitives import Condition, ValueRef


class OperationModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SpawnFromManifestOp(OperationModel):
    op: Literal["spawn_from_manifest"] = "spawn_from_manifest"
    manifest: str = Field(..., description="Manifest key under assets.deck_manifest.")
    dest: str = Field(..., description="Destination zone name.")


class ShuffleOp(OperationModel):
    op: Literal["shuffle"] = "shuffle"
    zone: str = Field(..., description="Zone to shuffle.")


class DealOp(OperationModel):
    op: Literal["deal"] = "deal"
    from_: str = Field(..., alias="from", description="Source zone.")
    count: int | str = Field(..., description="Cards to deal per recipient.")
    to: str = Field(
        ...,
        description="Recipient zone or special target (e.g. all_players).",
    )
    filter: dict[str, ValueRef] | None = Field(
        None,
        description="Optional filter map to constrain dealt cards.",
    )


class MoveOp(OperationModel):
    op: Literal["move"] = "move"
    entity: str | None = Field(
        None,
        description="Card/card-set reference, e.g. $card or $cards.",
    )
    from_: str | None = Field(
        None,
        alias="from",
        description="Source zone reference when entity is omitted.",
    )
    to: str = Field(..., description="Destination zone/reference.")
    count: int | str | None = Field(
        None,
        description="Number of cards to move when using from/to form.",
    )
    random: bool = Field(
        False,
        description="Whether selected cards are chosen randomly from source.",
    )
    store_as: str | None = Field(
        None,
        description="Store moved card(s) under $args.{store_as}.",
    )


class MoveAllExceptTopOp(OperationModel):
    op: Literal["move_all_except_top"] = "move_all_except_top"
    from_: str = Field(..., alias="from", description="Source zone.")
    to: str = Field(..., description="Destination zone.")


class SetGlobalOp(OperationModel):
    op: Literal["set_global"] = "set_global"
    key: str = Field(..., description="Global variable key.")
    value: ValueRef = Field(..., description="Value assigned to global variable.")


class SetPlayerVarOp(OperationModel):
    op: Literal["set_player_var"] = "set_player_var"
    key: str = Field(..., description="Per-player variable key.")
    value: ValueRef = Field(..., description="Value assigned to player variable.")
    player: str | None = Field(
        None,
        description="Optional player reference. Defaults to current player.",
    )


class MutateGlobalOp(OperationModel):
    op: Literal["mutate_global"] = "mutate_global"
    key: str = Field(..., description="Global variable key.")
    mutation: Literal["add", "subtract", "multiply", "divide", "negate"] = Field(
        ...,
        description="Arithmetic mutation type.",
    )
    operand: int | float | str | None = Field(
        None,
        description="Optional operand used by non-negate mutations.",
    )


class MutatePlayerVarOp(OperationModel):
    op: Literal["mutate_player_var"] = "mutate_player_var"
    key: str = Field(..., description="Per-player variable key.")
    mutation: Literal["add", "subtract", "multiply", "divide", "negate"] = Field(
        ...,
        description="Arithmetic mutation type.",
    )
    operand: int | float | str | None = Field(
        None,
        description="Optional operand used by non-negate mutations.",
    )
    player: str | None = Field(
        None,
        description="Optional player reference. Defaults to current player.",
    )


class BranchOp(OperationModel):
    op: Literal["branch"] = "branch"
    condition: Condition = Field(..., description="Condition tree.")
    if_true: list["Operation"] = Field(..., description="Operations when condition is true.")
    if_false: list["Operation"] = Field(
        default_factory=list,
        description="Operations when condition is false.",
    )


class AdvanceTurnOp(OperationModel):
    op: Literal["advance_turn"] = "advance_turn"
    skip: int = Field(
        0,
        ge=0,
        description="How many additional players to skip after advancing.",
    )


class TransitionPhaseOp(OperationModel):
    op: Literal["transition_phase"] = "transition_phase"
    to: str = Field(..., description="Target phase name.")


class TriggerRoutineOp(OperationModel):
    op: Literal["trigger_routine"] = "trigger_routine"
    name: str = Field(..., description="Routine name.")
    args: dict[str, ValueRef] = Field(
        default_factory=dict,
        description="Optional routine arguments stored in $args context.",
    )


class PromptOp(OperationModel):
    op: Literal["prompt"] = "prompt"
    player: str = Field(..., description="Player reference being prompted.")
    kind: Literal[
        "choose_option",
        "choose_card",
        "choose_number",
        "choose_zone",
        "text_input",
    ] = Field(..., description="Prompt UI kind.")
    options: list[ValueRef] | None = Field(
        None,
        description="Selectable options when kind is choose_option.",
    )
    message: str | None = Field(None, description="Prompt message for UI.")
    store_as: str | None = Field(None, description="Store response under $args.{store_as}.")
    min: int | None = Field(None, description="Optional lower bound for numeric prompts.")
    max: int | None = Field(None, description="Optional upper bound for numeric prompts.")


class GameOverOp(OperationModel):
    op: Literal["game_over"] = "game_over"
    winner: str | list[str] = Field(..., description="Winner player reference(s).")
    reason: str | None = Field(None, description="Optional game-over reason.")


class LogOp(OperationModel):
    op: Literal["log"] = "log"
    message: str = Field(..., description="Message emitted to logs/UI.")
    level: Literal["debug", "info", "warning", "error"] = Field(
        "info",
        description="Log severity level.",
    )


class RevealOp(OperationModel):
    op: Literal["reveal"] = "reveal"
    zone: str = Field(..., description="Zone to reveal cards from.")
    count: int | str = Field(1, description="Number of cards to reveal.")
    to_player: str | None = Field(
        None,
        description="Optional specific viewer; omitted means reveal to all.",
    )
    store_as: str | None = Field(None, description="Store revealed cards under $args.")


class EvaluateHandOp(OperationModel):
    op: Literal["evaluate_hand"] = "evaluate_hand"
    player: str = Field(..., description="Player whose hand is evaluated.")
    zone: str | None = Field(
        None,
        description="Zone to evaluate; defaults to the player's hand.",
    )
    rule_set: str = Field(..., description="Evaluation ruleset key, e.g. poker_standard.")
    store_as: str = Field(..., description="Store evaluation result under $args.")


class CompareHandsOp(OperationModel):
    op: Literal["compare_hands"] = "compare_hands"
    left: str = Field(..., description="Left hand score/reference.")
    right: str = Field(..., description="Right hand score/reference.")
    store_as: str = Field(..., description="Store comparison result under $args.")


class AddScoreOp(OperationModel):
    op: Literal["add_score"] = "add_score"
    player: str = Field(..., description="Player receiving score mutation.")
    amount: int | str = Field(..., description="Points to add (or subtract if negative).")


class CollectToPotOp(OperationModel):
    op: Literal["collect_to_pot"] = "collect_to_pot"
    player: str = Field(..., description="Player paying into the pot.")
    amount: int | str = Field(..., description="Amount collected from the player.")
    pot_key: str = Field("pot", description="Global variable key tracking the pot.")


class AwardPotOp(OperationModel):
    op: Literal["award_pot"] = "award_pot"
    player: str = Field(..., description="Player awarded the pot.")
    pot_key: str = Field("pot", description="Global variable key tracking the pot.")


class ForEachPlayerOp(OperationModel):
    op: Literal["for_each_player"] = "for_each_player"
    include_eliminated: bool = Field(
        False,
        description="Whether eliminated players are included.",
    )
    store_as: str | None = Field(
        None,
        description="Store loop player reference under $args.{store_as}.",
    )
    sequence: list["Operation"] = Field(..., description="Operations run for each player.")


class CheckGroupOp(OperationModel):
    op: Literal["check_group"] = "check_group"
    zone: str = Field(..., description="Zone containing candidate cards.")
    rule: Literal["set", "run", "n_of_a_kind", "all_different", "custom"] = Field(
        ...,
        description="Grouping rule to evaluate.",
    )
    count: int | None = Field(None, ge=1, description="Optional exact/target group size.")
    store_as: str = Field(..., description="Store boolean/result under $args.")
    field: str | None = Field(
        None,
        description="Optional card field path used by set/different checks.",
    )


class PeekOp(OperationModel):
    op: Literal["peek"] = "peek"
    zone: str = Field(..., description="Zone to inspect.")
    count: int = Field(1, ge=1, description="How many top cards to inspect.")
    store_as: str | None = Field(
        None,
        description="Optional $args key to store inspected cards.",
    )


class InsertAtOp(OperationModel):
    op: Literal["insert_at"] = "insert_at"
    entity: str = Field(..., description="Card/card-set reference to insert.")
    zone: str = Field(..., description="Destination zone.")
    position: int | Literal["top", "bottom", "player_choice"] | str = Field(
        ...,
        description="Insert position index or symbolic position.",
    )


class ChoosePlayerOp(OperationModel):
    op: Literal["choose_player"] = "choose_player"
    player: str = Field(..., description="Player making the selection.")
    message: str = Field(..., description="Prompt message.")
    exclude_self: bool = Field(
        True,
        description="Whether acting player is excluded from choices.",
    )
    store_as: str = Field(..., description="Store selected player under $args.")


class EliminatePlayerOp(OperationModel):
    op: Literal["eliminate_player"] = "eliminate_player"
    player: str = Field(..., description="Player to eliminate.")
    reason: str | None = Field(None, description="Optional elimination reason.")


class ChooseFromZoneOp(OperationModel):
    op: Literal["choose_from_zone"] = "choose_from_zone"
    player: str = Field(..., description="Player making the selection.")
    zone: str = Field(..., description="Zone cards can be chosen from.")
    message: str = Field(..., description="Prompt message.")
    count: int = Field(1, ge=1, description="Number of cards to choose.")
    store_as: str = Field(..., description="Store selected card(s) under $args.")


Operation = Annotated[
    Union[
        SpawnFromManifestOp,
        ShuffleOp,
        DealOp,
        MoveOp,
        MoveAllExceptTopOp,
        SetGlobalOp,
        SetPlayerVarOp,
        MutateGlobalOp,
        MutatePlayerVarOp,
        BranchOp,
        AdvanceTurnOp,
        TransitionPhaseOp,
        TriggerRoutineOp,
        PromptOp,
        GameOverOp,
        LogOp,
        RevealOp,
        EvaluateHandOp,
        CompareHandsOp,
        AddScoreOp,
        CollectToPotOp,
        AwardPotOp,
        ForEachPlayerOp,
        CheckGroupOp,
        PeekOp,
        InsertAtOp,
        ChoosePlayerOp,
        EliminatePlayerOp,
        ChooseFromZoneOp,
    ],
    Field(discriminator="op"),
]

BranchOp.model_rebuild()
ForEachPlayerOp.model_rebuild()
