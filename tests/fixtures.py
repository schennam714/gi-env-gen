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
