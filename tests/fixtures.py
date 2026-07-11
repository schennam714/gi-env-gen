from __future__ import annotations

from typing import Any


def reach_build_response() -> dict[str, Any]:
    """A provider-fake response, never a user-facing generated environment."""
    return {
        "status": "generated",
        "interpretation": ["Move the explorer to the beacon."],
        "environment": {
            "actor": "explorer",
            "map": ["#####", "#A.B#", "#####"],
            "legend": {
                "A": {"id": "explorer", "properties": {"symbol": "@", "solid": True}},
                "B": {"id": "beacon", "properties": {"symbol": "X", "solid": False}},
            },
            "values": {},
            "actions": [
                {
                    "name": "TRAVEL",
                    "parameters": {"heading": "direction"},
                    "allowed_when": [
                        {
                            "operation": "can_move",
                            "entity": "explorer",
                            "direction": "$heading",
                        }
                    ],
                    "effects": [
                        {"operation": "move", "entity": "explorer", "direction": "$heading"}
                    ],
                }
            ],
            "after_action": [],
            "objectives": [
                {
                    "id": "reach_beacon",
                    "description": "Reach the beacon.",
                    "satisfied_when": {
                        "operation": "at",
                        "first": "explorer",
                        "second": "beacon",
                    },
                }
            ],
            "failures": [],
        },
        "solution": [
            {"action": "TRAVEL", "arguments": {"heading": "RIGHT"}},
            {"action": "TRAVEL", "arguments": {"heading": "RIGHT"}},
        ],
    }


def timed_build_response() -> dict[str, Any]:
    """A provider-fake numeric-state composition, not a resource mechanic template."""
    return {
        "status": "generated",
        "interpretation": ["Reach the beacon before the remaining turns reach zero."],
        "environment": {
            "actor": "explorer",
            "map": ["######", "#A..B#", "######"],
            "legend": {
                "A": {"id": "explorer", "properties": {"symbol": "@", "solid": True}},
                "B": {"id": "beacon", "properties": {"symbol": "X", "solid": False}},
            },
            "values": {"remaining": 4, "moves": 0, "marker": 0},
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
                }
            ],
            "after_action": [
                {
                    "id": "advance_values",
                    "when": [],
                    "effects": [
                        {"operation": "change_value", "value": "remaining", "amount": -1},
                        {"operation": "change_value", "value": "moves", "amount": 1},
                        {"operation": "set_value", "value": "marker", "new_value": 1},
                    ],
                }
            ],
            "objectives": [
                {
                    "id": "reach_beacon",
                    "description": "Reach the beacon while time remains.",
                    "satisfied_when": {"operation": "at", "first": "explorer", "second": "beacon"},
                }
            ],
            "failures": [
                {
                    "id": "out_of_turns",
                    "description": "The remaining turns reached zero.",
                    "when": {
                        "operation": "value_compare",
                        "value": "remaining",
                        "comparator": "lte",
                        "expected": 0,
                    },
                }
            ],
        },
        "solution": [
            {"action": "ADVANCE", "arguments": {"heading": "RIGHT"}},
            {"action": "ADVANCE", "arguments": {"heading": "RIGHT"}},
            {"action": "ADVANCE", "arguments": {"heading": "RIGHT"}},
        ],
    }


def push_trigger_build_response() -> dict[str, Any]:
    """A provider-fake composition of generic operations, not a mechanic template."""
    return {
        "status": "generated",
        "interpretation": [
            "The explorer can move and shift a movable object.",
            "Placing the object on the marker changes the barrier before the explorer reaches the goal.",
        ],
        "environment": {
            "actor": "explorer",
            "map": ["#######", "#A.BP.#", "#....G#", "#....E#", "#######"],
            "legend": {
                "A": {"id": "explorer", "properties": {"symbol": "@", "solid": True}},
                "B": {
                    "id": "block",
                    "properties": {"symbol": "B", "solid": True, "movable": True},
                },
                "P": {"id": "marker", "properties": {"symbol": "P", "solid": False}},
                "G": {
                    "id": "barrier",
                    "properties": {"symbol": "G", "solid": True, "open": False},
                },
                "E": {"id": "goal", "properties": {"symbol": "E", "solid": False}},
            },
            "values": {},
            "actions": [
                {
                    "name": "NAVIGATE",
                    "parameters": {"heading": "direction"},
                    "allowed_when": [
                        {
                            "operation": "can_move",
                            "entity": "explorer",
                            "direction": "$heading",
                        }
                    ],
                    "effects": [
                        {"operation": "move", "entity": "explorer", "direction": "$heading"}
                    ],
                },
                {
                    "name": "SHIFT",
                    "parameters": {"target": "entity", "heading": "direction"},
                    "allowed_when": [
                        {
                            "operation": "adjacent",
                            "first": "explorer",
                            "second": "$target",
                            "direction": "$heading",
                        },
                        {
                            "operation": "property_equals",
                            "entity": "$target",
                            "property": "movable",
                            "value": True,
                        },
                        {
                            "operation": "can_move",
                            "entity": "$target",
                            "direction": "$heading",
                        },
                    ],
                    "effects": [
                        {"operation": "move", "entity": "$target", "direction": "$heading"},
                        {"operation": "move", "entity": "explorer", "direction": "$heading"},
                        {"operation": "emit", "event": "shifted", "target": "$target"},
                    ],
                },
            ],
            "after_action": [
                {
                    "id": "change_barrier",
                    "when": [
                        {"operation": "at", "first": "block", "second": "marker"},
                        {
                            "operation": "property_equals",
                            "entity": "barrier",
                            "property": "open",
                            "value": False,
                        },
                    ],
                    "effects": [
                        {
                            "operation": "set_property",
                            "entity": "barrier",
                            "property": "open",
                            "value": True,
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
                    "id": "observe_changed_barrier",
                    "when": [
                        {
                            "operation": "property_equals",
                            "entity": "barrier",
                            "property": "open",
                            "value": True,
                        }
                    ],
                    "effects": [
                        {"operation": "emit", "event": "observed_change", "target": "barrier"}
                    ],
                },
            ],
            "objectives": [
                {
                    "id": "place_object",
                    "description": "Place the movable object on the marker.",
                    "satisfied_when": {"operation": "at", "first": "block", "second": "marker"},
                },
                {
                    "id": "change_barrier",
                    "description": "Change the barrier.",
                    "satisfied_when": {
                        "operation": "property_equals",
                        "entity": "barrier",
                        "property": "open",
                        "value": True,
                    },
                },
                {
                    "id": "reach_goal",
                    "description": "Reach the goal.",
                    "satisfied_when": {"operation": "at", "first": "explorer", "second": "goal"},
                },
            ],
            "failures": [],
        },
        "solution": [
            {"action": "NAVIGATE", "arguments": {"heading": "RIGHT"}},
            {"action": "SHIFT", "arguments": {"target": "block", "heading": "RIGHT"}},
            {"action": "NAVIGATE", "arguments": {"heading": "DOWN"}},
            {"action": "NAVIGATE", "arguments": {"heading": "RIGHT"}},
            {"action": "NAVIGATE", "arguments": {"heading": "RIGHT"}},
            {"action": "NAVIGATE", "arguments": {"heading": "DOWN"}},
        ],
    }


def pursuit_build_response() -> dict[str, Any]:
    """A provider-fake autonomous composition, not a pursuit mechanic template."""
    return {
        "status": "generated",
        "interpretation": [
            "The explorer must reach the beacon while an autonomous entity moves toward it.",
            "Sharing a position with the autonomous entity ends the run.",
        ],
        "environment": {
            "actor": "explorer",
            "map": ["#######", "#A...E#", "#.###.#", "#T....#", "#######"],
            "legend": {
                "A": {"id": "explorer", "properties": {"symbol": "@", "solid": True}},
                "T": {"id": "pursuer", "properties": {"symbol": "T", "solid": False}},
                "E": {"id": "beacon", "properties": {"symbol": "X", "solid": False}},
            },
            "values": {},
            "actions": [
                {
                    "name": "ADVANCE",
                    "parameters": {"heading": "direction"},
                    "allowed_when": [{"operation": "can_move", "entity": "explorer", "direction": "$heading"}],
                    "effects": [{"operation": "move", "entity": "explorer", "direction": "$heading"}],
                }
            ],
            "after_action": [
                {
                    "id": "close_distance",
                    "when": [],
                    "effects": [{"operation": "move_toward", "entity": "pursuer", "target": "explorer"}],
                }
            ],
            "objectives": [
                {
                    "id": "reach_beacon",
                    "description": "Reach the beacon.",
                    "satisfied_when": {"operation": "at", "first": "explorer", "second": "beacon"},
                }
            ],
            "failures": [
                {
                    "id": "caught",
                    "description": "The autonomous entity reached the explorer.",
                    "when": {"operation": "at", "first": "pursuer", "second": "explorer"},
                }
            ],
        },
        "solution": [
            {"action": "ADVANCE", "arguments": {"heading": "RIGHT"}},
            {"action": "ADVANCE", "arguments": {"heading": "RIGHT"}},
            {"action": "ADVANCE", "arguments": {"heading": "RIGHT"}},
            {"action": "ADVANCE", "arguments": {"heading": "RIGHT"}},
        ],
    }


def possession_prerequisite_build_response() -> dict[str, Any]:
    """A provider-fake generic possession composition, not a mechanic template."""
    return {
        "status": "generated",
        "interpretation": [
            "The explorer must claim the token, changing its location and ownership state.",
            "The sealed barrier changes only while the token is held before the explorer reaches the goal.",
        ],
        "environment": {
            "actor": "explorer",
            "map": ["#########", "#A.KD..E#", "#########"],
            "legend": {
                "A": {"id": "explorer", "properties": {"symbol": "@", "solid": True}},
                "K": {
                    "id": "token",
                    "properties": {"symbol": "k", "solid": False, "held_by": None},
                },
                "D": {
                    "id": "barrier",
                    "properties": {"symbol": "D", "solid": True, "sealed": True},
                },
                "E": {"id": "goal", "properties": {"symbol": "E", "solid": False}},
            },
            "values": {},
            "actions": [
                {
                    "name": "ADVANCE",
                    "parameters": {"heading": "direction"},
                    "allowed_when": [
                        {
                            "operation": "can_move",
                            "entity": "explorer",
                            "direction": "$heading",
                        }
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
                    ],
                },
                {
                    "name": "CHANGE_ACCESS",
                    "parameters": {},
                    "allowed_when": [
                        {"operation": "adjacent", "first": "explorer", "second": "barrier"},
                        {
                            "operation": "property_equals",
                            "entity": "token",
                            "property": "held_by",
                            "value": "explorer",
                        },
                        {
                            "operation": "property_equals",
                            "entity": "barrier",
                            "property": "sealed",
                            "value": True,
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
                    ],
                },
            ],
            "after_action": [],
            "objectives": [
                {
                    "id": "hold_token",
                    "description": "Make the token held by the explorer.",
                    "satisfied_when": {
                        "operation": "property_equals",
                        "entity": "token",
                        "property": "held_by",
                        "value": "explorer",
                    },
                },
                {
                    "id": "change_access",
                    "description": "Change the sealed barrier.",
                    "satisfied_when": {
                        "operation": "property_equals",
                        "entity": "barrier",
                        "property": "sealed",
                        "value": False,
                    },
                },
                {
                    "id": "reach_goal",
                    "description": "Reach the goal.",
                    "satisfied_when": {"operation": "at", "first": "explorer", "second": "goal"},
                },
            ],
            "failures": [],
        },
        "solution": [
            {"action": "ADVANCE", "arguments": {"heading": "RIGHT"}},
            {"action": "CLAIM", "arguments": {}},
            {"action": "ADVANCE", "arguments": {"heading": "RIGHT"}},
            {"action": "CHANGE_ACCESS", "arguments": {}},
            {"action": "ADVANCE", "arguments": {"heading": "RIGHT"}},
            {"action": "ADVANCE", "arguments": {"heading": "RIGHT"}},
            {"action": "ADVANCE", "arguments": {"heading": "RIGHT"}},
            {"action": "ADVANCE", "arguments": {"heading": "RIGHT"}},
        ],
    }


def bounded_repeat_build_response() -> dict[str, Any]:
    """A provider-fake repeated-movement composition, not a mechanic template."""
    return {
        "status": "generated",
        "interpretation": [
            "The explorer's generated action repeatedly moves while its generated condition remains true.",
            "The explorer must stop at the goal before the wall.",
        ],
        "environment": {
            "actor": "explorer",
            "map": ["#########", "#A.....E#", "#########"],
            "legend": {
                "A": {"id": "explorer", "properties": {"symbol": "@", "solid": True}},
                "E": {"id": "goal", "properties": {"symbol": "E", "solid": False}},
            },
            "values": {},
            "actions": [
                {
                    "name": "GLIDE",
                    "parameters": {"heading": "direction"},
                    "allowed_when": [],
                    "effects": [
                        {
                            "operation": "repeat",
                            "while": {
                                "operation": "all",
                                "conditions": [
                                    {
                                        "operation": "any",
                                        "conditions": [
                                            {
                                                "operation": "at",
                                                "first": "explorer",
                                                "second": "goal",
                                            },
                                            {
                                                "operation": "can_move",
                                                "entity": "explorer",
                                                "direction": "$heading",
                                            },
                                        ],
                                    },
                                    {
                                        "operation": "not",
                                        "condition": {
                                            "operation": "at",
                                            "first": "explorer",
                                            "second": "goal",
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
                {
                    "name": "LOOP",
                    "parameters": {},
                    "allowed_when": [],
                    "effects": [
                        {
                            "operation": "repeat",
                            "while": {"operation": "all", "conditions": []},
                            "effects": [{"operation": "emit", "event": "looped"}],
                        }
                    ],
                },
            ],
            "after_action": [],
            "objectives": [
                {
                    "id": "reach_goal",
                    "description": "Reach the goal.",
                    "satisfied_when": {"operation": "at", "first": "explorer", "second": "goal"},
                }
            ],
            "failures": [],
        },
        "solution": [{"action": "GLIDE", "arguments": {"heading": "RIGHT"}}],
    }
