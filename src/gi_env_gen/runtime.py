from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, TypeAlias, cast

from .model import FrozenEnvironment, JsonObject

DIRECTIONS = {
    "UP": (0, -1),
    "RIGHT": (1, 0),
    "DOWN": (0, 1),
    "LEFT": (-1, 0),
}


RuntimeStatus: TypeAlias = Literal["running", "success", "failure"]
TransitionOutcome: TypeAlias = Literal["started", "applied", "inapplicable", "success"]


class EnvironmentProgramError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeState:
    positions: Mapping[str, tuple[int, int] | None]
    properties: Mapping[str, Mapping[str, Any]]
    values: Mapping[str, Any]
    completed_objectives: tuple[str, ...]
    current_step_events: tuple[object, ...]
    episode_events: tuple[object, ...]
    step: int
    status: RuntimeStatus
    failure_id: str | None


@dataclass(frozen=True)
class Transition:
    state: RuntimeState
    observation: JsonObject
    applicable: bool | None
    outcome: TransitionOutcome


def start(environment: FrozenEnvironment) -> Transition:
    program = environment.program
    positions: dict[str, tuple[int, int] | None] = {}
    properties: dict[str, Mapping[str, Any]] = {}
    for y, row in enumerate(program["map"]):
        for x, token in enumerate(row):
            if token in program["legend"]:
                declaration = program["legend"][token]
                positions[declaration["id"]] = (x, y)
                properties[declaration["id"]] = dict(declaration["properties"])
    state = RuntimeState(
        positions=positions,
        properties=properties,
        values=dict(program["values"]),
        completed_objectives=(),
        current_step_events=(),
        episode_events=(),
        step=0,
        status="running",
        failure_id=None,
    )
    return Transition(state, _observation(program, state, None), None, "started")


def step(
    environment: FrozenEnvironment,
    state: RuntimeState,
    invocation: Mapping[str, Any],
) -> Transition:
    if state.status != "running":
        raise EnvironmentProgramError("cannot step a terminal runtime state")
    program = environment.program
    action = _matching_action(program, invocation)
    arguments = invocation["arguments"]
    applicable = all(
        _condition(program, state, condition, arguments) for condition in action["allowed_when"]
    )
    positions = dict(state.positions)
    if applicable:
        for effect in action["effects"]:
            _effect(program, state, positions, effect, arguments)
    next_state = RuntimeState(
        positions=positions,
        properties={key: dict(value) for key, value in state.properties.items()},
        values=dict(state.values),
        completed_objectives=state.completed_objectives,
        current_step_events=(),
        episode_events=state.episode_events,
        step=state.step + 1,
        status="running",
        failure_id=None,
    )
    completed = list(next_state.completed_objectives)
    for objective in program["objectives"][len(completed) :]:
        if not _condition(program, next_state, objective["satisfied_when"], {}):
            break
        completed.append(objective["id"])
    status = "success" if len(completed) == len(program["objectives"]) else "running"
    next_state = RuntimeState(
        **{**next_state.__dict__, "completed_objectives": tuple(completed), "status": status}
    )
    outcome: TransitionOutcome = "success" if status == "success" else ("applied" if applicable else "inapplicable")
    return Transition(next_state, _observation(program, next_state, outcome), applicable, outcome)


def _matching_action(program: JsonObject, invocation: Mapping[str, Any]) -> JsonObject:
    if set(invocation) != {"action", "arguments"} or not isinstance(invocation["arguments"], dict):
        raise EnvironmentProgramError("action invocation must contain action and arguments")
    matches = [action for action in program["actions"] if action["name"] == invocation["action"]]
    if not matches:
        raise EnvironmentProgramError(f"unknown generated action: {invocation['action']!r}")
    action = matches[0]
    arguments = invocation["arguments"]
    if set(arguments) != set(action["parameters"]):
        raise EnvironmentProgramError("action arguments do not match generated parameters")
    for name, kind in action["parameters"].items():
        value = arguments[name]
        if kind == "direction" and value not in DIRECTIONS:
            raise EnvironmentProgramError(f"argument {name!r} must be a direction")
        if kind != "direction":
            raise EnvironmentProgramError(f"unsupported parameter type in minimal runtime: {kind!r}")
    return cast(JsonObject, action)


def _resolve(reference: str, arguments: Mapping[str, Any]) -> Any:
    return arguments[reference[1:]] if reference.startswith("$") else reference


def _condition(
    program: JsonObject,
    state: RuntimeState,
    condition: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> bool:
    operation = condition["operation"]
    if operation == "at":
        first = _resolve(condition["first"], arguments)
        second = _resolve(condition["second"], arguments)
        return state.positions[first] is not None and state.positions[first] == state.positions[second]
    if operation == "can_move":
        entity = _resolve(condition["entity"], arguments)
        direction = _resolve(condition["direction"], arguments)
        return _can_move(program, state.positions, state.properties, entity, direction)
    raise EnvironmentProgramError(f"unsupported condition operation: {operation!r}")


def _effect(
    program: JsonObject,
    state: RuntimeState,
    positions: dict[str, tuple[int, int] | None],
    effect: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> None:
    if effect["operation"] != "move":
        raise EnvironmentProgramError(f"unsupported effect operation: {effect['operation']!r}")
    entity = _resolve(effect["entity"], arguments)
    direction = _resolve(effect["direction"], arguments)
    if not _can_move(program, positions, state.properties, entity, direction):
        raise EnvironmentProgramError("move effect would create invalid state")
    x, y = positions[entity] or (0, 0)
    dx, dy = DIRECTIONS[direction]
    positions[entity] = (x + dx, y + dy)


def _can_move(
    program: JsonObject,
    positions: Mapping[str, tuple[int, int] | None],
    properties: Mapping[str, Mapping[str, Any]],
    entity: str,
    direction: str,
) -> bool:
    position = positions[entity]
    if position is None or direction not in DIRECTIONS:
        return False
    dx, dy = DIRECTIONS[direction]
    destination = (position[0] + dx, position[1] + dy)
    width, height = len(program["map"][0]), len(program["map"])
    if not (0 <= destination[0] < width and 0 <= destination[1] < height):
        return False
    if program["map"][destination[1]][destination[0]] == "#":
        return False
    return not any(
        other != entity and other_position == destination and properties[other]["solid"] is True
        for other, other_position in positions.items()
    )


def _observation(
    program: JsonObject,
    state: RuntimeState,
    previous_outcome: TransitionOutcome | None,
) -> JsonObject:
    rendered = [list(row) for row in program["map"]]
    for token in program["legend"]:
        for row in rendered:
            for index, value in enumerate(row):
                if value == token:
                    row[index] = "."
    for entity, position in state.positions.items():
        if position is not None:
            rendered[position[1]][position[0]] = state.properties[entity]["symbol"]
    completed = set(state.completed_objectives)
    current_index = len(completed)
    return {
        "map": ["".join(row) for row in rendered],
        "entities": [
            {"id": entity, "position": position, "properties": dict(state.properties[entity])}
            for entity, position in state.positions.items()
        ],
        "values": dict(state.values),
        "available_actions": program["actions"],
        "objectives": [
            {
                "id": objective["id"],
                "description": objective["description"],
                "status": (
                    "complete"
                    if objective["id"] in completed
                    else "current"
                    if index == current_index
                    else "pending"
                ),
            }
            for index, objective in enumerate(program["objectives"])
        ],
        "failures": [],
        "previous_outcome": previous_outcome,
        "step": state.step,
    }
