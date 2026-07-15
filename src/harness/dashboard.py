"""Public facade for the read-only reviewer dashboard."""

from .dashboard_projection import (
    ActionView,
    AutomaticRuleView,
    DashboardFrame,
    DashboardProjection,
    EntityView,
    FailureView,
    ObjectiveView,
)
from .dashboard_rendering import (
    DASHBOARD_THEME,
    LiveDashboard,
    generation_waiting,
    log_summary,
    render_dashboard,
)
from .rule_formatting import format_rule

__all__ = [
    "ActionView",
    "AutomaticRuleView",
    "DASHBOARD_THEME",
    "DashboardFrame",
    "DashboardProjection",
    "EntityView",
    "FailureView",
    "LiveDashboard",
    "ObjectiveView",
    "format_rule",
    "generation_waiting",
    "log_summary",
    "render_dashboard",
]
