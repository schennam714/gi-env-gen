from copy import deepcopy
from typing import Any

from gi_env_gen.acting import ActingResult, play
from gi_env_gen.builder import AcceptedBuild, BuildRequest, GenerationFailed, build
from gi_env_gen.runtime import start, step

from .fixtures import timed_build_response


class BuilderFake:
    def generate_build(self, request: BuildRequest) -> dict[str, Any]:
        return deepcopy(timed_build_response())


class ActorFake:
    def __init__(self, actions: list[dict[str, Any]]) -> None:
        self.actions = actions
        self.observations: list[dict[str, Any]] = []

    def choose_action(self, observation: dict[str, Any]) -> dict[str, Any]:
        self.observations.append(deepcopy(observation))
        return deepcopy(self.actions.pop(0))


def test_generated_timed_environment_replays_and_independently_acts() -> None:
    response = timed_build_response()
    accepted = build("Reach the beacon before time runs out.", BuilderFake())

    assert isinstance(accepted, AcceptedBuild)
    assert [transition.state.values for transition in accepted.validation.replay] == [
        {"remaining": 3, "moves": 1, "marker": 1},
        {"remaining": 2, "moves": 2, "marker": 1},
        {"remaining": 1, "moves": 3, "marker": 1},
    ]
    assert accepted.validation.replay[-1].state.status == "success"
    actor = ActorFake(deepcopy(response["solution"]))
    result = play("Reach the beacon before time runs out.", accepted, actor, max_steps=4)

    assert isinstance(result, ActingResult)
    assert result.status == "success"
    assert actor.observations[0]["values"] == {"remaining": 4, "moves": 0, "marker": 0}
    assert actor.observations[-1]["values"] == {"remaining": 2, "moves": 2, "marker": 1}


def test_inapplicable_attempt_still_changes_generated_values() -> None:
    response = timed_build_response()
    class TimedBuilder:
        def generate_build(self, request: BuildRequest) -> dict[str, Any]:
            return deepcopy(response)

    accepted = build("Create it", TimedBuilder())
    assert isinstance(accepted, AcceptedBuild)
    transition = step(
        accepted.environment,
        start(accepted.environment).state,
        {"action": "ADVANCE", "arguments": {"heading": "LEFT"}},
    )

    assert transition.outcome == "inapplicable"
    assert transition.state.values == {"remaining": 3, "moves": 1, "marker": 1}


def test_replay_rejects_solution_that_reaches_generated_failure() -> None:
    response = timed_build_response()
    response["environment"]["values"]["remaining"] = 3

    class FailingBuilder:
        def generate_build(self, request: BuildRequest) -> dict[str, Any]:
            return deepcopy(response)

    result = build("Create it", FailingBuilder())

    assert isinstance(result, GenerationFailed)
    assert result.diagnostics[0].code == "GENERATED_FAILURE"


def test_set_value_and_all_numeric_comparators() -> None:
    response = timed_build_response()
    response["environment"]["values"] = {"score": 1}
    response["environment"]["after_action"] = [
        {
            "id": "replace_score",
            "when": [
                {"operation": "value_compare", "value": "score", "comparator": comparator, "expected": expected}
                for comparator, expected in (("eq", 1), ("ne", 2), ("lt", 2), ("lte", 1), ("gt", 0), ("gte", 1))
            ],
            "effects": [{"operation": "set_value", "value": "score", "new_value": 7}],
        }
    ]
    response["environment"]["failures"] = []

    class ValueBuilder:
        def generate_build(self, request: BuildRequest) -> dict[str, Any]:
            return deepcopy(response)

    accepted = build("Create it", ValueBuilder())
    assert isinstance(accepted, AcceptedBuild)
    assert accepted.validation.replay[0].state.values == {"score": 7}


def test_value_validation_rejects_unknown_incompatible_and_invalid_parameter_references() -> None:
    cases = []
    unknown = timed_build_response()
    unknown["environment"]["after_action"][0]["effects"][0]["value"] = "missing"
    cases.append((unknown, "UNKNOWN_VALUE"))
    incompatible = timed_build_response()
    incompatible["environment"]["values"]["remaining"] = "three"
    cases.append((incompatible, "INCOMPATIBLE_VALUE_TYPE"))
    bad_parameter = timed_build_response()
    bad_parameter["environment"]["failures"][0]["when"]["expected"] = "$missing"
    cases.append((bad_parameter, "INVALID_VALUE_REFERENCE"))

    for response, code in cases:
        class InvalidBuilder:
            def generate_build(self, request: BuildRequest) -> dict[str, Any]:
                return deepcopy(response)

        result = build("Create it", InvalidBuilder())
        assert isinstance(result, GenerationFailed)
        assert result.diagnostics[0].code == code
