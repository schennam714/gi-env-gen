from harness.model import freeze_environment
from harness.runtime import start, step

from .fixtures import reach_build_response


def test_generated_action_moves_actor_and_completes_reach_objective() -> None:
    frozen = freeze_environment(reach_build_response()["environment"])

    initial = start(frozen)
    first = step(
        frozen,
        initial.state,
        {"action": "TRAVEL", "arguments": {"heading": "RIGHT"}},
    )
    final = step(
        frozen,
        first.state,
        {"action": "TRAVEL", "arguments": {"heading": "RIGHT"}},
    )

    assert initial.observation["map"] == ["#####", "#@.X#", "#####"]
    assert first.state.positions["explorer"] == (2, 1)
    assert final.state.status == "success"
    assert final.state.completed_objectives == ("reach_beacon",)
