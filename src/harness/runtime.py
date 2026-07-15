from __future__ import annotations

from dataclasses import dataclass, field, replace
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


class UnusableActorOutputError(ValueError):
    """The actor response does not invoke a generated action with valid arguments."""


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
class _TurnExecution:
    previous: RuntimeState
    positions: dict[str, tuple[int, int] | None]
    properties: dict[str, dict[str, Any]]
    values: dict[str, Any]
    current_events: list[EventRecord]
    episode_events: list[EventRecord]
    applications: int = 0
    states: list[RuntimeState] = field(default_factory=list)

    @classmethod
    def from_state(cls, state: RuntimeState) -> _TurnExecution:
        return cls(
            previous=state,
            positions=dict(state.positions),
            properties={key: dict(value) for key, value in state.properties.items()},
            values=dict(state.values),
            current_events=[],
            episode_events=list(state.episode_events),
        )

    @property
    def step_number(self) -> int:
        return self.previous.step + 1

    def snapshot(self) -> RuntimeState:
        return RuntimeState(
            positions=dict(self.positions),
            properties={key: dict(value) for key, value in self.properties.items()},
            values=dict(self.values),
            completed_objectives=self.previous.completed_objectives,
            current_step_events=tuple(self.current_events),
            episode_events=tuple(self.episode_events),
            step=self.step_number,
            status="running",
            failure_id=None,
        )

    def record_effect(self) -> None:
        self.states.append(self.snapshot())


def start(environment: FrozenEnvironment) -> Transition:
    program = cast(JsonObject, environment.program)
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
    program = cast(JsonObject, environment.program)
    action = _matching_action(program, invocation)
    arguments = invocation["arguments"]
    applicable = all(
        _condition(program, state, condition, arguments) for condition in action["allowed_when"]
    )
    execution = _TurnExecution.from_state(state)
    if applicable:
        _apply_effects(program, execution, action["effects"], arguments)
    direct_effect_count = len(execution.states)
    _apply_after_action_rules(program, execution)
    next_state = _finish_turn(program, execution.snapshot())
    outcome = _transition_outcome(next_state.status, applicable)
    return Transition(
        next_state,
        _observation(program, next_state, outcome),
        applicable,
        outcome,
        tuple(execution.states),
        tuple(execution.states[:direct_effect_count]),
        tuple(execution.states[direct_effect_count:]),
    )


def _apply_effects(
    program: JsonObject,
    execution: _TurnExecution,
    effects: list[JsonObject],
    arguments: Mapping[str, Any],
) -> None:
    for effect in effects:
        _effect(program, execution, effect, arguments)


def _apply_after_action_rules(program: JsonObject, execution: _TurnExecution) -> None:
    for rule in program["after_action"]:
        provisional = execution.snapshot()
        if all(_condition(program, provisional, condition, {}) for condition in rule["when"]):
            _apply_effects(program, execution, rule["effects"], {})


def _finish_turn(program: JsonObject, state: RuntimeState) -> RuntimeState:
    _validate_runtime_state(program, state)
    failure_id = next(
        (
            failure["id"]
            for failure in program["failures"]
            if _condition(program, state, failure["when"], {})
        ),
        None,
    )
    completed = list(state.completed_objectives)
    if failure_id is None:
        for objective in program["objectives"][len(completed) :]:
            if not _condition(program, state, objective["satisfied_when"], {}):
                break
            completed.append(objective["id"])
    if failure_id is not None:
        status: RuntimeStatus = "failure"
    elif len(completed) == len(program["objectives"]):
        status = "success"
    else:
        status = "running"
    return replace(
        state,
        completed_objectives=tuple(completed),
        status=status,
        failure_id=failure_id,
    )


def _transition_outcome(status: RuntimeStatus, applicable: bool) -> TransitionOutcome:
    if status == "success":
        return "success"
    if status == "failure":
        return "failure"
    return "applied" if applicable else "inapplicable"


def _matching_action(program: JsonObject, invocation: Mapping[str, Any]) -> JsonObject:
    if set(invocation) != {"action", "arguments"} or not isinstance(invocation["arguments"], dict):
        raise UnusableActorOutputError("action invocation must contain action and arguments")
    matches = [action for action in program["actions"] if action["name"] == invocation["action"]]
    if not matches:
        raise UnusableActorOutputError(f"unknown generated action: {invocation['action']!r}")
    action = matches[0]
    arguments = invocation["arguments"]
    if set(arguments) != set(action["parameters"]):
        raise UnusableActorOutputError("action arguments do not match generated parameters")
    for name, kind in action["parameters"].items():
        value = arguments[name]
        if kind == "direction" and value not in DIRECTIONS:
            raise UnusableActorOutputError(f"argument {name!r} must be a direction")
        if kind == "entity" and (not isinstance(value, str) or value not in _entity_ids(program)):
            raise UnusableActorOutputError(f"argument {name!r} must name a declared entity")
        if kind == "number" and type(value) not in {int, float}:
            raise UnusableActorOutputError(f"argument {name!r} must be a number")
        if kind == "string" and not isinstance(value, str):
            raise UnusableActorOutputError(f"argument {name!r} must be a string")
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
    if operation == "event_occurred":
        events = (
            state.current_step_events
            if condition["scope"] == "current_step"
            else state.episode_events
        )
        target = _resolve(condition["target"], arguments) if "target" in condition else None
        return any(
            record.event == condition["event"]
            and ("target" not in condition or record.target == target)
            for record in events
        )
    if operation == "value_compare":
        actual = state.values[condition["value"]]
        expected = _resolve(condition["expected"], arguments) if isinstance(condition["expected"], str) else condition["expected"]
        actual_number = cast(float, actual)
        expected_number = cast(float, expected)
        comparator = condition["comparator"]
        if comparator == "eq":
            return actual_number == expected_number
        if comparator == "ne":
            return actual_number != expected_number
        if comparator == "lt":
            return actual_number < expected_number
        if comparator == "lte":
            return actual_number <= expected_number
        if comparator == "gt":
            return actual_number > expected_number
        if comparator == "gte":
            return actual_number >= expected_number
    raise EnvironmentProgramError(f"unsupported condition operation: {operation!r}")


def _effect(
    program: JsonObject,
    execution: _TurnExecution,
    effect: Mapping[str, Any],
    arguments: Mapping[str, Any],
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
            execution.snapshot(),
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
                    execution,
                    child,
                    arguments,
                    inside_repeat=True,
                )
        return
    if operation == "move":
        entity = _resolve(effect["entity"], arguments)
        direction = _resolve(effect["direction"], arguments)
        if not _can_move(program, execution.positions, execution.properties, entity, direction):
            raise EnvironmentProgramError("move effect would create invalid state")
        x, y = execution.positions[entity] or (0, 0)
        dx, dy = DIRECTIONS[direction]
        execution.positions[entity] = (x + dx, y + dy)
        execution.record_effect()
        return
    if operation == "move_toward":
        entity = _resolve(effect["entity"], arguments)
        target = _resolve(effect["target"], arguments)
        next_position = _shortest_path_step(
            program,
            execution.positions,
            execution.properties,
            entity,
            target,
        )
        if next_position is not None:
            execution.positions[entity] = next_position
        execution.record_effect()
        return
    if operation == "set_position":
        entity = _resolve(effect["entity"], arguments)
        destination = effect["destination"]
        if isinstance(destination, list):
            execution.positions[entity] = (destination[0], destination[1])
        elif isinstance(destination, str):
            destination_entity = _resolve(destination, arguments)
            execution.positions[entity] = execution.positions[destination_entity]
        else:
            execution.positions[entity] = None
        execution.record_effect()
        return
    if operation == "set_property":
        entity = _resolve(effect["entity"], arguments)
        property_name = effect["property"]
        if property_name not in execution.properties[entity]:
            raise EnvironmentProgramError(f"unknown property {property_name!r} on entity {entity!r}")
        value = _resolve(effect["value"], arguments) if isinstance(effect["value"], str) else effect["value"]
        execution.properties[entity][property_name] = value
        execution.record_effect()
        return
    if operation == "set_value":
        value_id = effect["value"]
        execution.values[value_id] = (
            _resolve(effect["new_value"], arguments)
            if isinstance(effect["new_value"], str)
            else effect["new_value"]
        )
        execution.record_effect()
        return
    if operation == "change_value":
        value_id = effect["value"]
        amount = _resolve(effect["amount"], arguments) if isinstance(effect["amount"], str) else effect["amount"]
        execution.values[value_id] += amount
        execution.record_effect()
        return
    if operation == "emit":
        target = _resolve(effect["target"], arguments) if "target" in effect else None
        event = EventRecord(effect["event"], target, execution.step_number)
        execution.current_events.append(event)
        execution.episode_events.append(event)
        execution.record_effect()
        return
    raise EnvironmentProgramError(f"unsupported effect operation: {operation!r}")


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
