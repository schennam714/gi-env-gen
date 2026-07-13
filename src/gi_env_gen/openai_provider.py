from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from typing import Any, Callable

from .builder import BuildRequest, CandidateRejected, Diagnostic
from .model import JsonObject
from .structured_output import (
    MANIFEST_SCHEMA,
    build_response_schema,
    manifest_mismatch,
    validate_manifest,
)

DEFAULT_MODEL = "gpt-5.6"

MANIFEST_INSTRUCTIONS = """You are planning the names for a deterministic 2D rule environment.
If the request is unsupported, provide its interpretation and reason. Otherwise, list
every generated source-map token and entity ID, every property name on each entity,
and every generated action name and parameter name/type, plus every global value name. Every entity must list symbol
and solid. Entity tokens are one printable character and cannot be # or .. This manifest
fixes the dynamic keys for the complete response but does not
replace the complete environment program or proposed solution returned next.
"""

BUILDER_INSTRUCTIONS = """You are the builder for a deterministic 2D rule environment.
Return the complete response using exactly the names fixed by the supplied manifest.
For a generated response, author the map, entity property values, actions, automatic
rules, objectives, and proposed solution. For an unsupported response, explain why the
request cannot be represented exactly. The complete response's interpretation is the
authoritative wording used by validation and any later repair.

Map rows are rectangular ASCII; # is wall and . is floor. Every other source token
occurs once. Entity symbol is one printable character and solid is boolean. Additional
builder-chosen properties and global values may be boolean, number, string, or null.

The conditions are at, adjacent, can_move, property_equals, value_compare,
event_occurred, and recursive all, any, and not composition. value_compare supports
eq, ne, lt, lte, gt, and gte on declared numeric values. event_occurred checks an
exact emitted event and optional target at current_step or episode scope. The effects
are move, move_toward, set_position, set_property,
set_value, change_value, emit, and repeat. set_value replaces a declared value with a
compatible scalar; change_value adds a number to a declared numeric value. move_toward takes one traversable shortest-path step toward its
target, uses UP, RIGHT, DOWN, LEFT tie breaking, and is a no-op when no path exists.
set_position sets coordinates, copies another entity's position, or uses null
to remove an entity from rendering while preserving its properties. repeat rechecks
its condition after each complete child-effect pass, cannot nest, and shares the
100-effect turn limit with direct and automatic effects. References beginning with $
resolve a matching action parameter. Directions are UP, RIGHT, DOWN, or LEFT.

Automatic rules run once in declared order after every well-formed action attempt,
and effects run sequentially. Possession, access, pushing, triggering, and repeated
movement must be composed from generic operations; none is a runtime mechanic.
Failures are exact generated predicates checked after automatic rules and before
objectives; failure wins if final success is also true in that turn.

Objectives are ordered and no objective may be true initially. Supply a proposed
solution that deterministically reaches success. If the request cannot be represented
exactly, return unsupported; never approximate. Interpretation remains visible,
fallible model judgment.

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


@dataclass(frozen=True)
class StructuredResponseTrace:
    name: str
    schema: JsonObject
    output: JsonObject | None
    error: str | None = None


class OpenAIProvider:
    """One provider adapter used for stateless builder and acting calls."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        client: Any | None = None,
        structured_response_observer: Callable[[StructuredResponseTrace], None] | None = None,
    ) -> None:
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise MissingCredential("OPENAI_API_KEY is required for live generation and acting")
            from openai import OpenAI

            client = OpenAI()
        self._client = client
        self._model = model
        self._structured_response_observer = structured_response_observer

    def generate_build(self, request: BuildRequest) -> JsonObject:
        payload = {
            "original_prompt": request.original_prompt,
            "frozen_interpretation": request.frozen_interpretation,
            "previous_response": request.previous_response,
            "diagnostics": [diagnostic.__dict__ for diagnostic in request.diagnostics],
        }
        manifest = self._structured_response(
            MANIFEST_INSTRUCTIONS,
            json.dumps(payload, sort_keys=True),
            name="builder_manifest",
            schema=MANIFEST_SCHEMA,
        )
        validate_manifest(manifest)
        response = self._structured_response(
            BUILDER_INSTRUCTIONS,
            json.dumps({"build_request": payload, "manifest": manifest}, sort_keys=True),
            name=(
                "generated_build_response"
                if manifest["plan"]["status"] == "generated"
                else "unsupported_build_response"
            ),
            schema=build_response_schema(manifest),
        )
        mismatch = manifest_mismatch(response, manifest)
        if mismatch is not None:
            raise CandidateRejected(
                response,
                Diagnostic("shape", "MANIFEST_DRIFT", "manifest", mismatch),
            )
        return response

    def choose_action(self, observation: JsonObject) -> JsonObject:
        return self._json_response(ACTOR_INSTRUCTIONS, json.dumps(observation, sort_keys=True))

    def _structured_response(
        self,
        instructions: str,
        input_text: str,
        *,
        name: str,
        schema: JsonObject,
    ) -> JsonObject:
        try:
            response = self._client.responses.create(
                model=self._model,
                instructions=instructions,
                input=input_text,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": name,
                        "strict": True,
                        "schema": schema,
                    }
                },
                store=False,
            )
            output = self._decoded_object(response.output_text)
        except Exception as error:
            if self._structured_response_observer is not None:
                self._structured_response_observer(
                    StructuredResponseTrace(
                        name,
                        copy.deepcopy(schema),
                        None,
                        str(error),
                    )
                )
            raise
        if self._structured_response_observer is not None:
            self._structured_response_observer(
                StructuredResponseTrace(
                    name,
                    copy.deepcopy(schema),
                    copy.deepcopy(output),
                )
            )
        return output

    def _json_response(self, instructions: str, input_text: str) -> JsonObject:
        response = self._client.responses.create(
            model=self._model,
            instructions=instructions,
            input="Return one JSON object for this request:\n" + input_text,
            text={"format": {"type": "json_object"}},
            store=False,
        )
        return self._decoded_object(response.output_text)

    @staticmethod
    def _decoded_object(output_text: str) -> JsonObject:
        value = json.loads(output_text)
        if not isinstance(value, dict):
            raise ValueError("provider response must be a JSON object")
        return value
