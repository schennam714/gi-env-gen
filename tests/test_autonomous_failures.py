from copy import deepcopy
from typing import Any

from gi_env_gen.acting import ActingResult, play
from gi_env_gen.builder import AcceptedBuild, BuildRequest, GenerationFailed, build
from gi_env_gen.model import freeze_environment
from gi_env_gen.runtime import start, step

from .fixtures import pursuit_build_response


class BuilderFake:
    def generate_build(self, request: BuildRequest) -> dict[str, Any]:
        return deepcopy(pursuit_build_response())


class ActorFake:
    def __init__(self, actions: list[dict[str, Any]]) -> None:
        self.actions = actions

    def choose_action(self, observation: dict[str, Any]) -> dict[str, Any]:
        return deepcopy(self.actions.pop(0))


def test_generated_autonomous_threat_replays_and_acting_can_fail() -> None:
    response = pursuit_build_response()
    accepted = build("Create a moving-threat environment.", BuilderFake())

    assert isinstance(accepted, AcceptedBuild)
    assert accepted.validation.replay[-1].state.status == "success"
    first = accepted.validation.replay[0]
    assert first.direct_effect_states[-1].positions["explorer"] == (2, 1)
    assert first.automatic_effect_states[-1].positions["pursuer"] == (1, 2)
    assert first.observation["map"][2][1] == "T"

    actor = ActorFake(
        [
            {"action": "ADVANCE", "arguments": {"heading": "LEFT"}},
            {"action": "ADVANCE", "arguments": {"heading": "LEFT"}},
        ]
    )
    acting = play("Create a moving-threat environment.", accepted, actor, max_steps=2)

    assert isinstance(acting, ActingResult)
    assert acting.status == "failure"
    assert acting.transitions[-1].state.failure_id == "caught"
    assert acting.transitions[-1].outcome == "failure"


def test_move_toward_uses_fixed_tie_breaking_and_no_path_is_a_no_op() -> None:
    response = pursuit_build_response()
    program = response["environment"]
    program["map"] = ["#####", "#..A#", "#.T.#", "#..E#", "#####"]
    environment = freeze_environment(program)
    initial = start(environment).state

    tied = step(
        environment,
        initial,
        {"action": "ADVANCE", "arguments": {"heading": "LEFT"}},
    )
    assert tied.state.positions["pursuer"] == (2, 1)  # UP wins over RIGHT.

    blocked_program = deepcopy(program)
    blocked_program["map"] = ["#####", "###A#", "#T#.#", "##E.#", "#####"]
    blocked_environment = freeze_environment(blocked_program)
    blocked_initial = start(blocked_environment).state
    blocked = step(
        blocked_environment,
        blocked_initial,
        {"action": "ADVANCE", "arguments": {"heading": "LEFT"}},
    )
    assert blocked.state.positions["pursuer"] == blocked_initial.positions["pursuer"]

    solid_target_program = deepcopy(program)
    solid_target_program["legend"]["T"]["properties"]["solid"] = True
    solid_target_environment = freeze_environment(solid_target_program)
    solid_target_initial = start(solid_target_environment).state
    solid_target = step(
        solid_target_environment,
        solid_target_initial,
        {"action": "ADVANCE", "arguments": {"heading": "LEFT"}},
    )
    assert solid_target.state.positions["pursuer"] == solid_target_initial.positions["pursuer"]


def test_failure_wins_over_objective_completion_in_the_same_turn() -> None:
    response = pursuit_build_response()
    program = response["environment"]
    program["map"] = ["#####", "#ATE#", "#####"]
    program["objectives"][0]["satisfied_when"] = {
        "operation": "at",
        "first": "explorer",
        "second": "pursuer",
    }
    environment = freeze_environment(program)

    transition = step(
        environment,
        start(environment).state,
        {"action": "ADVANCE", "arguments": {"heading": "RIGHT"}},
    )

    assert transition.state.status == "failure"
    assert transition.state.failure_id == "caught"
    assert transition.state.completed_objectives == ()


def test_proposed_solution_that_triggers_generated_failure_is_rejected() -> None:
    response = pursuit_build_response()
    response["solution"] = [
        {"action": "ADVANCE", "arguments": {"heading": "DOWN"}},
    ]

    class CaughtBuilder:
        def generate_build(self, request: BuildRequest) -> dict[str, Any]:
            return deepcopy(response)

    result = build("Create it", CaughtBuilder())

    assert isinstance(result, GenerationFailed)
    assert result.diagnostics[0].code == "GENERATED_FAILURE"
    assert result.diagnostics[0].path == "solution[0]"
