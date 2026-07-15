from copy import deepcopy
from typing import Any

import pytest

from harness.acting import ActingResult, play
from harness.builder import AcceptedBuild, BuildRequest, GenerationFailed, build
from harness.model import freeze_environment
from harness.runtime import start, step

from .fixtures import possession_prerequisite_build_response


class BuilderFake:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or possession_prerequisite_build_response()

    def generate_build(self, request: BuildRequest) -> dict[str, Any]:
        return deepcopy(self.response)


class ActorFake:
    def __init__(self, actions: list[dict[str, Any]]) -> None:
        self.actions = actions
        self.observations: list[dict[str, Any]] = []

    def choose_action(self, observation: dict[str, Any]) -> dict[str, Any]:
        self.observations.append(deepcopy(observation))
        return deepcopy(self.actions.pop(0))


def test_generated_possession_prerequisite_replays_and_independently_acts() -> None:
    response = possession_prerequisite_build_response()
    accepted = build("Create a retrieval and prerequisite environment.", BuilderFake())

    assert isinstance(accepted, AcceptedBuild)
    claim = accepted.validation.replay[1]
    assert claim.state.positions["token"] is None
    assert claim.state.properties["token"]["held_by"] == "explorer"
    assert "k" not in "".join(claim.observation["map"])
    assert claim.observation["entities"][1] == {
        "id": "token",
        "position": None,
        "properties": {"symbol": "k", "solid": False, "held_by": "explorer"},
    }
    access = accepted.validation.replay[3]
    assert access.state.properties["barrier"] == {
        "symbol": "/",
        "solid": False,
        "sealed": False,
    }
    assert accepted.validation.replay[-1].state.status == "success"

    actor = ActorFake(deepcopy(response["solution"]))
    acting = play(
        "Create a retrieval and prerequisite environment.",
        accepted,
        actor,
        max_steps=10,
    )

    assert isinstance(acting, ActingResult)
    assert acting.status == "success"
    off_map_observation = actor.observations[2]
    token = next(entity for entity in off_map_observation["entities"] if entity["id"] == "token")
    assert token["position"] is None
    assert token["properties"]["held_by"] == "explorer"
    assert all("solution" not in observation for observation in actor.observations)


@pytest.mark.parametrize(
    ("destination", "expected"),
    [([2, 1], (2, 1)), ("goal", (7, 1)), (None, None)],
)
def test_set_position_supports_each_destination_shape(
    destination: list[int] | str | None,
    expected: tuple[int, int] | None,
) -> None:
    response = possession_prerequisite_build_response()
    response["environment"]["actions"].append(
        {
            "name": "RELOCATE",
            "parameters": {},
            "allowed_when": [],
            "effects": [
                {"operation": "set_position", "entity": "token", "destination": destination}
            ],
        }
    )
    frozen = freeze_environment(response["environment"])

    transition = step(
        frozen,
        start(frozen).state,
        {"action": "RELOCATE", "arguments": {}},
    )

    assert transition.state.positions["token"] == expected


@pytest.mark.parametrize(
    ("effect", "code", "path_suffix"),
    [
        (
            {"operation": "set_position", "entity": "absent", "destination": None},
            "UNKNOWN_ENTITY",
            ".entity",
        ),
        (
            {"operation": "set_position", "entity": "token", "destination": "absent"},
            "UNKNOWN_ENTITY",
            ".destination",
        ),
        (
            {"operation": "set_position", "entity": "token", "destination": [1, "bad"]},
            "INVALID_POSITION",
            ".destination",
        ),
    ],
)
def test_validator_rejects_invalid_set_position_references_and_types(
    effect: dict[str, Any], code: str, path_suffix: str
) -> None:
    response = possession_prerequisite_build_response()
    response["environment"]["actions"][1]["effects"][0] = effect

    result = build("Create it", BuilderFake(response))

    assert isinstance(result, GenerationFailed)
    assert result.diagnostics[0].code == code
    assert result.diagnostics[0].path.endswith(path_suffix)


def test_validator_rejects_incompatible_set_position_parameter_type() -> None:
    response = possession_prerequisite_build_response()
    claim = response["environment"]["actions"][1]
    claim["parameters"] = {"where": "direction"}
    claim["effects"][0]["destination"] = "$where"

    result = build("Create it", BuilderFake(response))

    assert isinstance(result, GenerationFailed)
    assert result.diagnostics[0].code == "UNKNOWN_ENTITY"
    assert result.diagnostics[0].path.endswith(".destination")


def test_validator_rejects_unknown_property_through_entity_parameter() -> None:
    response = possession_prerequisite_build_response()
    response["environment"]["actions"].append(
        {
            "name": "INSPECT",
            "parameters": {"target": "entity"},
            "allowed_when": [
                {
                    "operation": "property_equals",
                    "entity": "$target",
                    "property": "absent",
                    "value": True,
                }
            ],
            "effects": [],
        }
    )

    result = build("Create it", BuilderFake(response))

    assert isinstance(result, GenerationFailed)
    assert result.diagnostics[0].code == "UNKNOWN_PROPERTY"
    assert result.diagnostics[0].path.endswith(".property")
