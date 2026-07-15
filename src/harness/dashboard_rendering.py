from __future__ import annotations


from rich.console import Console, Group, RenderableType
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from .acting import ActingObserver, ActingUpdate
from .model import RunModels
from .dashboard_projection import (
    AutomaticRuleView,
    DashboardFrame as DashboardFrame,
    DashboardProjection as DashboardProjection,
    EntityView,
)
from .rule_formatting import format_rule


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


class LiveDashboard(ActingObserver):
    def __init__(self, projection: DashboardProjection, live: Live, console: Console) -> None:
        self._projection = projection
        self._live = live
        self._console = console

    def on_acting_update(self, update: ActingUpdate) -> None:
        self._projection.on_acting_update(update)
        self._live.update(
            render_dashboard(
                self._projection.frame,
                width=self._console.width,
                height=self._console.height,
            ),
            refresh=True,
        )

    def acting_updated(self, update: ActingUpdate) -> None:
        """Forward the previous observer method to the explicit observer contract."""

        self.on_acting_update(update)



def _when_then_block(conditions: tuple[str, ...], effects: tuple[str, ...]) -> Table:
    rows = Table.grid(padding=(0, 1), expand=True)
    rows.add_column(width=5, style="heading")
    rows.add_column(width=3, justify="right")
    rows.add_column(ratio=1, overflow="fold")
    if conditions:
        for index, condition in enumerate(conditions):
            rows.add_row("WHEN" if index == 0 else "", "•", condition)
    else:
        rows.add_row("WHEN", "", "Always")

    if effects:
        for index, effect in enumerate(effects, start=1):
            rows.add_row("THEN" if index == 1 else "", f"{index}.", effect)
    else:
        rows.add_row("THEN", "", "No effects")

    return rows


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
        Layout(_header(dashboard), name="header", size=4),
        Layout(name="body"),
        Layout(_footer(dashboard), name="footer", size=3),
    )
    body = root["body"]
    body.split_row(
        Layout(world, name="world", ratio=5, minimum_size=38),
        Layout(details, name="details", ratio=7, minimum_size=54),
    )
    return root


def generation_waiting(models: RunModels) -> Panel:
    text = Text()
    text.append("Generating environment\n", style="heading")
    text.append(f"Builder: {models.builder} · Actor: {models.actor}\n", style="muted")
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
    text.append(f"  env {frame.environment_hash_prefix}", style="muted")
    text.append(f"  turn {frame.step}/{frame.max_steps}  ")
    text.append(frame.status, style=status_style)
    text.append(f"\nBuilder: {frame.models.builder}", style="muted")
    text.append(f" · Actor: {frame.models.actor}", style="muted")
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
            table.add_row(_when_then_block(action.conditions, action.effects))
    latest = frame.latest_error or frame.latest_action or "—"
    table.add_row(Text(f"Latest: {latest}", style="failure" if frame.latest_error else "muted"))
    return Panel(table, border_style="cyan")


def _automatic_rules_panel(frame: DashboardFrame) -> Panel:
    table = Table(box=None, padding=(0, 1), expand=True)
    table.add_column("Rule", style="bright_white", no_wrap=True)
    table.add_column("when / then", overflow="fold")
    _populate_automatic_rule_rows(table, frame.automatic_rules)
    return Panel(table, title="Automatic rules", border_style="magenta")


def _populate_automatic_rule_rows(
    table: Table,
    rules: tuple[AutomaticRuleView, ...],
) -> None:
    if not rules:
        table.add_row("—", "No generated automatic rules")
    for rule in rules:
        table.add_row(rule.id, _when_then_block(rule.conditions, rule.effects))


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
        actions.add_row("", _when_then_block(selected.conditions, selected.effects))
    latest = frame.latest_error or frame.latest_action or "—"
    actions.add_row("Latest", Text(latest, style="failure" if frame.latest_error else "muted"))

    status = Text()
    status.append(f"Builder: {frame.models.builder} · Actor: {frame.models.actor}\n", style="muted")
    status.append("Status  ", style="heading")
    status.append(frame.status)

    automatic_rules = Table.grid(padding=(0, 1), expand=True)
    automatic_rules.add_column(ratio=2, overflow="fold")
    automatic_rules.add_column(ratio=5, overflow="fold")
    _populate_automatic_rule_rows(automatic_rules, frame.automatic_rules)

    details = Text()
    details.append("Objectives  ", style="heading")
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
        f"Reviewer dashboard · env {frame.environment_hash_prefix} · "
        f"turn {frame.step}/{frame.max_steps} · {frame.status}"
    )
    return Panel(
        Group(
            world,
            actions,
            status,
            Text("Automatic rules", style="heading"),
            automatic_rules,
            details,
        ),
        title=title,
        border_style="bright_blue",
    )
