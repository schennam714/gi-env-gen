from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

from rich.console import Console, Group, RenderableType
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from .acting import ActingUpdate, ActingUpdates
from .model import FrozenEnvironment, JsonObject
from .runtime import EventRecord, RuntimeState, start


DASHBOARD_THEME = Theme(
    {
        "heading": "bold bright_white",
        "muted": "grey62",
        "waiting": "bold yellow",
        "running": "bold cyan",
        "success": "bold green",
        "failure": "bold red",
        "changed": "bold reverse",
    }
)

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
    model: str
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


class DashboardProjection(ActingUpdates):
    """Read-only projection of frozen rules and deterministic acting updates."""

    def __init__(
        self,
        *,
        model: str,
        environment: FrozenEnvironment,
        max_steps: int,
        evidence_path: Path,
    ) -> None:
        self._model = model
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
            model=self._model,
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

    def acting_updated(self, update: ActingUpdate) -> None:
        previous_map = tuple(self._observation["map"])
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
            self._changed_cells = _changed_cells(previous_map, tuple(update.observation["map"]))
            self._latest_action = _invocation_label(update.action)
            self._latest_action_name = _invocation_name(update.action)
            self._latest_error = None
        else:
            self._status = cast(str, update.status)
            self._latest_error = update.error


class LiveDashboard(ActingUpdates):
    def __init__(self, projection: DashboardProjection, live: Live, console: Console) -> None:
        self._projection = projection
        self._live = live
        self._console = console

    def acting_updated(self, update: ActingUpdate) -> None:
        self._projection.acting_updated(update)
        self._live.update(
            render_dashboard(
                self._projection.frame,
                width=self._console.width,
                height=self._console.height,
            ),
            refresh=True,
        )


def format_rule(value: object) -> str:
    """Format a generated generic operation without interpreting its mechanics."""

    if isinstance(value, Mapping):
        operation = value.get("operation")
        if isinstance(operation, str):
            if operation in {"all", "any"} and isinstance(value.get("conditions"), list):
                children = ", ".join(format_rule(item) for item in value["conditions"])
                return f"{operation}({children})"
            arguments = ", ".join(
                f"{key}={format_rule(item)}"
                for key, item in value.items()
                if key != "operation"
            )
            return f"{operation}({arguments})"
        return "{" + ", ".join(f"{key}={format_rule(item)}" for key, item in value.items()) + "}"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "[" + ", ".join(format_rule(item) for item in value) + "]"
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def render_dashboard(
    frame: DashboardFrame,
    *,
    width: int,
    height: int | None = None,
) -> RenderableType:
    dashboard = frame
    world = Panel(
        Group(_map_text(dashboard), _legend_table(dashboard)),
        title="Generated world",
        border_style="bright_blue",
    )
    details = Group(
        _actions_panel(dashboard),
        _automatic_rules_panel(dashboard),
        _objectives_panel(dashboard),
        _state_panel(dashboard),
    )
    if height is not None and height < 35:
        return _compact_dashboard(dashboard)
    if width < 100:
        return Group(_header(dashboard), world, details, _footer(dashboard))
    root = Layout(name="dashboard")
    root.split_column(
        Layout(_header(dashboard), name="header", size=3),
        Layout(name="body"),
        Layout(_footer(dashboard), name="footer", size=3),
    )
    body = root["body"]
    body.split_row(
        Layout(world, name="world", ratio=5, minimum_size=38),
        Layout(details, name="details", ratio=7, minimum_size=54),
    )
    return root


def generation_waiting(model: str) -> Panel:
    text = Text()
    text.append("Generating environment\n", style="heading")
    text.append(f"Model: {model}\n", style="muted")
    text.append("Waiting for builder response…", style="waiting")
    return Panel(text, border_style="yellow")


def log_summary(frame: DashboardFrame, *, builder_attempts: int) -> tuple[str, ...]:
    completed = sum(item.status == "complete" for item in frame.objectives)
    triggered = [item.id for item in frame.failures if item.triggered]
    failure_summary = ", ".join(triggered) if triggered else "none triggered"
    return (
        (
            f"Environment {frame.environment_hash_prefix} accepted after "
            f"{builder_attempts} builder {'attempt' if builder_attempts == 1 else 'attempts'}."
        ),
        f"Acting: {frame.status} · step {frame.step}/{frame.max_steps}",
        f"Objectives: {completed}/{len(frame.objectives)} complete · Failures: {failure_summary}",
        f"Evidence: {frame.evidence_path}",
    )


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
        conditions=tuple(format_rule(item) for item in action["allowed_when"]),
        effects=tuple(format_rule(item) for item in action["effects"]),
    )


def _automatic_rule_view(rule: JsonObject) -> AutomaticRuleView:
    return AutomaticRuleView(
        id=rule["id"],
        conditions=tuple(format_rule(item) for item in rule["when"]),
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


def _changed_cells(before: tuple[str, ...], after: tuple[str, ...]) -> frozenset[tuple[int, int]]:
    return frozenset(
        (x, y)
        for y, row in enumerate(after)
        for x, character in enumerate(row)
        if y >= len(before) or x >= len(before[y]) or before[y][x] != character
    )


def _header(frame: DashboardFrame) -> Panel:
    status_style = (
        "success"
        if frame.status == "success"
        else "failure"
        if frame.status in {"generated_failure", "failure", "provider_failure", "invalid_generated_program", "unusable_actor_output"}
        else "waiting"
        if frame.status.startswith("waiting")
        else "running"
    )
    text = Text()
    text.append("Reviewer dashboard", style="heading")
    text.append(f"  {frame.model}", style="muted")
    text.append(f"  env {frame.environment_hash_prefix}", style="muted")
    text.append(f"  turn {frame.step}/{frame.max_steps}  ")
    text.append(frame.status, style=status_style)
    return Panel(text, border_style="grey39")


def _map_text(frame: DashboardFrame) -> Text:
    positions: dict[tuple[int, int], EntityView] = {
        entity.position: entity for entity in frame.entities if entity.position is not None
    }
    text = Text()
    for y, row in enumerate(frame.map_rows):
        for x, character in enumerate(row):
            entity = positions.get((x, y))
            style = entity.style if entity is not None else "grey70"
            if (x, y) in frame.changed_cells:
                style = f"{style} bold reverse"
            text.append(character, style=style)
        if y < len(frame.map_rows) - 1:
            text.append("\n")
    return text


def _legend_table(frame: DashboardFrame) -> Table:
    table = Table(title="Legend", box=None, padding=(0, 1), expand=True)
    table.add_column("", width=1)
    table.add_column("Entity", style="bright_white")
    table.add_column("Position", style="muted")
    table.add_column("Properties", overflow="fold")
    for entity in frame.entities:
        properties = ", ".join(
            f"{name}={format_rule(value)}" for name, value in entity.properties if name != "symbol"
        )
        table.add_row(
            Text(entity.symbol, style=entity.style),
            entity.id,
            "off-map" if entity.position is None else f"[{entity.position[0]},{entity.position[1]}]",
            properties,
        )
    return table


def _actions_panel(frame: DashboardFrame) -> Panel:
    table = Table(box=None, padding=(0, 1), expand=True)
    table.add_column("Generated actions", style="heading")
    for action in frame.actions:
        marker = "›" if action.name == frame.latest_action_name else " "
        table.add_row(Text(f"{marker} {action.signature}", no_wrap=True, overflow="ellipsis"))
        if action.name == frame.latest_action_name:
            when = " ∧ ".join(action.conditions) if action.conditions else "always"
            then = "; ".join(
                f"{index}. {effect}" for index, effect in enumerate(action.effects, start=1)
            ) or "no effects"
            table.add_row(Text(f"  when {when}\n  then {then}", style="muted"))
    latest = frame.latest_error or frame.latest_action or "—"
    table.add_row(Text(f"Latest: {latest}", style="failure" if frame.latest_error else "muted"))
    return Panel(table, border_style="cyan")


def _automatic_rules_panel(frame: DashboardFrame) -> Panel:
    table = Table(box=None, padding=(0, 1), expand=True)
    table.add_column("Rule", style="bright_white", no_wrap=True)
    table.add_column("when / then", overflow="fold")
    if not frame.automatic_rules:
        table.add_row("—", "No generated automatic rules")
    for rule in frame.automatic_rules:
        when = " ∧ ".join(rule.conditions) if rule.conditions else "always"
        then = "; ".join(
            f"{index}. {effect}" for index, effect in enumerate(rule.effects, start=1)
        ) or "no effects"
        table.add_row(rule.id, f"when {when}\nthen {then}")
    return Panel(table, title="Automatic rules", border_style="magenta")


def _objectives_panel(frame: DashboardFrame) -> Panel:
    table = Table(box=None, padding=(0, 1), expand=True)
    table.add_column("", width=1)
    table.add_column("Objective")
    markers = {"complete": "✓", "current": "›", "pending": "·"}
    for objective in frame.objectives:
        table.add_row(markers[objective.status], f"{objective.id}: {objective.description}")
    table.add_section()
    if not frame.failures:
        table.add_row("·", "Failures: none declared")
    for failure in frame.failures:
        marker = "!" if failure.triggered else "·"
        state = "triggered" if failure.triggered else "dormant"
        table.add_row(marker, f"{failure.id} ({state}): {failure.description}")
    return Panel(table, title="Objectives & failures", border_style="green")


def _state_panel(frame: DashboardFrame) -> Panel:
    values = ", ".join(f"{name}={format_rule(value)}" for name, value in frame.values) or "—"
    events = ", ".join(frame.events) or "—"
    text = Text()
    text.append("Values  ", style="heading")
    text.append(values)
    text.append("\nEvents  ", style="heading")
    text.append(events)
    return Panel(text, title="Current deterministic state", border_style="yellow")


def _footer(frame: DashboardFrame) -> Panel:
    return Panel(Text(f"Evidence  {frame.evidence_path}", style="muted"), border_style="grey39")


def _compact_dashboard(frame: DashboardFrame) -> Panel:
    world = Table(box=None, padding=(0, 2), expand=True)
    world.add_column("Map", style="heading", ratio=2)
    world.add_column("Legend", style="heading", ratio=3)
    legend = Text()
    for index, entity in enumerate(frame.entities):
        if index:
            legend.append("\n")
        legend.append(entity.symbol, style=entity.style)
        position = "off-map" if entity.position is None else f"[{entity.position[0]},{entity.position[1]}]"
        properties = ",".join(
            f"{name}={format_rule(value)}" for name, value in entity.properties if name != "symbol"
        )
        legend.append(f" {entity.id} {position} {properties}")
    world.add_row(_map_text(frame), legend)

    actions = Table(box=None, padding=(0, 1), expand=True)
    actions.add_column("Actions", style="heading", width=9)
    actions.add_column()
    for action in frame.actions:
        marker = "› " if action.name == frame.latest_action_name else ""
        actions.add_row("", Text(f"{marker}{action.signature}", no_wrap=True, overflow="ellipsis"))
    selected = next(
        (action for action in frame.actions if action.name == frame.latest_action_name),
        None,
    )
    if selected is not None:
        when = " ∧ ".join(selected.conditions) if selected.conditions else "always"
        then = "; ".join(
            f"{index}. {effect}" for index, effect in enumerate(selected.effects, start=1)
        ) or "no effects"
        actions.add_row("", Text(f"when {when}\nthen {then}", style="muted"))
    latest = frame.latest_error or frame.latest_action or "—"
    actions.add_row("Latest", Text(latest, style="failure" if frame.latest_error else "muted"))

    details = Text()
    details.append("Status  ", style="heading")
    details.append(frame.status)
    details.append("\nAutomatic rules  ", style="heading")
    if not frame.automatic_rules:
        details.append("—")
    for index, rule in enumerate(frame.automatic_rules):
        if index:
            details.append(" · ")
        when = " ∧ ".join(rule.conditions) if rule.conditions else "always"
        then = "; ".join(
            f"{effect_index}. {effect}"
            for effect_index, effect in enumerate(rule.effects, start=1)
        ) or "no effects"
        details.append(f"{rule.id}: when {when} then {then}")

    details.append("\nObjectives  ", style="heading")
    markers = {"complete": "✓", "current": "›", "pending": "·"}
    details.append(
        " · ".join(
            f"{markers[objective.status]} {objective.id}" for objective in frame.objectives
        )
    )
    details.append("\nFailures  ", style="heading")
    if not frame.failures:
        details.append("none declared")
    else:
        details.append(
            " · ".join(
                f"{'!' if failure.triggered else '·'} {failure.id} "
                f"({'triggered' if failure.triggered else 'dormant'})"
                for failure in frame.failures
            )
        )
    values = ", ".join(f"{name}={format_rule(value)}" for name, value in frame.values) or "—"
    events = ", ".join(frame.events) or "—"
    details.append("\nValues  ", style="heading")
    details.append(values)
    details.append("  Events  ", style="heading")
    details.append(events)
    details.append("\nEvidence  ", style="heading")
    details.append(frame.evidence_path, style="muted")

    title = (
        f"Reviewer dashboard · {frame.model} · env {frame.environment_hash_prefix} · "
        f"turn {frame.step}/{frame.max_steps} · {frame.status}"
    )
    return Panel(Group(world, actions, details), title=title, border_style="bright_blue")
