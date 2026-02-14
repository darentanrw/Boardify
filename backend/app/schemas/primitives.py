"""Primitive and reusable schema building blocks."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


PrimitiveValue = str | int | float | bool | None
ValueRef = PrimitiveValue | list[PrimitiveValue] | dict[str, Any]


class PlayerCount(BaseModel):
    """Supported player range for a game."""

    model_config = ConfigDict(extra="forbid")

    min: int = Field(..., ge=1, description="Minimum player count.")
    max: int = Field(..., ge=1, description="Maximum player count.")

    @model_validator(mode="after")
    def validate_bounds(self) -> "PlayerCount":
        if self.max < self.min:
            raise ValueError("max must be >= min")
        return self


class LeafCondition(BaseModel):
    """Binary comparison condition."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["eq", "neq", "gt", "lt", "gte", "lte"]
    val1: PrimitiveValue | str = Field(
        ...,
        description="Left operand ($-reference or scalar literal).",
    )
    val2: PrimitiveValue | str = Field(
        ...,
        description="Right operand ($-reference or scalar literal).",
    )


class CompoundCondition(BaseModel):
    """Logical AND/OR over nested conditions."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["and", "or"]
    args: list["Condition"] = Field(..., min_length=2)


class NotCondition(BaseModel):
    """Logical NOT over a nested condition."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["not"]
    arg: "Condition"


class HasMatchingCondition(BaseModel):
    """Check whether a zone has enough cards matching a field."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["has_matching"]
    zone: str = Field(..., description="Zone reference, e.g. $player.hand.")
    field: str = Field(..., description="Card field path, e.g. data.type.")
    count: int = Field(..., ge=1, description="Minimum matching card count.")


class PlayerAliveCondition(BaseModel):
    """Check if a player is currently alive/in game."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["is_alive"]
    player: str = Field(..., description="Player reference.")


Condition = Annotated[
    Union[
        LeafCondition,
        CompoundCondition,
        NotCondition,
        HasMatchingCondition,
        PlayerAliveCondition,
    ],
    Field(discriminator="op"),
]

CompoundCondition.model_rebuild()
NotCondition.model_rebuild()
