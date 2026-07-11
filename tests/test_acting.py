from copy import deepcopy
from typing import Any

from gi_env_gen.acting import ActingResult, play
from gi_env_gen.builder import AcceptedBuild, build

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
