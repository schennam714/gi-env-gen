from __future__ import annotations

import json
import os
from typing import Any

from .model import JsonObject

DEFAULT_MODEL = "gpt-5.6"

BUILDER_INSTRUCTIONS = """You are the builder for a deterministic 2D rule environment.
Return JSON only. Either return {status:'unsupported', interpretation:[...], reason:'...'}
or {status:'generated', interpretation:[...], environment:{...}, solution:[...]}.
Use exactly those top-level keys and no others.

For this minimal slice, environment must contain actor, map, legend, values, actions,
after_action, objectives, and failures. Map rows are rectangular ASCII; # is wall and .
is floor. Every other one-character token occurs once and maps through legend to an
entity with id and properties containing one-character symbol and boolean solid.
values, after_action, and failures must be empty.

You author action names. Every action has exactly this shape:
{"name":<string>, "parameters":{<parameter name>:"direction"},
"allowed_when":[<condition>, ...], "effects":[<effect>, ...]}.
parameters is a JSON object, never an array. The only generic conditions are:
- {operation:'at', first:<entity id>, second:<entity id>}
- {operation:'can_move', entity:<entity id>, direction:<literal or $parameter>}
The only effect is {operation:'move', entity:<entity id>, direction:<literal or
$parameter>}. Directions are exactly "UP", "RIGHT", "DOWN", or "LEFT". The runtime
has no fixed MOVE action or reach mechanic.

Objectives are ordered objects shaped exactly {"id":<string>, "description":<string>,
"satisfied_when":<one condition object>}; satisfied_when is never an array. Every
solution item is exactly {"action":<generated action name>, "arguments":{<parameter
name>:<uppercase direction>}}. Supply a solution that deterministically reaches
success. No objective may be true initially. If the request cannot be represented
exactly, return unsupported; do not approximate. Interpretation is visible, fallible
model judgment.
"""

ACTOR_INSTRUCTIONS = """You are the acting policy in a frozen deterministic 2D world.
The JSON observation is complete. Choose exactly one available generated action and
return JSON shaped {"action": <name>, "arguments": {...}}. Copy the action name and
parameter names exactly. A direction argument must be exactly one of "UP", "RIGHT",
"DOWN", or "LEFT" in uppercase. Never claim or alter state.
"""


class MissingCredential(RuntimeError):
    pass


class OpenAIProvider:
    """One provider adapter used for stateless builder and acting calls."""

    def __init__(self, *, model: str = DEFAULT_MODEL, client: Any | None = None) -> None:
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise MissingCredential("OPENAI_API_KEY is required for live generation and acting")
            from openai import OpenAI

            client = OpenAI()
        self._client = client
        self._model = model

    def generate_build(self, prompt: str) -> JsonObject:
        return self._json_response(BUILDER_INSTRUCTIONS, prompt)

    def choose_action(self, observation: JsonObject) -> JsonObject:
        return self._json_response(ACTOR_INSTRUCTIONS, json.dumps(observation, sort_keys=True))

    def _json_response(self, instructions: str, input_text: str) -> JsonObject:
        response = self._client.responses.create(
            model=self._model,
            instructions=instructions,
            input="Return one JSON object for this request:\n" + input_text,
            text={"format": {"type": "json_object"}},
            store=False,
        )
        value = json.loads(response.output_text)
        if not isinstance(value, dict):
            raise ValueError("provider response must be a JSON object")
        return value
