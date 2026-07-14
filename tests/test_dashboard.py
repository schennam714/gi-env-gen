from copy import deepcopy
from pathlib import Path
from typing import Any

from rich.console import Console

from harness.acting import ActingUpdate, play
from harness.builder import AcceptedBuild, build
from harness.dashboard import (
    DASHBOARD_THEME,
    DashboardFrame,
    DashboardProjection,
    format_rule,
    render_dashboard,
)
from harness.model import RunModels

from .test_cli import reach_build_response


class BuildProviderFake:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def generate_build(self, request: object) -> dict[str, Any]:
        return deepcopy(self.response)


class ActorFake:
    def __init__(self, actions: list[dict[str, Any]]) -> None:
        self.actions = actions
        self.observations: list[dict[str, Any]] = []

    def choose_action(self, observation: dict[str, Any]) -> dict[str, Any]:
        self.observations.append(deepcopy(observation))
        return deepcopy(self.actions[len(self.observations) - 1])


REVIEWER_MODELS = RunModels(builder="builder-fake", actor="reviewer-fake")


def dashboard_build_response() -> dict[str, Any]:
    response = reach_build_response()
    response["environment"]["values"] = {"energy": 2}
    response["environment"]["after_action"] = [
        {
            "id": "consume_energy",
            "when": [{"operation": "all", "conditions": []}],
            "effects": [
                {"operation": "change_value", "value": "energy", "amount": -1},
                {"operation": "emit", "event": "advanced", "target": "explorer"},
            ],
        }
    ]
    response["environment"]["failures"] = [
        {
            "id": "energy_exhausted",
            "description": "Energy fell below zero.",
            "when": {
                "operation": "value_compare",
                "value": "energy",
                "comparator": "lt",
                "expected": 0,
            },
        }
    ]
    return response


def test_rule_projection_renders_generated_records_at_fixed_terminal_widths() -> None:
    accepted = build(
        "Reach the beacon before energy is exhausted",
        BuildProviderFake(dashboard_build_response()),
    )
    assert isinstance(accepted, AcceptedBuild)
    projection = DashboardProjection(
        models=REVIEWER_MODELS,
        environment=accepted.environment,
        max_steps=12,
        evidence_path=Path("run-evidence/test"),
    )

    assert format_rule(
        {
            "operation": "all",
            "conditions": [
                {"operation": "can_move", "entity": "$target", "direction": "$heading"},
                {"operation": "property_equals", "entity": "$target", "property": "movable", "value": True},
            ],
        }
    ) == (
        "all: can_move: $target can move $heading; "
        "property_equals: $target.movable is true"
    )

    wide = _render(projection.frame, width=120)
    narrow = _render(projection.frame, width=72, height=24)
    structured = _render(projection.frame, width=200)
    assert len(narrow.splitlines()) <= 24
    assert "WHEN" in narrow
    assert "THEN" in narrow
    assert "1. change_value:" in narrow
    assert "2. emit:" in narrow

    structured_lines = structured.splitlines()
    assert "Always (all: no conditions)" in structured
    when_line = next(index for index, line in enumerate(structured_lines) if "WHEN" in line)
    then_line = next(index for index, line in enumerate(structured_lines) if "THEN" in line)
    first_effect_line = next(
        index for index, line in enumerate(structured_lines) if "1. change_value:" in line
    )
    second_effect_line = next(
        index for index, line in enumerate(structured_lines) if "2. emit:" in line
    )
    assert when_line < then_line == first_effect_line < second_effect_line

    for output, width in ((wide, 120), (narrow, 72)):
        assert all(len(line) <= width for line in output.splitlines())
        assert "reviewer-fake" in output
        assert accepted.environment.content_hash[:10] in output
        assert "TRAVEL(heading: direction)" in output
        assert "Automatic rules" in output
        assert "consume_energy" in output
        assert "change_value:" in output
        assert "energy changes by -1" in output
        assert "Objectives" in output
        assert "energy_exhausted (dormant)" in output
        assert "energy=2" in output
        assert "Events" in output
        assert "Legend" in output
        assert "solid=true" in output
        assert "Evidence" in output
        assert "solution" not in output
        assert sum("TRAVEL(heading: direction)" in line for line in output.splitlines()) == 1

    assert "solution" not in repr(projection.frame)


def test_successive_acting_updates_produce_authoritative_dashboard_frames() -> None:
    accepted = build("Reach the beacon", BuildProviderFake(reach_build_response()))
    assert isinstance(accepted, AcceptedBuild)
    projection = DashboardProjection(
        models=REVIEWER_MODELS,
        environment=accepted.environment,
        max_steps=5,
        evidence_path=Path("run-evidence/test"),
    )
    actions = [
        {"action": "TRAVEL", "arguments": {"heading": "RIGHT"}},
        {"action": "TRAVEL", "arguments": {"heading": "RIGHT"}},
    ]

    class FrameRecorder:
        def __init__(self) -> None:
            self.frames = []

        def acting_updated(self, update: ActingUpdate) -> None:
            projection.acting_updated(update)
            self.frames.append(projection.frame)

    recorder = FrameRecorder()
    actor = ActorFake(actions)
    observed = play("Reach the beacon", accepted, actor, max_steps=5, updates=recorder)
    baseline = play("Reach the beacon", accepted, ActorFake(actions), max_steps=5)

    assert observed == baseline
    assert len(actor.observations) == 2
    assert [frame.status for frame in recorder.frames] == [
        "waiting for actor",
        "checking response",
        "running",
        "waiting for actor",
        "checking response",
        "success",
        "success",
    ]
    assert recorder.frames[2].map_rows == tuple(observed.transitions[0].observation["map"])
    assert recorder.frames[2].changed_cells == {(1, 1), (2, 1)}
    assert recorder.frames[3].changed_cells == set()
    assert recorder.frames[-1].map_rows == tuple(observed.transitions[-1].observation["map"])
    assert recorder.frames[-1].changed_cells == {(2, 1), (3, 1)}
    selected_action = _render(recorder.frames[2], width=140)
    assert "› TRAVEL(heading: direction)" in selected_action
    selected_lines = selected_action.splitlines()
    when_line = next(index for index, line in enumerate(selected_lines) if "WHEN" in line)
    condition_line = next(
        index for index, line in enumerate(selected_lines) if "• can_move:" in line
    )
    then_line = next(index for index, line in enumerate(selected_lines) if "THEN" in line)
    effect_line = next(
        index for index, line in enumerate(selected_lines) if "1. move:" in line
    )
    assert when_line == condition_line < then_line == effect_line
    assert "explorer can move $heading" in selected_action
    assert "explorer moves $heading" in selected_action
    compact_selected = _render(recorder.frames[2], width=72, height=24)
    assert "can_move" in compact_selected
    assert "explorer can move $heading" in compact_selected
    assert "THEN" in compact_selected
    assert "1. move:" in compact_selected
    assert "success" in _render(recorder.frames[-1], width=72)
    assert "solution" not in repr(recorder.frames)


def test_nested_conditions_and_wrapped_effects_keep_visual_hierarchy() -> None:
    response = dashboard_build_response()
    response["environment"]["after_action"] = [
        {
            "id": "nested_rule",
            "when": [
                {
                    "operation": "all",
                    "conditions": [
                        {
                            "operation": "any",
                            "conditions": [
                                {
                                    "operation": "value_compare",
                                    "value": "energy",
                                    "comparator": "gt",
                                    "expected": 0,
                                },
                                {
                                    "operation": "not",
                                    "condition": {
                                        "operation": "property_equals",
                                        "entity": "explorer",
                                        "property": "solid",
                                        "value": False,
                                    },
                                },
                            ],
                        }
                    ],
                }
            ],
            "effects": [
                {
                    "operation": "emit",
                    "event": "generated_event_with_a_deliberately_long_name_and_continued_tail",
                    "target": "explorer",
                }
            ],
        }
    ]
    accepted = build("Reach the beacon", BuildProviderFake(response))
    assert isinstance(accepted, AcceptedBuild)
    projection = DashboardProjection(
        models=REVIEWER_MODELS,
        environment=accepted.environment,
        max_steps=5,
        evidence_path=Path("run-evidence/test"),
    )

    rendered = _render(projection.frame, width=100)
    lines = rendered.splitlines()
    all_line = next(line for line in lines if "• all:" in line)
    any_line = next(line for line in lines if "• any:" in line)
    value_line = next(line for line in lines if "• value_compare:" in line)
    not_line = next(line for line in lines if "• not:" in line)
    effect_line = next(line for line in lines if "1. emit:" in line)
    continuation_line = next(line for line in lines if "tail for explorer" in line)

    assert all_line.index("•") < any_line.index("•") < value_line.index("•")
    assert any_line.index("•") < not_line.index("•")
    assert continuation_line.index("tail") == effect_line.index("emit:")


def test_unusable_responses_each_publish_an_unchanged_error_frame() -> None:
    accepted = build("Reach the beacon", BuildProviderFake(reach_build_response()))
    assert isinstance(accepted, AcceptedBuild)
    projection = DashboardProjection(
        models=REVIEWER_MODELS,
        environment=accepted.environment,
        max_steps=5,
        evidence_path=Path("run-evidence/test"),
    )

    class UpdateRecorder:
        def __init__(self) -> None:
            self.updates: list[ActingUpdate] = []

        def acting_updated(self, update: ActingUpdate) -> None:
            self.updates.append(update)
            projection.acting_updated(update)

    recorder = UpdateRecorder()
    result = play(
        "Reach the beacon",
        accepted,
        ActorFake(
            [
                {"action": "UNKNOWN", "arguments": {}},
                {"action": "TRAVEL", "arguments": {}},
                {"action": "TRAVEL", "arguments": {"heading": "north"}},
            ]
        ),
        max_steps=5,
        updates=recorder,
    )

    assert result.status == "unusable_actor_output"
    assert [update.phase for update in recorder.updates] == [
        "before_actor_request",
        "after_response_attempt",
        "response_error",
        "before_actor_request",
        "after_response_attempt",
        "response_error",
        "before_actor_request",
        "after_response_attempt",
        "response_error",
        "termination",
    ]
    assert all(update.state.step == 0 for update in recorder.updates)
    assert all(
        update.error is not None
        for update in recorder.updates
        if update.phase == "response_error"
    )
    assert projection.frame.latest_error is not None
    assert "solution" not in repr(recorder.updates)


def test_failing_read_only_updates_cannot_change_acting_semantics() -> None:
    accepted = build("Reach the beacon", BuildProviderFake(reach_build_response()))
    assert isinstance(accepted, AcceptedBuild)
    actions = [
        {"action": "TRAVEL", "arguments": {"heading": "RIGHT"}},
        {"action": "TRAVEL", "arguments": {"heading": "RIGHT"}},
    ]

    class FailingUpdates:
        def acting_updated(self, update: ActingUpdate) -> None:
            raise RuntimeError("renderer failed")

    observed_actor = ActorFake(actions)
    observed = play(
        "Reach the beacon",
        accepted,
        observed_actor,
        max_steps=5,
        updates=FailingUpdates(),
    )
    baseline_actor = ActorFake(actions)
    baseline = play("Reach the beacon", accepted, baseline_actor, max_steps=5)

    assert observed == baseline
    assert len(observed_actor.observations) == len(baseline_actor.observations) == 2


def test_terminal_frame_compacts_values_recent_events_objectives_and_failures() -> None:
    response = dashboard_build_response()
    accepted = build("Reach before energy is exhausted", BuildProviderFake(response))
    assert isinstance(accepted, AcceptedBuild)
    projection = DashboardProjection(
        models=REVIEWER_MODELS,
        environment=accepted.environment,
        max_steps=5,
        evidence_path=Path("run-evidence/test"),
    )

    result = play(
        "Reach before energy is exhausted",
        accepted,
        ActorFake(deepcopy(response["solution"])),
        max_steps=5,
        updates=projection,
    )
    rendered = _render(projection.frame, width=120)

    assert result.status == "success"
    assert "energy=0" in rendered
    assert "advanced → explorer" in rendered
    assert "✓" in rendered
    assert "energy_exhausted (dormant)" in rendered


def test_generated_failure_is_textually_marked_as_triggered() -> None:
    response = dashboard_build_response()
    accepted = build("Reach before energy is exhausted", BuildProviderFake(response))
    assert isinstance(accepted, AcceptedBuild)
    projection = DashboardProjection(
        models=REVIEWER_MODELS,
        environment=accepted.environment,
        max_steps=3,
        evidence_path=Path("run-evidence/test"),
    )

    result = play(
        "Reach before energy is exhausted",
        accepted,
        ActorFake(
            [
                {"action": "TRAVEL", "arguments": {"heading": "RIGHT"}},
                {"action": "TRAVEL", "arguments": {"heading": "LEFT"}},
                {"action": "TRAVEL", "arguments": {"heading": "RIGHT"}},
            ]
        ),
        max_steps=3,
        updates=projection,
    )
    rendered = _render(projection.frame, width=100)

    assert result.status == "generated_failure"
    assert "generated_failure" in rendered
    assert "energy_exhausted (triggered)" in rendered


def _render(frame: DashboardFrame, *, width: int, height: int = 70) -> str:
    console = Console(
        width=width,
        height=height,
        color_system=None,
        force_terminal=False,
        record=True,
        theme=DASHBOARD_THEME,
    )
    console.print(render_dashboard(frame, width=width, height=height))
    return console.export_text()
