"""Canonical vocabulary for builder-authored environment programs.

Provider responses remain ordinary JSON. These types name that JSON contract so the
builder schema, validator, rule runtime, and presentation adapters share one readable
vocabulary without introducing scenario-specific mechanics.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypeAlias, TypedDict

Scalar: TypeAlias = bool | int | float | str | None
Coordinate: TypeAlias = list[int]
Direction: TypeAlias = Literal["UP", "RIGHT", "DOWN", "LEFT"]
ParameterType: TypeAlias = Literal["direction", "entity", "number", "string"]


class AllCondition(TypedDict):
    operation: Literal["all"]
    conditions: list[Condition]


class AnyCondition(TypedDict):
    operation: Literal["any"]
    conditions: list[Condition]


class NotCondition(TypedDict):
    operation: Literal["not"]
    condition: Condition


class AtCondition(TypedDict):
    operation: Literal["at"]
    first: str
    second: str


class AdjacentCondition(TypedDict):
    operation: Literal["adjacent"]
    first: str
    second: str
    direction: NotRequired[str]


class CanMoveCondition(TypedDict):
    operation: Literal["can_move"]
    entity: str
    direction: str


class PropertyEqualsCondition(TypedDict):
    operation: Literal["property_equals"]
    entity: str
    property: str
    value: Scalar


class ValueCompareCondition(TypedDict):
    operation: Literal["value_compare"]
    value: str
    comparator: Literal["eq", "ne", "lt", "lte", "gt", "gte"]
    expected: int | float | str


class EventOccurredCondition(TypedDict):
    operation: Literal["event_occurred"]
    event: str
    scope: Literal["current_step", "episode"]
    target: NotRequired[str]


Condition: TypeAlias = (
    AllCondition
    | AnyCondition
    | NotCondition
    | AtCondition
    | AdjacentCondition
    | CanMoveCondition
    | PropertyEqualsCondition
    | ValueCompareCondition
    | EventOccurredCondition
)


class MoveEffect(TypedDict):
    operation: Literal["move"]
    entity: str
    direction: str


class MoveTowardEffect(TypedDict):
    operation: Literal["move_toward"]
    entity: str
    target: str


class SetPositionEffect(TypedDict):
    operation: Literal["set_position"]
    entity: str
    destination: str | Coordinate | None


class SetPropertyEffect(TypedDict):
    operation: Literal["set_property"]
    entity: str
    property: str
    value: Scalar


class SetValueEffect(TypedDict):
    operation: Literal["set_value"]
    value: str
    new_value: Scalar


class ChangeValueEffect(TypedDict):
    operation: Literal["change_value"]
    value: str
    amount: int | float | str


class EmitEffect(TypedDict):
    operation: Literal["emit"]
    event: str
    target: NotRequired[str]


NonRepeatEffect: TypeAlias = (
    MoveEffect
    | MoveTowardEffect
    | SetPositionEffect
    | SetPropertyEffect
    | SetValueEffect
    | ChangeValueEffect
    | EmitEffect
)


RepeatEffect = TypedDict(
    "RepeatEffect",
    {
        "operation": Literal["repeat"],
        "while": Condition,
        "effects": list[NonRepeatEffect],
    },
)


Effect: TypeAlias = NonRepeatEffect | RepeatEffect


class EntityDeclaration(TypedDict):
    id: str
    properties: dict[str, Scalar]


class ActionRule(TypedDict):
    name: str
    parameters: dict[str, ParameterType]
    allowed_when: list[Condition]
    effects: list[Effect]


class AfterActionRule(TypedDict):
    id: str
    when: list[Condition]
    effects: list[Effect]


class ObjectiveRule(TypedDict):
    id: str
    description: str
    satisfied_when: Condition


class FailureRule(TypedDict):
    id: str
    description: str
    when: Condition


class ActionInvocation(TypedDict):
    action: str
    arguments: dict[str, Scalar]


class EnvironmentProgram(TypedDict):
    actor: str
    map: list[str]
    legend: dict[str, EntityDeclaration]
    values: dict[str, Scalar]
    actions: list[ActionRule]
    after_action: list[AfterActionRule]
    objectives: list[ObjectiveRule]
    failures: list[FailureRule]
