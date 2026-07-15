from copy import deepcopy
from typing import Any

from harness.acting import ActingResult, play
from harness.builder import AcceptedBuild, build

from .fixtures import reach_build_response
from .test_builder import FakeProvider


class FakeActor:
    def __init__(self, actions: list[dict[str, Any]]) -> None:
        self.actions = actions
        self.observations: list[dict[str, Any]] = []

    def choose_action(self, observation: dict[str, Any]) -> dict[str, Any]:
        self.observations.append(deepcopy(observation))
        return self.actions[len(self.observations) - 1]


def test_separate_actor_reaches_success_without_receiving_private_solution() -> None:
    accepted = build("Reach the beacon", FakeProvider(reach_build_response()))
    assert isinstance(accepted, AcceptedBuild)
    actor = FakeActor(
        [
            {"action": "TRAVEL", "arguments": {"heading": "RIGHT"}},
            {"action": "TRAVEL", "arguments": {"heading": "RIGHT"}},
        ]
    )

    result = play("Reach the beacon", accepted, actor, max_steps=5)

    assert isinstance(result, ActingResult)
    assert result.status == "success"
    assert len(actor.observations) == 2
    assert actor.observations[0]["original_prompt"] == "Reach the beacon"
    assert actor.observations[0]["interpretation"] == ["Move the explorer to the beacon."]
    assert actor.observations[0]["steps_remaining"] == 5
    assert "solution" not in repr(actor.observations)
    assert actor.observations[0]["available_actions"][0]["name"] == "TRAVEL"


def test_unusable_actor_output_receives_bounded_recovery_without_advancing_state() -> None:
    accepted = build("Reach the beacon", FakeProvider(reach_build_response()))
    assert isinstance(accepted, AcceptedBuild)
    actor = FakeActor(
        [
            {"action": "UNKNOWN", "arguments": {}},
            {"action": "TRAVEL", "arguments": {}},
            {"action": "TRAVEL", "arguments": {"heading": "north"}},
        ]
    )

    result = play("Reach the beacon", accepted, actor, max_steps=5)

    assert result.status == "unusable_actor_output"
    assert result.transitions == ()
    assert len(result.steps) == 1
    assert len(result.steps[0].response_attempts) == 3
    assert result.steps[0].transition is None
    assert len(actor.observations) == 3


def test_acting_provider_failure_is_attributed_without_advancing_state() -> None:
    accepted = build("Reach the beacon", FakeProvider(reach_build_response()))
    assert isinstance(accepted, AcceptedBuild)

    class FailingActor:
        def choose_action(self, observation: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("actor service unavailable")

    result = play("Reach the beacon", accepted, FailingActor(), max_steps=5)

    assert result.status == "provider_failure"
    assert result.reason == "actor service unavailable"
    assert result.transitions == ()
    assert result.steps[0].response_attempts[0].response is None
    assert result.steps[0].response_attempts[0].error == "actor service unavailable"
