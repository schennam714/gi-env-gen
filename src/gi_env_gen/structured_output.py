from __future__ import annotations

from typing import Any, Mapping, Sequence, cast

from .model import JsonObject

SCALAR_SCHEMA: JsonObject = {"type": ["boolean", "number", "string", "null"]}
CONDITION_OPERATIONS = frozenset(
    {
        "all",
        "any",
        "not",
        "at",
        "adjacent",
        "can_move",
        "property_equals",
        "value_compare",
        "event_occurred",
    }
)
NON_REPEAT_EFFECT_OPERATIONS = frozenset(
    {"move", "move_toward", "set_position", "set_property", "set_value", "change_value", "emit"}
)
EFFECT_OPERATIONS = NON_REPEAT_EFFECT_OPERATIONS | {"repeat"}


def _strict_object_schema(properties: Mapping[str, Any]) -> JsonObject:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(properties),
        "additionalProperties": False,
    }


def _string_const(value: Any) -> JsonObject:
    return {"type": "string", "const": value}


def _interpretation_schema() -> JsonObject:
    return {
        "type": "array",
        "minItems": 1,
        "items": {"type": "string", "minLength": 1},
    }


_PARAMETER_MANIFEST_SCHEMA = _strict_object_schema(
    {
        "name": {"type": "string", "minLength": 1},
        "type": {"type": "string", "enum": ["direction", "entity", "number", "string"]},
    }
)
_ENTITY_MANIFEST_SCHEMA = _strict_object_schema(
    {
        "token": {"type": "string", "pattern": r"^[^#.\n\r]$"},
        "id": {"type": "string", "minLength": 1},
        "properties": {
            "type": "array",
            "minItems": 2,
            "items": {"type": "string", "minLength": 1},
        },
    }
)
_ACTION_MANIFEST_SCHEMA = _strict_object_schema(
    {
        "name": {"type": "string", "minLength": 1},
        "parameters": {
            "type": "array",
            "items": _PARAMETER_MANIFEST_SCHEMA,
        },
    }
)
MANIFEST_SCHEMA: JsonObject = _strict_object_schema(
    {
        "interpretation": _interpretation_schema(),
        "plan": {
            "anyOf": [
                _strict_object_schema(
                    {
                        "status": _string_const("unsupported"),
                        "reason": {"type": "string", "minLength": 1},
                    }
                ),
                _strict_object_schema(
                    {
                        "status": _string_const("generated"),
                        "entities": {
                            "type": "array",
                            "minItems": 1,
                            "items": _ENTITY_MANIFEST_SCHEMA,
                        },
                        "actions": {
                            "type": "array",
                            "minItems": 1,
                            "items": _ACTION_MANIFEST_SCHEMA,
                        },
                        "values": {"type": "array", "items": {"type": "string", "minLength": 1}},
                    }
                ),
            ]
        },
    }
)


def manifest_from_generated(response: Mapping[str, Any]) -> JsonObject:
    environment = cast(Mapping[str, Any], response["environment"])
    legend = cast(Mapping[str, Mapping[str, Any]], environment["legend"])
    actions = cast(Sequence[Mapping[str, Any]], environment["actions"])
    return {
        "interpretation": list(response["interpretation"]),
        "plan": {
            "status": "generated",
            "entities": [
                {
                    "token": token,
                    "id": declaration["id"],
                    "properties": list(cast(Mapping[str, Any], declaration["properties"])),
                }
                for token, declaration in legend.items()
            ],
            "actions": [
                {
                    "name": action["name"],
                    "parameters": [
                        {"name": name, "type": parameter_type}
                        for name, parameter_type in cast(
                            Mapping[str, str], action["parameters"]
                        ).items()
                    ],
                }
                for action in actions
            ],
            "values": list(cast(Mapping[str, Any], environment["values"])),
        },
    }


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    interpretation = manifest.get("interpretation")
    if not isinstance(interpretation, list) or not interpretation or not all(
        isinstance(item, str) and item for item in interpretation
    ):
        raise ValueError("builder manifest requires a nonempty interpretation")
    plan = manifest.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("builder manifest requires a plan")
    if plan.get("status") == "unsupported":
        if not isinstance(plan.get("reason"), str) or not plan["reason"]:
            raise ValueError("unsupported builder manifest requires a reason")
        return
    if plan.get("status") != "generated":
        raise ValueError("builder manifest status must be generated or unsupported")
    entities = plan.get("entities")
    actions = plan.get("actions")
    values = plan.get("values")
    if not isinstance(entities, list) or not entities or not isinstance(actions, list) or not actions or not isinstance(values, list):
        raise ValueError("generated builder manifest requires entities and actions")
    if not all(isinstance(value, str) and value for value in values) or len(values) != len(set(values)):
        raise ValueError("generated builder manifest value names must be unique strings")


def build_response_schema(manifest: Mapping[str, Any]) -> JsonObject:
    validate_manifest(manifest)
    plan = cast(Mapping[str, Any], manifest["plan"])
    if plan["status"] == "unsupported":
        return _strict_object_schema(
            {
                "status": _string_const("unsupported"),
                "interpretation": _interpretation_schema(),
                "reason": {"type": "string", "minLength": 1},
            }
        )
    entities = cast(list[Mapping[str, Any]], plan["entities"])
    actions = cast(list[Mapping[str, Any]], plan["actions"])
    values = cast(list[str], plan["values"])
    condition = _condition_schema()
    non_repeat = _non_repeat_effect_schema()
    effect = {
        "anyOf": [
            *cast(list[JsonObject], non_repeat["anyOf"]),
            _strict_object_schema(
                {
                    "operation": _string_const("repeat"),
                    "while": {"$ref": "#/$defs/condition"},
                    "effects": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/non_repeat_effect"},
                    },
                }
            ),
        ]
    }
    schema = _strict_object_schema(
        {
            "status": _string_const("generated"),
            "interpretation": _interpretation_schema(),
            "environment": _environment_schema(entities, actions, values),
            "solution": {
                "type": "array",
                "items": {"anyOf": [_invocation_schema(action) for action in actions]},
            },
        }
    )
    schema["$defs"] = {
        "condition": condition,
        "non_repeat_effect": non_repeat,
        "effect": effect,
    }
    return schema


def manifest_mismatch(response: Mapping[str, Any], manifest: Mapping[str, Any]) -> str | None:
    plan = cast(Mapping[str, Any], manifest["plan"])
    if response.get("status") != plan["status"]:
        return "Complete response status differs from its manifest."
    if plan["status"] == "unsupported":
        return None
    expected_entities = cast(list[Mapping[str, Any]], plan["entities"])
    expected_actions = cast(list[Mapping[str, Any]], plan["actions"])
    expected_values = cast(list[str], plan["values"])
    if len(expected_values) != len(set(expected_values)):
        return "Manifest value names must be unique."
    if not _manifest_names_are_unique(expected_entities, expected_actions):
        return "Manifest tokens, IDs, properties, actions, and parameters must be unique."
    actual = manifest_from_generated(response)
    actual_plan = cast(Mapping[str, Any], actual["plan"])
    actual_entities = cast(list[Mapping[str, Any]], actual_plan["entities"])
    actual_actions = cast(list[Mapping[str, Any]], actual_plan["actions"])
    if _entity_signature(actual_entities) != _entity_signature(expected_entities):
        return "Complete response entities and properties differ from its manifest."
    if _action_signature(actual_actions) != _action_signature(expected_actions):
        return "Complete response actions and parameters differ from its manifest."
    if set(cast(list[str], actual_plan["values"])) != set(expected_values):
        return "Complete response values differ from its manifest."
    return None


def _manifest_names_are_unique(
    entities: Sequence[Mapping[str, Any]], actions: Sequence[Mapping[str, Any]]
) -> bool:
    tokens = [entity["token"] for entity in entities]
    entity_ids = [entity["id"] for entity in entities]
    action_names = [action["name"] for action in actions]
    return (
        len(tokens) == len(set(tokens))
        and len(entity_ids) == len(set(entity_ids))
        and len(action_names) == len(set(action_names))
        and all(
            len(entity["properties"]) == len(set(entity["properties"]))
            for entity in entities
        )
        and all(
            len(action["parameters"])
            == len({parameter["name"] for parameter in action["parameters"]})
            for action in actions
        )
    )


def _entity_signature(entities: Sequence[Mapping[str, Any]]) -> dict[str, tuple[Any, frozenset[Any]]]:
    return {
        entity["token"]: (entity["id"], frozenset(entity["properties"]))
        for entity in entities
    }


def _action_signature(actions: Sequence[Mapping[str, Any]]) -> dict[str, frozenset[tuple[Any, Any]]]:
    return {
        action["name"]: frozenset(
            (parameter["name"], parameter["type"]) for parameter in action["parameters"]
        )
        for action in actions
    }


def _environment_schema(
    entities: Sequence[Mapping[str, Any]], actions: Sequence[Mapping[str, Any]], values: Sequence[str]
) -> JsonObject:
    legend: dict[str, JsonObject] = {}
    for entity in entities:
        property_names = cast(list[str], entity["properties"])
        property_schemas = {name: dict(SCALAR_SCHEMA) for name in property_names}
        property_schemas["symbol"] = {
            "type": "string",
            "pattern": r"^[ -~]$",
        }
        property_schemas["solid"] = {"type": "boolean"}
        legend[cast(str, entity["token"])] = _strict_object_schema(
            {
                "id": _string_const(entity["id"]),
                "properties": _strict_object_schema(property_schemas),
            }
        )
    return _strict_object_schema(
        {
            "actor": {"type": "string", "minLength": 1},
            "map": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "legend": _strict_object_schema(legend),
            "values": _strict_object_schema({name: dict(SCALAR_SCHEMA) for name in values}),
            "actions": {
                "type": "array",
                "minItems": 1,
                "items": {"anyOf": [_action_schema(action) for action in actions]},
            },
            "after_action": {
                "type": "array",
                "items": _strict_object_schema(
                    {
                        "id": {"type": "string", "minLength": 1},
                        "when": {
                            "type": "array",
                            "items": {"$ref": "#/$defs/condition"},
                        },
                        "effects": {
                            "type": "array",
                            "items": {"$ref": "#/$defs/effect"},
                        },
                    }
                ),
            },
            "objectives": {
                "type": "array",
                "minItems": 1,
                "items": _strict_object_schema(
                    {
                        "id": {"type": "string", "minLength": 1},
                        "description": {"type": "string", "minLength": 1},
                        "satisfied_when": {"$ref": "#/$defs/condition"},
                    }
                ),
            },
            "failures": {
                "type": "array",
                "items": _strict_object_schema(
                    {
                        "id": {"type": "string", "minLength": 1},
                        "description": {"type": "string", "minLength": 1},
                        "when": {"$ref": "#/$defs/condition"},
                    }
                ),
            },
        }
    )


def _action_schema(action: Mapping[str, Any]) -> JsonObject:
    parameters = cast(list[Mapping[str, str]], action["parameters"])
    return _strict_object_schema(
        {
            "name": _string_const(action["name"]),
            "parameters": _strict_object_schema(
                {
                    parameter["name"]: _string_const(parameter["type"])
                    for parameter in parameters
                }
            ),
            "allowed_when": {
                "type": "array",
                "items": {"$ref": "#/$defs/condition"},
            },
            "effects": {"type": "array", "items": {"$ref": "#/$defs/effect"}},
        }
    )


def _invocation_schema(action: Mapping[str, Any]) -> JsonObject:
    parameters = cast(list[Mapping[str, str]], action["parameters"])
    argument_schemas = {
        parameter["name"]: (
            {"type": "string", "enum": ["UP", "RIGHT", "DOWN", "LEFT"]}
            if parameter["type"] == "direction"
            else {"type": "number"}
            if parameter["type"] == "number"
            else {"type": "string", "minLength": 1}
        )
        for parameter in parameters
    }
    return _strict_object_schema(
        {
            "action": _string_const(action["name"]),
            "arguments": _strict_object_schema(argument_schemas),
        }
    )


def _condition_schema() -> JsonObject:
    entity_ref = {"type": "string", "minLength": 1}
    direction_ref = {"type": "string", "minLength": 1}
    return {
        "anyOf": [
            _strict_object_schema(
                {
                    "operation": _string_const("all"),
                    "conditions": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/condition"},
                    },
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("any"),
                    "conditions": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/condition"},
                    },
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("not"),
                    "condition": {"$ref": "#/$defs/condition"},
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("at"),
                    "first": entity_ref,
                    "second": entity_ref,
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("adjacent"),
                    "first": entity_ref,
                    "second": entity_ref,
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("adjacent"),
                    "first": entity_ref,
                    "second": entity_ref,
                    "direction": direction_ref,
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("can_move"),
                    "entity": entity_ref,
                    "direction": direction_ref,
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("property_equals"),
                    "entity": entity_ref,
                    "property": {"type": "string", "minLength": 1},
                    "value": dict(SCALAR_SCHEMA),
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("value_compare"),
                    "value": {"type": "string", "minLength": 1},
                    "comparator": {"type": "string", "enum": ["eq", "ne", "lt", "lte", "gt", "gte"]},
                    "expected": {"anyOf": [{"type": "number"}, {"type": "string", "pattern": r"^\$.+"}]},
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("event_occurred"),
                    "event": {"type": "string", "minLength": 1},
                    "scope": {"type": "string", "enum": ["current_step", "episode"]},
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("event_occurred"),
                    "event": {"type": "string", "minLength": 1},
                    "target": entity_ref,
                    "scope": {"type": "string", "enum": ["current_step", "episode"]},
                }
            ),
        ]
    }


def _non_repeat_effect_schema() -> JsonObject:
    entity_ref = {"type": "string", "minLength": 1}
    direction_ref = {"type": "string", "minLength": 1}
    coordinate = {
        "type": "array",
        "minItems": 2,
        "maxItems": 2,
        "items": {"type": "integer"},
    }
    return {
        "anyOf": [
            _strict_object_schema(
                {
                    "operation": _string_const("move"),
                    "entity": entity_ref,
                    "direction": direction_ref,
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("move_toward"),
                    "entity": entity_ref,
                    "target": entity_ref,
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("set_position"),
                    "entity": entity_ref,
                    "destination": {
                        "anyOf": [coordinate, entity_ref, {"type": "null"}],
                    },
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("set_property"),
                    "entity": entity_ref,
                    "property": {"type": "string", "minLength": 1},
                    "value": dict(SCALAR_SCHEMA),
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("set_value"),
                    "value": {"type": "string", "minLength": 1},
                    "new_value": dict(SCALAR_SCHEMA),
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("change_value"),
                    "value": {"type": "string", "minLength": 1},
                    "amount": {"anyOf": [{"type": "number"}, {"type": "string", "pattern": r"^\$.+"}]},
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("emit"),
                    "event": {"type": "string", "minLength": 1},
                }
            ),
            _strict_object_schema(
                {
                    "operation": _string_const("emit"),
                    "event": {"type": "string", "minLength": 1},
                    "target": entity_ref,
                }
            ),
        ]
    }
