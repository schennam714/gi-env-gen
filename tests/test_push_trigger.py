from copy import deepcopy
from typing import Any

import pytest

from harness.acting import ActingResult, play
from harness.builder import AcceptedBuild, BuildRequest, GenerationFailed, build
from harness.runtime import UnusableActorOutputError, start, step

from .fixtures import push_trigger_build_response


class BuilderFake:
    def generate_build(self, request: BuildRequest) -> dict[str, Any]:
        return deepcopy(push_trigger_build_response())


class ActorFake:
    def __init__(self, actions: list[dict[str, Any]]) -> None:
        self.actions = actions
        self.observations: list[dict[str, Any]] = []

    def choose_action(self, observation: dict[str, Any]) -> dict[str, Any]:
        self.observations.append(deepcopy(observation))
        return deepcopy(self.actions.pop(0))


def test_generated_push_trigger_replays_and_independently_acts() -> None:
    response = push_trigger_build_response()
    accepted = build("Create a push and trigger puzzle.", BuilderFake())

    assert isinstance(accepted, AcceptedBuild)
    shift = accepted.validation.replay[1]
    assert shift.state.positions["block"] == (4, 1)
    assert shift.state.positions["explorer"] == (3, 1)
    assert shift.state.properties["barrier"] == {"symbol": "/", "solid": False, "open": True}
    assert shift.state.completed_objectives == ("place_object", "change_barrier")
    assert [(event.event, event.target) for event in shift.state.current_step_events] == [
        ("shifted", "block"),
        ("changed", "barrier"),
        ("observed_change", "barrier"),
    ]
    assert shift.observation["map"][2][5] == "/"
    assert accepted.validation.replay[-1].state.status == "success"

    actor = ActorFake(deepcopy(response["solution"]))
    acting = play("Create a push and trigger puzzle.", accepted, actor, max_steps=10)

    assert isinstance(acting, ActingResult)
    assert acting.status == "success"
    assert acting.transitions[-1].state == accepted.validation.replay[-1].state
    assert all("solution" not in observation for observation in actor.observations)


def test_entity_and_direction_arguments_are_type_checked() -> None:
    accepted = build("Create it", BuilderFake())
    assert isinstance(accepted, AcceptedBuild)
    initial = start(accepted.environment).state

    with pytest.raises(UnusableActorOutputError, match="must name a declared entity"):
        step(
            accepted.environment,
            initial,
            {"action": "SHIFT", "arguments": {"target": "absent", "heading": "DOWN"}},
        )


def test_validator_rejects_unknown_property_reference() -> None:
    response = push_trigger_build_response()
    response["environment"]["after_action"][0]["when"][1]["property"] = "missing"

    class InvalidBuilder:
        def generate_build(self, request: BuildRequest) -> dict[str, Any]:
            return deepcopy(response)

    result = build("Create it", InvalidBuilder())

    assert isinstance(result, GenerationFailed)
    assert result.diagnostics[0].code == "UNKNOWN_PROPERTY"


def test_after_action_runs_after_a_well_formed_inapplicable_attempt() -> None:
    response = push_trigger_build_response()
    response["environment"]["after_action"].insert(
        0,
        {
            "id": "record_attempt",
            "when": [],
            "effects": [{"operation": "emit", "event": "attempted"}],
        },
    )

    class RecordingBuilder:
        def generate_build(self, request: BuildRequest) -> dict[str, Any]:
            return deepcopy(response)

    accepted = build("Create it", RecordingBuilder())
    assert isinstance(accepted, AcceptedBuild)

    transition = step(
        accepted.environment,
        start(accepted.environment).state,
        {"action": "SHIFT", "arguments": {"target": "block", "heading": "RIGHT"}},
    )

    assert transition.outcome == "inapplicable"
    assert [event.event for event in transition.state.current_step_events] == ["attempted"]


def test_replay_rejects_a_property_change_that_overlaps_solid_entities() -> None:
    response = push_trigger_build_response()
    response["environment"]["after_action"][0]["effects"].append(
        {
            "operation": "set_property",
            "entity": "marker",
            "property": "solid",
            "value": True,
        }
    )

    class InvalidStateBuilder:
        def generate_build(self, request: BuildRequest) -> dict[str, Any]:
            return deepcopy(response)

    result = build("Create it", InvalidStateBuilder())

    assert isinstance(result, GenerationFailed)
    assert result.diagnostics[0].phase == "solution_replay"
    assert "two solid entities" in result.diagnostics[0].message


def test_parameterized_property_write_requires_property_on_every_entity_target() -> None:
    response = push_trigger_build_response()
    response["environment"]["actions"][1]["effects"].append(
        {
            "operation": "set_property",
            "entity": "$target",
            "property": "movable",
            "value": False,
        }
    )

    class UnsafePropertyBuilder:
        def generate_build(self, request: BuildRequest) -> dict[str, Any]:
            return deepcopy(response)

    result = build("Create it", UnsafePropertyBuilder())

    assert isinstance(result, GenerationFailed)
    assert result.diagnostics[0].code == "UNKNOWN_PROPERTY"
    assert result.diagnostics[0].path.endswith("effects[3].property")
