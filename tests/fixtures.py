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

