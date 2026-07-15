from copy import deepcopy
from typing import Any

import pytest

from harness.acting import ActingResult, play
from harness.builder import AcceptedBuild, BuildRequest, GenerationFailed, build
from harness.runtime import EffectLimitExceeded, start, step

from .fixtures import bounded_repeat_build_response


class BuilderFake:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or bounded_repeat_build_response()

    def generate_build(self, request: BuildRequest) -> dict[str, Any]:
        return deepcopy(self.response)


class ActorFake:
    def __init__(self, actions: list[dict[str, Any]]) -> None:
        self.actions = actions
        self.observations: list[dict[str, Any]] = []

    def choose_action(self, observation: dict[str, Any]) -> dict[str, Any]:
        self.observations.append(deepcopy(observation))
        return deepcopy(self.actions.pop(0))


def test_generated_sliding_solution_replays_and_independently_acts() -> None:
    response = bounded_repeat_build_response()
    accepted = build("Create an ice-like environment with continued movement.", BuilderFake())

    assert isinstance(accepted, AcceptedBuild)
    replay = accepted.validation.replay[0]
    assert [state.positions["explorer"] for state in replay.effect_states] == [
        (2, 1),
        (3, 1),
        (4, 1),
        (5, 1),
        (6, 1),
        (7, 1),
    ]
    assert replay.state.status == "success"

    actor = ActorFake(deepcopy(response["solution"]))
    acting = play(
        "Create an ice-like environment with continued movement.",
        accepted,
        actor,
        max_steps=2,
    )

    assert isinstance(acting, ActingResult)
    assert acting.status == "success"
    assert acting.transitions[0].state == replay.state
    assert all("solution" not in observation for observation in actor.observations)


def test_nested_repeat_is_rejected_before_replay() -> None:
    response = bounded_repeat_build_response()
    outer = response["environment"]["actions"][0]["effects"][0]
    outer["effects"] = [deepcopy(outer)]

    result = build("Create it", BuilderFake(response))

    assert isinstance(result, GenerationFailed)
    assert result.diagnostics[0].code == "NESTED_REPEAT"
    assert result.diagnostics[0].path.endswith("effects[0].effects[0]")


def test_effect_limit_is_shared_with_after_action_rules() -> None:
    response = bounded_repeat_build_response()
    response["environment"]["actions"][0]["effects"] = [
        {"operation": "emit", "event": f"direct_{index}"} for index in range(100)
    ]
    response["environment"]["after_action"] = [
        {
            "id": "one_more",
            "when": [],
            "effects": [{"operation": "emit", "event": "automatic"}],
        }
    ]

    result = build("Create it", BuilderFake(response))

    assert isinstance(result, GenerationFailed)
    assert result.diagnostics[0].phase == "solution_replay"
    assert result.diagnostics[0].code == "EFFECT_LIMIT_EXCEEDED"


def test_exactly_100_effect_applications_are_allowed() -> None:
    response = bounded_repeat_build_response()
    response["environment"]["actions"][0]["effects"] = [
        *({"operation": "emit", "event": f"direct_{index}"} for index in range(99)),
        {"operation": "set_position", "entity": "explorer", "destination": "goal"},
    ]

    result = build("Create it", BuilderFake(response))

    assert isinstance(result, AcceptedBuild)
    assert len(result.validation.replay[0].effect_states) == 100
    assert result.validation.replay[0].state.status == "success"


def test_limit_exhaustion_during_acting_is_an_environment_program_error() -> None:
    accepted = build("Create it", BuilderFake())
    assert isinstance(accepted, AcceptedBuild)

    result = play(
        "Create it",
        accepted,
        ActorFake([{"action": "LOOP", "arguments": {}}]),
        max_steps=1,
    )

    assert result.status == "invalid_generated_program"
    assert result.reason is not None and "100" in result.reason
    assert result.transitions == ()


def test_true_repeat_with_no_child_effects_cannot_loop_forever() -> None:
    response = bounded_repeat_build_response()
    response["environment"]["actions"][1]["effects"][0]["effects"] = []
    accepted = build("Create it", BuilderFake(response))
    assert isinstance(accepted, AcceptedBuild)

    with pytest.raises(EffectLimitExceeded, match="cannot make progress"):
        step(
            accepted.environment,
            start(accepted.environment).state,
            {"action": "LOOP", "arguments": {}},
        )


def test_repeat_re_evaluates_its_condition_after_each_child_effect_pass() -> None:
    response = bounded_repeat_build_response()
    response["environment"]["map"] = ["#####", "#AE.#", "#####"]
    repeated = response["environment"]["actions"][0]["effects"][0]
    repeated["while"] = {
        "operation": "not",
        "condition": {"operation": "at", "first": "explorer", "second": "goal"},
    }
    repeated["effects"].append({"operation": "emit", "event": "completed_pass"})
    accepted = build("Create it", BuilderFake(response))
    assert isinstance(accepted, AcceptedBuild)

    transition = step(
        accepted.environment,
        start(accepted.environment).state,
        {"action": "GLIDE", "arguments": {"heading": "RIGHT"}},
    )

    assert len(transition.effect_states) == 2
    assert transition.state.positions["explorer"] == (2, 1)
    assert [event.event for event in transition.state.current_step_events] == ["completed_pass"]
