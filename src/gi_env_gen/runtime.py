from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, TypeAlias, cast

from .model import FrozenEnvironment, JsonObject

DIRECTIONS = {
    "UP": (0, -1),
    "RIGHT": (1, 0),
    "DOWN": (0, 1),
    "LEFT": (-1, 0),
}


RuntimeStatus: TypeAlias = Literal["running", "success", "failure"]
TransitionOutcome: TypeAlias = Literal["started", "applied", "inapplicable", "success", "failure"]


class EnvironmentProgramError(ValueError):
    pass


class EffectLimitExceeded(EnvironmentProgramError):
    pass


@dataclass(frozen=True)
class EventRecord:
    event: str
    target: str | None
    step: int


@dataclass(frozen=True)
class RuntimeState:
    positions: Mapping[str, tuple[int, int] | None]
    properties: Mapping[str, Mapping[str, Any]]
    values: Mapping[str, Any]
    completed_objectives: tuple[str, ...]
    current_step_events: tuple[EventRecord, ...]
    episode_events: tuple[EventRecord, ...]
    step: int
    status: RuntimeStatus
    failure_id: str | None


@dataclass(frozen=True)
class Transition:
    state: RuntimeState
    observation: JsonObject
    applicable: bool | None
    outcome: TransitionOutcome
    effect_states: tuple[RuntimeState, ...] = ()
    direct_effect_states: tuple[RuntimeState, ...] = ()
    automatic_effect_states: tuple[RuntimeState, ...] = ()


@dataclass
class _EffectExecution:
    applications: int = 0
    states: list[RuntimeState] = field(default_factory=list)


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
    properties = {key: dict(value) for key, value in state.properties.items()}
    current_events: list[EventRecord] = []
    episode_events = list(state.episode_events)
    execution = _EffectExecution()
    if applicable:
        for effect in action["effects"]:
            _effect(
                program,
                state,
                positions,
                properties,
                current_events,
                episode_events,
                state.step + 1,
                effect,
                arguments,
                execution,
            )
    direct_effect_count = len(execution.states)
    for rule in program["after_action"]:
        provisional = _state_after_effects(state, positions, properties, current_events, episode_events)
        if all(_condition(program, provisional, condition, {}) for condition in rule["when"]):
            for effect in rule["effects"]:
                _effect(
                    program,
                    state,
                    positions,
                    properties,
                    current_events,
                    episode_events,
                    state.step + 1,
                    effect,
                    {},
                    execution,
                )
    next_state = RuntimeState(
        positions=dict(positions),
        properties={key: dict(value) for key, value in properties.items()},
        values=dict(state.values),
        completed_objectives=state.completed_objectives,
        current_step_events=tuple(current_events),
        episode_events=tuple(episode_events),
        step=state.step + 1,
        status="running",
        failure_id=None,
    )
    _validate_runtime_state(program, next_state)
    failure_id = next(
        (
            failure["id"]
            for failure in program["failures"]
            if _condition(program, next_state, failure["when"], {})
        ),
        None,
    )
    completed = list(next_state.completed_objectives)
    if failure_id is None:
        for objective in program["objectives"][len(completed) :]:
            if not _condition(program, next_state, objective["satisfied_when"], {}):
                break
            completed.append(objective["id"])
    status: RuntimeStatus = (
        "failure"
        if failure_id is not None
        else "success"
        if len(completed) == len(program["objectives"])
        else "running"
    )
    next_state = RuntimeState(
        **{
            **next_state.__dict__,
            "completed_objectives": tuple(completed),
            "status": status,
            "failure_id": failure_id,
        }
    )
    outcome: TransitionOutcome = (
        status if status in {"success", "failure"} else ("applied" if applicable else "inapplicable")
    )
    return Transition(
        next_state,
        _observation(program, next_state, outcome),
        applicable,
        outcome,
        tuple(execution.states),
        tuple(execution.states[:direct_effect_count]),
        tuple(execution.states[direct_effect_count:]),
    )


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
        if kind == "entity" and (not isinstance(value, str) or value not in _entity_ids(program)):
            raise EnvironmentProgramError(f"argument {name!r} must name a declared entity")
        if kind not in {"direction", "entity"}:
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
    if operation == "all":
        return all(_condition(program, state, child, arguments) for child in condition["conditions"])
    if operation == "any":
        return any(_condition(program, state, child, arguments) for child in condition["conditions"])
    if operation == "not":
        return not _condition(program, state, condition["condition"], arguments)
    if operation == "at":
        first = _resolve(condition["first"], arguments)
        second = _resolve(condition["second"], arguments)
        return state.positions[first] is not None and state.positions[first] == state.positions[second]
    if operation == "can_move":
        entity = _resolve(condition["entity"], arguments)
        direction = _resolve(condition["direction"], arguments)
        return _can_move(program, state.positions, state.properties, entity, direction)
    if operation == "adjacent":
        first = _resolve(condition["first"], arguments)
        second = _resolve(condition["second"], arguments)
        first_position = state.positions[first]
        second_position = state.positions[second]
        if first_position is None or second_position is None:
            return False
        dx = second_position[0] - first_position[0]
        dy = second_position[1] - first_position[1]
        if abs(dx) + abs(dy) != 1:
            return False
        if "direction" not in condition:
            return True
        direction = _resolve(condition["direction"], arguments)
        return DIRECTIONS.get(direction) == (dx, dy)
    if operation == "property_equals":
        entity = _resolve(condition["entity"], arguments)
        value = _resolve(condition["value"], arguments) if isinstance(condition["value"], str) else condition["value"]
        return condition["property"] in state.properties[entity] and state.properties[entity][condition["property"]] == value
    raise EnvironmentProgramError(f"unsupported condition operation: {operation!r}")


def _effect(
    program: JsonObject,
    previous: RuntimeState,
    positions: dict[str, tuple[int, int] | None],
    properties: dict[str, dict[str, Any]],
    current_events: list[EventRecord],
    episode_events: list[EventRecord],
    step_number: int,
    effect: Mapping[str, Any],
    arguments: Mapping[str, Any],
    execution: _EffectExecution,
    *,
    inside_repeat: bool = False,
) -> None:
    execution.applications += 1
    if execution.applications > 100:
        raise EffectLimitExceeded("generated environment exceeded 100 effect applications in one turn")
    operation = effect["operation"]
    if operation == "repeat":
        if inside_repeat:
            raise EnvironmentProgramError("nested repeat is invalid")
        while _condition(
            program,
            _state_after_effects(previous, positions, properties, current_events, episode_events),
            effect["while"],
            arguments,
        ):
            if not effect["effects"]:
                raise EffectLimitExceeded(
                    "generated environment repeat cannot make progress within 100 effect applications"
                )
            for child in effect["effects"]:
                _effect(
                    program,
                    previous,
                    positions,
                    properties,
                    current_events,
                    episode_events,
                    step_number,
                    child,
                    arguments,
                    execution,
                    inside_repeat=True,
                )
        return
    if operation == "move":
        entity = _resolve(effect["entity"], arguments)
        direction = _resolve(effect["direction"], arguments)
        if not _can_move(program, positions, properties, entity, direction):
            raise EnvironmentProgramError("move effect would create invalid state")
        x, y = positions[entity] or (0, 0)
        dx, dy = DIRECTIONS[direction]
        positions[entity] = (x + dx, y + dy)
        _record_effect_state(previous, positions, properties, current_events, episode_events, execution)
        return
    if operation == "move_toward":
        entity = _resolve(effect["entity"], arguments)
        target = _resolve(effect["target"], arguments)
        next_position = _shortest_path_step(program, positions, properties, entity, target)
        if next_position is not None:
            positions[entity] = next_position
        _record_effect_state(previous, positions, properties, current_events, episode_events, execution)
        return
    if operation == "set_position":
        entity = _resolve(effect["entity"], arguments)
        destination = effect["destination"]
        if isinstance(destination, list):
            positions[entity] = (destination[0], destination[1])
        elif isinstance(destination, str):
            destination_entity = _resolve(destination, arguments)
            positions[entity] = positions[destination_entity]
        else:
            positions[entity] = None
        _record_effect_state(previous, positions, properties, current_events, episode_events, execution)
        return
    if operation == "set_property":
        entity = _resolve(effect["entity"], arguments)
        property_name = effect["property"]
        if property_name not in properties[entity]:
            raise EnvironmentProgramError(f"unknown property {property_name!r} on entity {entity!r}")
        value = _resolve(effect["value"], arguments) if isinstance(effect["value"], str) else effect["value"]
        properties[entity][property_name] = value
        _record_effect_state(previous, positions, properties, current_events, episode_events, execution)
        return
    if operation == "emit":
        target = _resolve(effect["target"], arguments) if "target" in effect else None
        event = EventRecord(effect["event"], target, step_number)
        current_events.append(event)
        episode_events.append(event)
        _record_effect_state(previous, positions, properties, current_events, episode_events, execution)
        return
    raise EnvironmentProgramError(f"unsupported effect operation: {operation!r}")


def _record_effect_state(
    previous: RuntimeState,
    positions: Mapping[str, tuple[int, int] | None],
    properties: Mapping[str, Mapping[str, Any]],
    current_events: list[EventRecord],
    episode_events: list[EventRecord],
    execution: _EffectExecution,
) -> None:
    execution.states.append(
        _state_after_effects(
            previous,
            dict(positions),
            {entity: dict(entity_properties) for entity, entity_properties in properties.items()},
            current_events,
            episode_events,
        )
    )


def _state_after_effects(
    previous: RuntimeState,
    positions: Mapping[str, tuple[int, int] | None],
    properties: Mapping[str, Mapping[str, Any]],
    current_events: list[EventRecord],
    episode_events: list[EventRecord],
) -> RuntimeState:
    return RuntimeState(
        positions=positions,
        properties=properties,
        values=previous.values,
        completed_objectives=previous.completed_objectives,
        current_step_events=tuple(current_events),
        episode_events=tuple(episode_events),
        step=previous.step + 1,
        status="running",
        failure_id=None,
    )


def _entity_ids(program: JsonObject) -> set[str]:
    return {declaration["id"] for declaration in program["legend"].values()}


def _validate_runtime_state(program: JsonObject, state: RuntimeState) -> None:
    solid_positions: set[tuple[int, int]] = set()
    width, height = len(program["map"][0]), len(program["map"])
    for entity, properties in state.properties.items():
        symbol = properties.get("symbol")
        if not isinstance(symbol, str) or len(symbol) != 1 or not 0x20 <= ord(symbol) <= 0x7E:
            raise EnvironmentProgramError(f"entity {entity!r} has an invalid symbol")
        if type(properties.get("solid")) is not bool:
            raise EnvironmentProgramError(f"entity {entity!r} has an invalid solid property")
        position = state.positions[entity]
        if position is not None:
            x, y = position
            if not (0 <= x < width and 0 <= y < height):
                raise EnvironmentProgramError(f"entity {entity!r} is outside the map")
            if program["map"][y][x] == "#":
                raise EnvironmentProgramError(f"entity {entity!r} is positioned on a wall")
        if properties["solid"] is True and position is not None:
            if position in solid_positions:
                raise EnvironmentProgramError("two solid entities cannot share a position")
            solid_positions.add(position)


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


def _shortest_path_step(
    program: JsonObject,
    positions: Mapping[str, tuple[int, int] | None],
    properties: Mapping[str, Mapping[str, Any]],
    entity: str,
    target: str,
) -> tuple[int, int] | None:
    start_position = positions[entity]
    target_position = positions[target]
    if start_position is None or target_position is None or start_position == target_position:
        return None
    width, height = len(program["map"][0]), len(program["map"])
    blocked = {
        position
        for other, position in positions.items()
        if other != entity
        and position is not None
        and properties[other]["solid"] is True
        and (other != target or properties[entity]["solid"] is True)
    }
    queue: list[tuple[tuple[int, int], tuple[int, int] | None]] = [(start_position, None)]
    visited = {start_position}
    for position, first_step in queue:
        for dx, dy in DIRECTIONS.values():
            candidate = (position[0] + dx, position[1] + dy)
            if candidate in visited or candidate in blocked:
                continue
            x, y = candidate
            if not (0 <= x < width and 0 <= y < height) or program["map"][y][x] == "#":
                continue
            candidate_first = candidate if first_step is None else first_step
            if candidate == target_position:
                return candidate_first
            visited.add(candidate)
            queue.append((candidate, candidate_first))
    return None


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
        "failures": [
            {"id": failure["id"], "description": failure["description"]}
            for failure in program["failures"]
        ],
        "previous_outcome": previous_outcome,
        "step": state.step,
    }
