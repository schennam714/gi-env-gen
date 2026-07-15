from copy import deepcopy
from typing import Any

import pytest

from harness.acting import play
from harness.builder import AcceptedBuild, GenerationFailed, build

from .test_acting import FakeActor
from .test_builder import FakeProvider


def mixed_build_response() -> dict[str, Any]:
    """A provider-fake complete composition, not a user-facing mechanic template."""
    return {
        "status": "generated",
        "interpretation": [
            "Claim the token, change the barrier, and reach the beacon.",
            "An autonomous entity advances and the generated charge decreases after every attempt.",
        ],
        "environment": {
            "actor": "explorer",
            "map": [
                "##########",
                "#ATD...E.#",
                "#........#",
                "#.....H..#",
                "##########",
            ],
            "legend": {
                "A": {"id": "explorer", "properties": {"symbol": "@", "solid": True}},
                "T": {
                    "id": "token",
                    "properties": {"symbol": "t", "solid": False, "held_by": None},
                },
                "D": {
                    "id": "barrier",
                    "properties": {"symbol": "D", "solid": True, "sealed": True},
                },
                "E": {"id": "beacon", "properties": {"symbol": "E", "solid": False}},
                "H": {"id": "wanderer", "properties": {"symbol": "H", "solid": False}},
            },
            "values": {"charge": 5},
            "actions": [
                {
                    "name": "ADVANCE",
                    "parameters": {"heading": "direction"},
                    "allowed_when": [
                        {"operation": "can_move", "entity": "explorer", "direction": "$heading"}
                    ],
                    "effects": [
                        {"operation": "move", "entity": "explorer", "direction": "$heading"}
                    ],
                },
                {
                    "name": "CLAIM",
                    "parameters": {},
                    "allowed_when": [
                        {"operation": "adjacent", "first": "explorer", "second": "token"},
                        {
                            "operation": "property_equals",
                            "entity": "token",
                            "property": "held_by",
                            "value": None,
                        },
                    ],
                    "effects": [
                        {"operation": "set_position", "entity": "token", "destination": None},
                        {
                            "operation": "set_property",
                            "entity": "token",
                            "property": "held_by",
                            "value": "explorer",
                        },
                        {"operation": "emit", "event": "claimed", "target": "token"},
                    ],
                },
                {
                    "name": "CHANGE",
                    "parameters": {},
                    "allowed_when": [
                        {"operation": "adjacent", "first": "explorer", "second": "barrier"},
                        {
                            "operation": "property_equals",
                            "entity": "token",
                            "property": "held_by",
                            "value": "explorer",
                        },
                    ],
                    "effects": [
                        {
                            "operation": "set_property",
                            "entity": "barrier",
                            "property": "sealed",
                            "value": False,
                        },
                        {
                            "operation": "set_property",
                            "entity": "barrier",
                            "property": "solid",
                            "value": False,
                        },
                        {
                            "operation": "set_property",
                            "entity": "barrier",
                            "property": "symbol",
                            "value": "/",
                        },
                        {"operation": "emit", "event": "changed", "target": "barrier"},
                    ],
                },
                {
                    "name": "TRAVERSE",
                    "parameters": {"heading": "direction"},
                    "allowed_when": [
                        {
                            "operation": "property_equals",
                            "entity": "barrier",
                            "property": "sealed",
                            "value": False,
                        }
                    ],
                    "effects": [
                        {
                            "operation": "repeat",
                            "while": {
                                "operation": "all",
                                "conditions": [
                                    {
                                        "operation": "can_move",
                                        "entity": "explorer",
                                        "direction": "$heading",
                                    },
                                    {
                                        "operation": "not",
                                        "condition": {
                                            "operation": "at",
                                            "first": "explorer",
                                            "second": "beacon",
                                        },
                                    },
                                ],
                            },
                            "effects": [
                                {
                                    "operation": "move",
                                    "entity": "explorer",
                                    "direction": "$heading",
                                }
                            ],
                        }
                    ],
                },
            ],
            "after_action": [
                {
                    "id": "consume_charge",
                    "when": [],
                    "effects": [{"operation": "change_value", "value": "charge", "amount": -1}],
                },
                {
                    "id": "advance_wanderer",
                    "when": [],
                    "effects": [
                        {"operation": "move_toward", "entity": "wanderer", "target": "explorer"}
                    ],
                },
            ],
            "objectives": [
                {
                    "id": "claim_token",
                    "description": "Emit a claim for the token this turn.",
                    "satisfied_when": {
                        "operation": "event_occurred",
                        "event": "claimed",
                        "target": "token",
                        "scope": "current_step",
                    },
                },
                {
                    "id": "change_barrier",
                    "description": "Emit a barrier change this turn.",
                    "satisfied_when": {
                        "operation": "event_occurred",
                        "event": "changed",
                        "target": "barrier",
                        "scope": "current_step",
                    },
                },
                {
                    "id": "reach_beacon",
                    "description": "Reach the beacon after claiming the token.",
                    "satisfied_when": {
                        "operation": "all",
                        "conditions": [
                            {"operation": "at", "first": "explorer", "second": "beacon"},
                            {
                                "operation": "event_occurred",
                                "event": "claimed",
                                "target": "token",
                                "scope": "episode",
                            },
                        ],
                    },
                },
            ],
            "failures": [
                {
                    "id": "charge_depleted_after_claim",
                    "description": "The charge was depleted after the token was claimed.",
                    "when": {
                        "operation": "all",
                        "conditions": [
                            {
                                "operation": "value_compare",
                                "value": "charge",
                                "comparator": "lte",
                                "expected": 0,
                            },
                            {
                                "operation": "event_occurred",
                                "event": "claimed",
                                "target": "token",
                                "scope": "episode",
                            },
                        ],
                    },
                },
                {
                    "id": "intercepted",
                    "description": "The autonomous entity reached the explorer.",
                    "when": {"operation": "at", "first": "wanderer", "second": "explorer"},
                },
            ],
        },
        "solution": [
            {"action": "CLAIM", "arguments": {}},
            {"action": "ADVANCE", "arguments": {"heading": "RIGHT"}},
            {"action": "CHANGE", "arguments": {}},
            {"action": "TRAVERSE", "arguments": {"heading": "RIGHT"}},
        ],
    }


def test_mixed_generated_program_replays_and_independent_actor_succeeds() -> None:
    response = mixed_build_response()
    accepted = build("Compose one generated environment", FakeProvider(response))

    assert isinstance(accepted, AcceptedBuild)
    assert accepted.validation.replay[-1].state.status == "success"
    assert accepted.validation.replay[-1].state.completed_objectives == (
        "claim_token",
        "change_barrier",
        "reach_beacon",
    )
    actor = FakeActor(deepcopy(response["solution"]))

    result = play("Compose one generated environment", accepted, actor, max_steps=6)

    assert result.status == "success"
    assert result.transitions[-1].state.positions["token"] is None
    assert result.transitions[-1].state.positions["wanderer"] == (6, 1)
    assert result.transitions[-1].state.properties["barrier"]["sealed"] is False
    assert result.transitions[-1].state.values["charge"] == 1
    assert len(result.transitions[-1].direct_effect_states) == 5
    assert [event.event for event in result.transitions[-1].state.episode_events] == [
        "claimed",
        "changed",
    ]
    expected_action_names = [
        "ADVANCE",
        "CLAIM",
        "CHANGE",
        "TRAVERSE",
    ]
    assert all(
        [action["name"] for action in observation["available_actions"]]
        == expected_action_names
        for observation in actor.observations
    )
    assert "solution" not in repr(actor.observations)
    assert "attempts" not in repr(actor.observations)


def test_same_validation_passed_environment_can_end_in_generated_acting_failure() -> None:
    response = mixed_build_response()
    accepted = build("Compose one generated environment", FakeProvider(response))
    assert isinstance(accepted, AcceptedBuild)
    actor = FakeActor(
        [
            {"action": "CLAIM", "arguments": {}},
            *[
                {"action": "ADVANCE", "arguments": {"heading": "LEFT"}}
                for _ in range(4)
            ],
        ]
    )

    result = play("Compose one generated environment", accepted, actor, max_steps=5)

    assert result.status == "generated_failure"
    assert result.transitions[-1].state.failure_id == "charge_depleted_after_claim"
    assert result.transitions[-1].applicable is False
    assert result.transitions[-1].state.values["charge"] == 0


def test_complete_program_rejects_an_empty_action_name_before_replay() -> None:
    response = mixed_build_response()
    response["environment"]["actions"][0]["name"] = ""
    response["solution"][1]["action"] = ""

    result = build(
        "Compose one generated environment",
        FakeProvider(*([response] * 5)),
    )

    assert isinstance(result, GenerationFailed)
    assert result.attempts[0].diagnostics[0].code == "INVALID_ACTION_NAME"
    assert result.attempts[0].diagnostics[0].path == "environment.actions[0].name"


@pytest.mark.parametrize(
    ("namespace", "expected_code"),
    [
        ("entities", "INVALID_ENTITY_ID"),
        ("actions", "INVALID_ACTION_NAME"),
        ("after_action_rules", "INVALID_AFTER_ACTION_ID"),
        ("objectives", "INVALID_OBJECTIVE"),
        ("failures", "INVALID_FAILURE"),
    ],
)
def test_complete_program_rejects_duplicate_ids_before_replay(
    namespace: str,
    expected_code: str,
) -> None:
    response = mixed_build_response()
    environment = response["environment"]
    if namespace == "entities":
        environment["legend"]["T"]["id"] = environment["legend"]["A"]["id"]
    elif namespace == "actions":
        environment["actions"][1]["name"] = environment["actions"][0]["name"]
    elif namespace == "after_action_rules":
        environment["after_action"][1]["id"] = environment["after_action"][0]["id"]
    elif namespace == "objectives":
        environment["objectives"][1]["id"] = environment["objectives"][0]["id"]
    else:
        environment["failures"][1]["id"] = environment["failures"][0]["id"]

    result = build(
        "Compose one generated environment",
        FakeProvider(*([response] * 5)),
    )

    assert isinstance(result, GenerationFailed)
    assert result.attempts[0].diagnostics[0].code == expected_code


@pytest.mark.parametrize(
    ("namespace", "expected_code"),
    [
        ("entities", "INVALID_ENTITY_ID"),
        ("values", "INVALID_VALUES"),
        ("parameters", "INVALID_PARAMETERS"),
        ("after_action_rules", "INVALID_AFTER_ACTION_ID"),
        ("objectives", "INVALID_OBJECTIVE"),
        ("failures", "INVALID_FAILURE"),
    ],
)
def test_complete_program_rejects_empty_ids_before_replay(
    namespace: str,
    expected_code: str,
) -> None:
    response = mixed_build_response()
    environment = response["environment"]
    if namespace == "entities":
        environment["legend"]["T"]["id"] = ""
    elif namespace == "values":
        environment["values"][""] = environment["values"].pop("charge")
        environment["after_action"][0]["effects"][0]["value"] = ""
        environment["failures"][0]["when"]["conditions"][0]["value"] = ""
    elif namespace == "parameters":
        environment["actions"][0]["parameters"] = {"": "direction"}
        environment["actions"][0]["allowed_when"][0]["direction"] = "$"
        environment["actions"][0]["effects"][0]["direction"] = "$"
        response["solution"][1]["arguments"] = {"": "RIGHT"}
    elif namespace == "after_action_rules":
        environment["after_action"][0]["id"] = ""
    elif namespace == "objectives":
        environment["objectives"][0]["id"] = ""
    else:
        environment["failures"][0]["id"] = ""

    result = build(
        "Compose one generated environment",
        FakeProvider(*([response] * 5)),
    )

    assert isinstance(result, GenerationFailed)
    assert result.attempts[0].diagnostics[0].code == expected_code


@pytest.mark.parametrize(
    ("mutation", "expected_code", "expected_path"),
    [
        ("empty_event", "INVALID_EVENT", "environment.objectives[0].satisfied_when.event"),
        ("invalid_scope", "INVALID_EVENT_SCOPE", "environment.objectives[0].satisfied_when.scope"),
        ("wrong_scope_type", "INVALID_EVENT_SCOPE", "environment.objectives[0].satisfied_when.scope"),
        ("unknown_target", "UNKNOWN_ENTITY", "environment.objectives[0].satisfied_when.target"),
        ("extra_field", "INVALID_CONDITION", "environment.objectives[0].satisfied_when"),
        ("empty_emit", "INVALID_EFFECT", "environment.actions[1].effects[2].event"),
    ],
)
def test_event_operations_are_fully_validated_before_replay(
    mutation: str,
    expected_code: str,
    expected_path: str,
) -> None:
    response = mixed_build_response()
    condition = response["environment"]["objectives"][0]["satisfied_when"]
    if mutation == "empty_event":
        condition["event"] = ""
    elif mutation == "invalid_scope":
        condition["scope"] = "turn"
    elif mutation == "wrong_scope_type":
        condition["scope"] = []
    elif mutation == "unknown_target":
        condition["target"] = "$target"
    elif mutation == "extra_field":
        condition["unexpected"] = True
    else:
        response["environment"]["actions"][1]["effects"][2]["event"] = ""

    result = build(
        "Compose one generated environment",
        FakeProvider(*([response] * 5)),
    )

    assert isinstance(result, GenerationFailed)
    diagnostic = result.attempts[0].diagnostics[0]
    assert diagnostic.code == expected_code
    assert diagnostic.path == expected_path
