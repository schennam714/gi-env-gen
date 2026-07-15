"""Human-readable formatting for generated conditions and effects."""

from __future__ import annotations

import json
from typing import Mapping, Sequence


def format_rule(value: object, *, multiline: bool = False) -> str:
    """Describe a generated generic operation without interpreting scenario mechanics."""

    if isinstance(value, Mapping):
        operation = value.get("operation")
        if isinstance(operation, str):
            if operation in {"all", "any"} and isinstance(value.get("conditions"), list):
                if multiline:
                    if not value["conditions"]:
                        outcome = "Always" if operation == "all" else "Never"
                        return f"{outcome} ({operation}: no conditions)"
                    lines = [f"{operation}:"]
                    for child in value["conditions"]:
                        child_lines = format_rule(child, multiline=True).splitlines()
                        lines.append(f"  • {child_lines[0]}")
                        lines.extend(f"    {line}" for line in child_lines[1:])
                    return "\n".join(lines)
                children = "; ".join(format_rule(item) for item in value["conditions"])
                return f"{operation}: {children or 'no conditions'}"
            if operation == "not":
                if multiline:
                    child_lines = format_rule(value.get("condition"), multiline=True).splitlines()
                    return "\n".join(
                        [
                            f"not: {child_lines[0]}",
                            *(f"  {line}" for line in child_lines[1:]),
                        ]
                    )
                return f"not: {format_rule(value.get('condition'))}"
            if operation == "at":
                first = format_rule(value.get("first"))
                second = format_rule(value.get("second"))
                return f"at: {first} is at {second}"
            if operation == "adjacent":
                relation = (
                    f"{format_rule(value.get('first'))} is next to "
                    f"{format_rule(value.get('second'))}"
                )
                if "direction" in value:
                    relation += f" toward {format_rule(value['direction'])}"
                return f"adjacent: {relation}"
            if operation == "can_move":
                return (
                    f"can_move: {format_rule(value.get('entity'))} can move "
                    f"{format_rule(value.get('direction'))}"
                )
            if operation == "property_equals":
                return (
                    f"property_equals: {format_rule(value.get('entity'))}."
                    f"{format_rule(value.get('property'))} is {format_rule(value.get('value'))}"
                )
            if operation == "value_compare":
                comparators = {
                    "eq": "=",
                    "ne": "≠",
                    "lt": "<",
                    "lte": "≤",
                    "gt": ">",
                    "gte": "≥",
                }
                comparator_id = str(value.get("comparator"))
                comparator = comparators.get(comparator_id, comparator_id)
                return (
                    f"value_compare: {format_rule(value.get('value'))} {comparator} "
                    f"{format_rule(value.get('expected'))}"
                )
            if operation == "event_occurred":
                target = (
                    f" for {format_rule(value['target'])}" if "target" in value else ""
                )
                return (
                    f"event_occurred: {format_rule(value.get('event'))}{target} in "
                    f"{format_rule(value.get('scope'))}"
                )
            if operation == "move":
                return (
                    f"move: {format_rule(value.get('entity'))} moves "
                    f"{format_rule(value.get('direction'))}"
                )
            if operation == "move_toward":
                return (
                    f"move_toward: {format_rule(value.get('entity'))} moves toward "
                    f"{format_rule(value.get('target'))}"
                )
            if operation == "set_position":
                return (
                    f"set_position: {format_rule(value.get('entity'))} position ← "
                    f"{format_rule(value.get('destination'))}"
                )
            if operation == "set_property":
                return (
                    f"set_property: {format_rule(value.get('entity'))}."
                    f"{format_rule(value.get('property'))} ← {format_rule(value.get('value'))}"
                )
            if operation == "set_value":
                return (
                    f"set_value: {format_rule(value.get('value'))} ← "
                    f"{format_rule(value.get('new_value'))}"
                )
            if operation == "change_value":
                return (
                    f"change_value: {format_rule(value.get('value'))} changes by "
                    f"{format_rule(value.get('amount'))}"
                )
            if operation == "emit":
                target = (
                    f" for {format_rule(value['target'])}" if "target" in value else ""
                )
                return f"emit: event {format_rule(value.get('event'))}{target}"
            if operation == "repeat":
                effects = "; ".join(format_rule(item) for item in value.get("effects", []))
                return (
                    f"repeat: while {format_rule(value.get('while'))}; "
                    f"do {effects or 'no effects'}"
                )
            arguments = ", ".join(
                f"{key}={format_rule(item)}"
                for key, item in value.items()
                if key != "operation"
            )
            return f"{operation}({arguments})"
        return "{" + ", ".join(f"{key}={format_rule(item)}" for key, item in value.items()) + "}"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "[" + ", ".join(format_rule(item) for item in value) + "]"
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


