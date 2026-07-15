"""Read-only projection of deterministic acting state for presentation adapters."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, cast

from .acting import ActingObserver, ActingUpdate
from .model import FrozenEnvironment, JsonObject, RunModels
from .rule_formatting import format_rule
from .runtime import EventRecord, RuntimeState, start


_ENTITY_STYLES = (
    "bright_cyan",
    "bright_magenta",
    "bright_yellow",
    "bright_green",
    "bright_blue",
    "orange3",
    "deep_sky_blue1",
    "spring_green2",
)


@dataclass(frozen=True)
class EntityView:
    id: str
    position: tuple[int, int] | None
    symbol: str
    properties: tuple[tuple[str, Any], ...]
    style: str


@dataclass(frozen=True)
class ActionView:
    name: str
    signature: str
    conditions: tuple[str, ...]
    effects: tuple[str, ...]


@dataclass(frozen=True)
class AutomaticRuleView:
    id: str
    conditions: tuple[str, ...]
    effects: tuple[str, ...]


@dataclass(frozen=True)
class ObjectiveView:
    id: str
    description: str
    status: str


@dataclass(frozen=True)
class FailureView:
    id: str
    description: str
    triggered: bool


@dataclass(frozen=True)
class DashboardFrame:
    models: RunModels
    environment_hash_prefix: str
    step: int
    max_steps: int
    status: str
    map_rows: tuple[str, ...]
    changed_cells: frozenset[tuple[int, int]]
    entities: tuple[EntityView, ...]
    actions: tuple[ActionView, ...]
    automatic_rules: tuple[AutomaticRuleView, ...]
    objectives: tuple[ObjectiveView, ...]
    failures: tuple[FailureView, ...]
    values: tuple[tuple[str, Any], ...]
    events: tuple[str, ...]
    latest_action: str | None
    latest_action_name: str | None
    latest_error: str | None
    evidence_path: str


class DashboardProjection(ActingObserver):
    """Read-only projection of frozen rules and deterministic acting updates."""

    def __init__(
        self,
        *,
        models: RunModels,
        environment: FrozenEnvironment,
        max_steps: int,
        evidence_path: Path,
    ) -> None:
        self._models = models
        self._environment_hash_prefix = environment.content_hash[:10]
        self._program = environment.program
        self._max_steps = max_steps
        self._evidence_path = str(evidence_path)
        initial = start(environment)
        self._observation = initial.observation
        self._state = initial.state
        self._status = "ready"
        self._changed_cells: frozenset[tuple[int, int]] = frozenset()
        self._latest_action: str | None = None
        self._latest_action_name: str | None = None
        self._latest_error: str | None = None

    @property
    def frame(self) -> DashboardFrame:
        entities = tuple(_entity_view(item) for item in self._observation["entities"])
        completed = set(self._state.completed_objectives)
        return DashboardFrame(
            models=self._models,
            environment_hash_prefix=self._environment_hash_prefix,
            step=self._state.step,
            max_steps=self._max_steps,
            status=self._status,
            map_rows=tuple(self._observation["map"]),
            changed_cells=self._changed_cells,
            entities=entities,
            actions=tuple(_action_view(action) for action in self._program["actions"]),
            automatic_rules=tuple(
                _automatic_rule_view(rule) for rule in self._program["after_action"]
            ),
            objectives=tuple(
                ObjectiveView(item["id"], item["description"], item["status"])
                for item in self._observation["objectives"]
            ),
            failures=tuple(
                FailureView(
                    item["id"],
                    item["description"],
                    item["id"] == self._state.failure_id,
                )
                for item in self._observation["failures"]
            ),
            values=tuple(self._state.values.items()),
            events=tuple(_event_label(event) for event in self._state.episode_events[-5:]),
            latest_action=self._latest_action,
            latest_action_name=self._latest_action_name,
            latest_error=self._latest_error,
            evidence_path=self._evidence_path,
        )

    def on_acting_update(self, update: ActingUpdate) -> None:
        previous_map = tuple(self._observation["map"])
        previous_state = self._state
        self._observation = update.observation
        self._state = update.state
        if update.phase == "before_actor_request":
            self._status = "waiting for actor"
            self._changed_cells = frozenset()
        elif update.phase == "after_response_attempt":
            self._status = "checking response"
            self._latest_action = _invocation_label(update.response)
            self._latest_action_name = _invocation_name(update.action)
            self._latest_error = update.error
        elif update.phase == "response_error":
            self._status = "response error"
            self._latest_action = _invocation_label(update.response)
            self._latest_action_name = _invocation_name(update.action)
            self._latest_error = update.error
        elif update.phase == "after_transition":
            self._status = "running" if update.state.status == "running" else update.state.status
            self._changed_cells = _changed_cells(
                previous_map,
                tuple(update.observation["map"]),
                previous_state,
                update.state,
            )
            self._latest_action = _invocation_label(update.action)
            self._latest_action_name = _invocation_name(update.action)
            self._latest_error = None
        else:
            self._status = cast(str, update.status)
            self._latest_error = update.error

    def acting_updated(self, update: ActingUpdate) -> None:
        """Forward the previous observer method to the explicit observer contract."""

        self.on_acting_update(update)


def _entity_view(item: JsonObject) -> EntityView:
    properties = item["properties"]
    position_value = item["position"]
    position = None if position_value is None else (position_value[0], position_value[1])
    symbol = properties["symbol"]
    return EntityView(
        id=item["id"],
        position=position,
        symbol=symbol,
        properties=tuple(properties.items()),
        style=_entity_style(item["id"]),
    )


def _entity_style(entity_id: str) -> str:
    digest = hashlib.sha256(entity_id.encode()).digest()
    return _ENTITY_STYLES[digest[0] % len(_ENTITY_STYLES)]


def _action_view(action: JsonObject) -> ActionView:
    parameters = ", ".join(f"{name}: {kind}" for name, kind in action["parameters"].items())
    return ActionView(
        name=action["name"],
        signature=f"{action['name']}({parameters})",
        conditions=tuple(
            format_rule(item, multiline=True) for item in action["allowed_when"]
        ),
        effects=tuple(format_rule(item) for item in action["effects"]),
    )


def _automatic_rule_view(rule: JsonObject) -> AutomaticRuleView:
    return AutomaticRuleView(
        id=rule["id"],
        conditions=tuple(format_rule(item, multiline=True) for item in rule["when"]),
        effects=tuple(format_rule(item) for item in rule["effects"]),
    )


def _event_label(event: EventRecord) -> str:
    return event.event if event.target is None else f"{event.event} → {event.target}"


def _invocation_name(value: object) -> str | None:
    if isinstance(value, Mapping) and isinstance(value.get("action"), str):
        return cast(str, value["action"])
    return None


def _invocation_label(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None if value is None else str(value)
    action = value.get("action")
    arguments = value.get("arguments")
    if not isinstance(action, str) or not isinstance(arguments, Mapping):
        return format_rule(value)
    rendered_arguments = ", ".join(
        f"{name}={format_rule(argument)}" for name, argument in arguments.items()
    )
    return f"{action}({rendered_arguments})"


def _changed_cells(
    before: tuple[str, ...],
    after: tuple[str, ...],
    before_state: RuntimeState,
    after_state: RuntimeState,
) -> frozenset[tuple[int, int]]:
    changed = {
        (x, y)
        for y, row in enumerate(after)
        for x, character in enumerate(row)
        if y >= len(before) or x >= len(before[y]) or before[y][x] != character
    }
    for entity_id in before_state.positions.keys() | after_state.positions.keys():
        before_position = before_state.positions.get(entity_id)
        after_position = after_state.positions.get(entity_id)
        if before_position == after_position:
            continue
        if before_position is not None:
            changed.add(before_position)
        if after_position is not None:
            changed.add(after_position)
    return frozenset(changed)
