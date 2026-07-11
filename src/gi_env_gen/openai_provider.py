from __future__ import annotations

import json
import os
from typing import Any

from .builder import BuildRequest
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
Additional builder-chosen properties may be boolean, number, string, or null. values
and failures must be empty in this slice.

You author action names. Every action has exactly this shape:
{"name":<string>, "parameters":{<parameter name>:"direction" or "entity"},
"allowed_when":[<condition>, ...], "effects":[<effect>, ...]}.
parameters is a JSON object, never an array. The only generic conditions are:
- {operation:'at', first:<entity id>, second:<entity id>}
- {operation:'adjacent', first:<entity ref>, second:<entity ref>, optional direction:<direction ref>}
- {operation:'can_move', entity:<entity id>, direction:<literal or $parameter>}
- {operation:'property_equals', entity:<entity ref>, property:<declared property>, value:<scalar>}
Conditions may compose recursively as {operation:'all' or 'any', conditions:[...]}
or {operation:'not', condition:<condition>}.
The generic effects are move; set_property on an existing property; emit with an
event string and optional entity target; and set_position shaped exactly as
{operation:'set_position', entity:<entity ref>, destination:<[x,y], entity ref, or null>}.
set_position uses an exact coordinate, copies another entity's current position, or
removes the entity from the grid with null while retaining all of its declared
properties in state. Entity and direction references may use a matching $parameter
inside their declaring action.
Directions are exactly "UP", "RIGHT", "DOWN", or "LEFT". Possession and access must
be authored from these generic positions and builder-chosen properties; there is no
built-in inventory, collection, key, or door behavior.
repeat is shaped exactly as {operation:'repeat', while:<condition>, effects:[<effect>, ...]}.
It re-evaluates while after every complete child-effect pass, cannot contain another
repeat, and shares a limit of 100 total effect applications with the action's other
effects and all after_action effects. Repeated movement must be authored from repeat
and move; the runtime has no sliding or conveyor mechanic.

after_action contains rules shaped {"id":<string>, "when":[<condition>, ...],
"effects":[<effect>, ...]}. They run once in declared order after every well-formed
action attempt. Effects run sequentially. The runtime has no fixed MOVE, PUSH,
crate, plate, or gate mechanic.

Objectives are ordered objects shaped exactly {"id":<string>, "description":<string>,
"satisfied_when":<one condition object>}; satisfied_when is never an array. Every
solution item is exactly {"action":<generated action name>, "arguments":{<declared
parameter name>:<typed value>}}. Supply a solution that deterministically reaches
success. No objective may be true initially. If the request cannot be represented
exactly, return unsupported; do not approximate. Interpretation is visible, fallible
model judgment.

The input is a complete stateless build request. On repair, preserve
frozen_interpretation exactly, inspect the complete previous_response and diagnostics,
and return a complete replacement response. Never omit unchanged fields or silently
alter the prompt, map geometry, or rules to evade an error.
"""

ACTOR_INSTRUCTIONS = """You are the acting policy in a frozen deterministic 2D world.
The JSON observation is complete. Choose exactly one available generated action and
return JSON shaped {"action": <name>, "arguments": {...}}. Copy the action name and
parameter names exactly. A direction argument must be exactly one of "UP", "RIGHT",
"DOWN", or "LEFT" in uppercase. An entity argument must copy a current declared entity
ID exactly. Never claim or alter state.
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

    def generate_build(self, request: BuildRequest) -> JsonObject:
        payload = {
            "original_prompt": request.original_prompt,
            "frozen_interpretation": request.frozen_interpretation,
            "previous_response": request.previous_response,
            "diagnostics": [diagnostic.__dict__ for diagnostic in request.diagnostics],
        }
        return self._json_response(BUILDER_INSTRUCTIONS, json.dumps(payload, sort_keys=True))

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
