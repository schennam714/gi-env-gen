from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, cast

from .model import FrozenEnvironment, JsonObject, freeze_environment
from .runtime import EffectLimitExceeded, EnvironmentProgramError, Transition, _condition, start, step
from .structured_output import CONDITION_OPERATIONS, EFFECT_OPERATIONS


@dataclass(frozen=True)
class Diagnostic:
    phase: str
    code: str
    path: str
    message: str


class CandidateRejected(Exception):
    def __init__(self, response: JsonObject, diagnostic: Diagnostic) -> None:
        super().__init__(diagnostic.message)
        self.response = response
        self.diagnostic = diagnostic


class BuilderProvider(Protocol):
    def generate_build(self, request: BuildRequest) -> JsonObject: ...


@dataclass(frozen=True)
class BuildRequest:
    original_prompt: str
    frozen_interpretation: tuple[str, ...] | None
    previous_response: JsonObject | None
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class BuildAttempt:
    response: JsonObject
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class ValidationEvidence:
    solution: tuple[JsonObject, ...]
    replay: tuple[Transition, ...]


@dataclass(frozen=True)
class AcceptedBuild:
    interpretation: tuple[str, ...]
    environment: FrozenEnvironment
    validation: ValidationEvidence
    attempts: tuple[BuildAttempt, ...]


@dataclass(frozen=True)
class UnsupportedBuild:
    interpretation: tuple[str, ...]
    reason: str
    attempts: tuple[BuildAttempt, ...]


@dataclass(frozen=True)
class GenerationFailed:
    reason: str
    diagnostics: tuple[Diagnostic, ...]
    attempts: tuple[BuildAttempt, ...]


@dataclass(frozen=True)
class ProviderFailed:
    reason: str
    attempts: tuple[BuildAttempt, ...]


BuildResult = AcceptedBuild | UnsupportedBuild | GenerationFailed | ProviderFailed


def build(prompt: str, provider: BuilderProvider) -> BuildResult:
    attempts: list[BuildAttempt] = []
    frozen_interpretation: tuple[str, ...] | None = None
    previous_response: JsonObject | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    for _ in range(3):
        request = BuildRequest(prompt, frozen_interpretation, previous_response, diagnostics)
        try:
            response = provider.generate_build(request)
        except CandidateRejected as error:
            diagnostics = (error.diagnostic,)
            attempts.append(BuildAttempt(error.response, diagnostics))
            previous_response = error.response
            if frozen_interpretation is None and _generated_shape_is_valid(error.response):
                frozen_interpretation = tuple(error.response["interpretation"])
            continue
        except Exception as error:
            return ProviderFailed(str(error), tuple(attempts))
        result = _validate_response(response, frozen_interpretation)
        if isinstance(result, UnsupportedBuild):
            attempt = BuildAttempt(response, ())
            return UnsupportedBuild(result.interpretation, result.reason, (*attempts, attempt))
        if isinstance(result, AcceptedBuild):
            attempt = BuildAttempt(response, ())
            return AcceptedBuild(result.interpretation, result.environment, result.validation, (*attempts, attempt))
        assert isinstance(result, GenerationFailed)
        diagnostics = result.diagnostics
        attempts.append(BuildAttempt(response, diagnostics))
        previous_response = response
        if frozen_interpretation is None and _generated_shape_is_valid(response):
            frozen_interpretation = tuple(response["interpretation"])
    return GenerationFailed("retry_exhausted", diagnostics, tuple(attempts))


def _validate_response(
    response: JsonObject, frozen_interpretation: tuple[str, ...] | None
) -> BuildResult:
    if response.get("status") == "unsupported":
        required = {"status", "interpretation", "reason"}
        if set(response) != required:
            return _field_diagnostic(response, required, "", code="INVALID_UNSUPPORTED_RESPONSE")
        if not _strings(response.get("interpretation")):
            return _failure("shape", "INVALID_UNSUPPORTED_RESPONSE", "interpretation", "Expected an array of strings.")
        if not isinstance(response.get("reason"), str):
            return _failure("shape", "INVALID_UNSUPPORTED_RESPONSE", "reason", "Expected a string.")
        if frozen_interpretation is not None and tuple(response["interpretation"]) != frozen_interpretation:
            return _interpretation_drift()
        return UnsupportedBuild(tuple(response["interpretation"]), response["reason"], ())
    if response.get("status") != "generated":
        return _failure("shape", "INVALID_BUILD_RESPONSE", "status", "Expected generated or unsupported.")
    if set(response) != {"status", "interpretation", "environment", "solution"}:
        return _field_diagnostic(response, {"status", "interpretation", "environment", "solution"}, "")
    if not _strings(response.get("interpretation")):
        return _failure("shape", "INVALID_INTERPRETATION", "interpretation", "Expected non-empty strings.")
    if frozen_interpretation is not None and tuple(response["interpretation"]) != frozen_interpretation:
        return _interpretation_drift()
    environment = response.get("environment")
    solution = response.get("solution")
    if not isinstance(environment, dict):
        return _failure("shape", "INVALID_BUILD_RESPONSE", "environment", "Environment must be an object.")
    if not isinstance(solution, list):
        return _failure("shape", "INVALID_BUILD_RESPONSE", "solution", "Solution must be an array.")
    diagnostic = _validate_environment_program(environment)
    if diagnostic is not None:
        return GenerationFailed("validation_rejected", (diagnostic,), ())
    frozen = freeze_environment(environment)
    initial = start(frozen)
    for index, failure in enumerate(environment["failures"]):
        if _condition(environment, initial.state, failure["when"], {}):
            return _failure(
                "initial_state",
                "FAILURE_SATISFIED_AT_RESET",
                f"environment.failures[{index}]",
                "Every failure must be false at reset.",
            )
    for index, objective in enumerate(environment["objectives"]):
        if _condition(environment, initial.state, objective["satisfied_when"], {}):
            return _failure(
                "initial_state",
                "OBJECTIVE_SATISFIED_AT_RESET",
                f"environment.objectives[{index}]",
                "Every objective must be incomplete at reset.",
            )
    replay: list[Transition] = []
    state = initial.state
    for index, invocation in enumerate(solution):
        try:
            transition = step(frozen, state, invocation)
        except EffectLimitExceeded as error:
            return _failure(
                "solution_replay",
                "EFFECT_LIMIT_EXCEEDED",
                f"solution[{index}]",
                str(error),
            )
        except (KeyError, TypeError, EnvironmentProgramError) as error:
            return _failure("solution_replay", "INVALID_SOLUTION", f"solution[{index}]", str(error))
        if not transition.applicable:
            return _failure(
                "solution_replay",
                "ACTION_INAPPLICABLE",
                f"solution[{index}]",
                "Proposed solution action was inapplicable.",
            )
        replay.append(transition)
        state = transition.state
        if state.status == "failure":
            return _failure(
                "solution_replay",
                "GENERATED_FAILURE",
                f"solution[{index}]",
                f"Proposed solution triggered failure {state.failure_id!r}.",
            )
    if state.status != "success":
        return _failure(
            "solution_replay",
            "OBJECTIVES_INCOMPLETE",
            "solution",
            "Proposed solution did not complete all objectives.",
        )
    return AcceptedBuild(
        tuple(response["interpretation"]),
        frozen,
        ValidationEvidence(tuple(dict(item) for item in solution), tuple(replay)),
        (),
    )


def _validate_environment_program(program: JsonObject) -> Diagnostic | None:
    required = {"actor", "map", "legend", "values", "actions", "after_action", "objectives", "failures"}
    if set(program) != required:
        failure = _field_diagnostic(program, required, "environment.")
        return Diagnostic("shape", "INVALID_ENVIRONMENT_SHAPE", failure.diagnostics[0].path, "Unexpected or missing field.")
    rows = program["map"]
    if not isinstance(rows, list) or not rows or not all(isinstance(row, str) and row for row in rows):
        return Diagnostic("shape", "INVALID_MAP", "environment.map", "Map rows must be non-empty strings.")
    if len({len(row) for row in rows}) != 1:
        return Diagnostic("shape", "NON_RECTANGULAR_MAP", "environment.map", "Map must be rectangular.")
    if any(not _printable_ascii(character) for row in rows for character in row):
        return Diagnostic("shape", "INVALID_MAP_CHARACTER", "environment.map", "Map characters must be printable ASCII.")
    legend = program["legend"]
    if not isinstance(legend, dict) or any(token in {"#", "."} or not _printable_ascii(token) for token in legend):
        return Diagnostic("shape", "INVALID_LEGEND", "environment.legend", "Legend tokens must be unique non-reserved characters.")
    source = "".join(rows)
    if any(token not in "#." and token not in legend for token in source):
        return Diagnostic("references", "UNKNOWN_MAP_TOKEN", "environment.map", "Every entity token needs a legend entry.")
    if any(source.count(token) != 1 for token in legend):
        return Diagnostic("initial_state", "LEGEND_TOKEN_COUNT", "environment.legend", "Each legend token must occur once.")
    ids: list[str] = []
    entity_properties: dict[str, set[str]] = {}
    for token, declaration in legend.items():
        if not isinstance(declaration, dict) or not isinstance(declaration.get("id"), str):
            return Diagnostic("shape", "INVALID_ENTITY", f"environment.legend.{token}", "Invalid entity declaration.")
        props = declaration.get("properties")
        if (
            not isinstance(props, dict)
            or not _printable_ascii(props.get("symbol"))
            or type(props.get("solid")) is not bool
            or any(not isinstance(name, str) or not _scalar(value) for name, value in props.items())
        ):
            return Diagnostic("shape", "INVALID_ENTITY_PROPERTIES", f"environment.legend.{token}.properties", "symbol, solid, and scalar property values are required.")
        ids.append(declaration["id"])
        entity_properties[declaration["id"]] = set(props)
    if len(ids) != len(set(ids)) or program["actor"] not in ids:
        return Diagnostic("references", "INVALID_ACTOR_OR_ENTITY_IDS", "environment.actor", "Actor must name a unique entity.")
    if not isinstance(program["values"], dict) or any(
        not isinstance(name, str) or not _scalar(value)
        for name, value in program["values"].items()
    ):
        return Diagnostic("shape", "INVALID_VALUES", "environment.values", "Values must be named scalar values.")
    values = cast(dict[str, Any], program["values"])
    if not isinstance(program["actions"], list) or not program["actions"]:
        return Diagnostic("shape", "INVALID_ACTIONS", "environment.actions", "At least one action is required.")
    action_names: set[str] = set()
    for index, action in enumerate(program["actions"]):
        path = f"environment.actions[{index}]"
        if not isinstance(action, dict) or set(action) != {"name", "parameters", "allowed_when", "effects"}:
            return Diagnostic("shape", "INVALID_ACTION", path, "Invalid action shape.")
        if not isinstance(action["name"], str) or action["name"] in action_names:
            return Diagnostic("shape", "INVALID_ACTION_NAME", path, "Action names must be unique strings.")
        action_names.add(action["name"])
        parameters = action["parameters"]
        if not isinstance(parameters, dict) or any(kind not in {"direction", "entity", "number", "string"} for kind in parameters.values()):
            return Diagnostic("shape", "INVALID_PARAMETERS", path + ".parameters", "Actions accept direction, entity, number, and string parameters.")
        if not isinstance(action["allowed_when"], list) or not isinstance(action["effects"], list):
            return Diagnostic("shape", "INVALID_ACTION_RULES", path, "Conditions and effects must be arrays.")
        for condition_index, condition in enumerate(action["allowed_when"]):
            error = _validate_condition(condition, ids, entity_properties, values, parameters, f"{path}.allowed_when[{condition_index}]")
            if error:
                return error
        for effect_index, effect in enumerate(action["effects"]):
            effect_path = f"{path}.effects[{effect_index}]"
            error = _validate_effect(effect, ids, entity_properties, values, parameters, effect_path)
            if error:
                return error
    if not isinstance(program["after_action"], list):
        return Diagnostic("shape", "INVALID_AFTER_ACTION", "environment.after_action", "After-action rules must be an array.")
    after_action_ids: set[str] = set()
    for index, rule in enumerate(program["after_action"]):
        path = f"environment.after_action[{index}]"
        if not isinstance(rule, dict) or set(rule) != {"id", "when", "effects"}:
            return Diagnostic("shape", "INVALID_AFTER_ACTION", path, "Invalid after-action rule shape.")
        if not isinstance(rule["id"], str) or rule["id"] in after_action_ids:
            return Diagnostic("shape", "INVALID_AFTER_ACTION_ID", path + ".id", "After-action IDs must be unique strings.")
        after_action_ids.add(rule["id"])
        if not isinstance(rule["when"], list) or not isinstance(rule["effects"], list):
            return Diagnostic("shape", "INVALID_AFTER_ACTION", path, "Conditions and effects must be arrays.")
        for condition_index, condition in enumerate(rule["when"]):
            error = _validate_condition(condition, ids, entity_properties, values, {}, f"{path}.when[{condition_index}]")
            if error:
                return error
        for effect_index, effect in enumerate(rule["effects"]):
            error = _validate_effect(effect, ids, entity_properties, values, {}, f"{path}.effects[{effect_index}]")
            if error:
                return error
    if not isinstance(program["objectives"], list) or not program["objectives"]:
        return Diagnostic("shape", "INVALID_OBJECTIVES", "environment.objectives", "At least one objective is required.")
    objective_ids: set[str] = set()
    for index, objective in enumerate(program["objectives"]):
        path = f"environment.objectives[{index}]"
        if not isinstance(objective, dict) or set(objective) != {"id", "description", "satisfied_when"}:
            return Diagnostic("shape", "INVALID_OBJECTIVE", path, "Invalid objective shape.")
        if not isinstance(objective["id"], str) or objective["id"] in objective_ids or not isinstance(objective["description"], str):
            return Diagnostic("shape", "INVALID_OBJECTIVE", path, "Objective IDs must be unique and descriptions textual.")
        objective_ids.add(objective["id"])
        error = _validate_condition(objective["satisfied_when"], ids, entity_properties, values, {}, path + ".satisfied_when")
        if error:
            return error
    if not isinstance(program["failures"], list):
        return Diagnostic("shape", "INVALID_FAILURES", "environment.failures", "Failures must be an array.")
    failure_ids: set[str] = set()
    for index, failure in enumerate(program["failures"]):
        path = f"environment.failures[{index}]"
        if (
            not isinstance(failure, dict)
            or set(failure) != {"id", "description", "when"}
            or not isinstance(failure["id"], str)
            or not isinstance(failure["description"], str)
            or failure["id"] in failure_ids
        ):
            return Diagnostic("shape", "INVALID_FAILURE", path, "Failure IDs must be unique and descriptions textual.")
        failure_ids.add(failure["id"])
        error = _validate_condition(failure["when"], ids, entity_properties, values, {}, path + ".when")
        if error:
            return error
    return None


def _validate_condition(
    condition: Any,
    ids: list[str],
    entity_properties: Mapping[str, set[str]],
    values: Mapping[str, Any],
    parameters: Mapping[str, Any],
    path: str,
) -> Diagnostic | None:
    if not isinstance(condition, dict) or condition.get("operation") not in CONDITION_OPERATIONS:
        return Diagnostic("shape", "INVALID_CONDITION", path, "Unsupported condition operation.")
    operation = condition["operation"]
    if operation in {"all", "any"}:
        if set(condition) != {"operation", "conditions"} or not isinstance(condition["conditions"], list):
            return Diagnostic("shape", "INVALID_CONDITION", path, "Boolean conditions require a conditions array.")
        for index, child in enumerate(condition["conditions"]):
            error = _validate_condition(
                child,
                ids,
                entity_properties,
                values,
                parameters,
                f"{path}.conditions[{index}]",
            )
            if error:
                return error
        return None
    if operation == "not":
        if set(condition) != {"operation", "condition"}:
            return Diagnostic("shape", "INVALID_CONDITION", path, "not requires exactly one condition.")
        return _validate_condition(
            condition["condition"],
            ids,
            entity_properties,
            values,
            parameters,
            path + ".condition",
        )
    if operation == "at":
        expected = {"operation", "first", "second"}
    elif operation == "adjacent":
        expected = {"operation", "first", "second"} | ({"direction"} if "direction" in condition else set())
    elif operation == "can_move":
        expected = {"operation", "entity", "direction"}
    elif operation == "property_equals":
        expected = {"operation", "entity", "property", "value"}
    else:
        expected = {"operation", "value", "comparator", "expected"}
    if set(condition) != expected:
        return Diagnostic("shape", "INVALID_CONDITION", path, "Condition fields do not match its operation.")
    if operation in {"at", "adjacent"}:
        for key in ("first", "second"):
            if not _entity_reference(condition[key], ids, parameters):
                return Diagnostic("references", "UNKNOWN_ENTITY", path + "." + key, "Unknown entity reference.")
        if operation == "adjacent" and "direction" in condition and not _direction_reference(condition["direction"], parameters):
            return Diagnostic("references", "INVALID_DIRECTION_REFERENCE", path + ".direction", "Unknown direction or parameter.")
        return None
    if operation == "can_move":
        return _validate_entity_and_direction(condition, ids, parameters, path)
    if operation == "value_compare":
        value_id = condition["value"]
        if not isinstance(value_id, str) or value_id not in values:
            return Diagnostic("references", "UNKNOWN_VALUE", path + ".value", "Unknown global value.")
        if not _numeric(values[value_id]):
            return Diagnostic("references", "INCOMPATIBLE_VALUE_TYPE", path + ".value", "Compared values must be numeric.")
        if condition["comparator"] not in {"eq", "ne", "lt", "lte", "gt", "gte"}:
            return Diagnostic("shape", "INVALID_COMPARATOR", path + ".comparator", "Unknown value comparator.")
        expected_value = condition["expected"]
        if isinstance(expected_value, str) and expected_value.startswith("$"):
            if parameters.get(expected_value[1:]) != "number":
                return Diagnostic("references", "INVALID_VALUE_REFERENCE", path + ".expected", "Expected a numeric parameter reference.")
        elif not _numeric(expected_value):
            return Diagnostic("references", "INCOMPATIBLE_VALUE_TYPE", path + ".expected", "Expected value must be numeric.")
        return None
    entity = condition["entity"]
    if not _entity_reference(entity, ids, parameters):
        return Diagnostic("references", "UNKNOWN_ENTITY", path + ".entity", "Unknown entity reference.")
    if not isinstance(condition["property"], str):
        return Diagnostic("shape", "INVALID_PROPERTY", path + ".property", "Property name must be a string.")
    if entity in ids and condition["property"] not in entity_properties[entity]:
        return Diagnostic("references", "UNKNOWN_PROPERTY", path + ".property", "Unknown entity property.")
    if (
        isinstance(entity, str)
        and entity.startswith("$")
        and not any(condition["property"] in properties for properties in entity_properties.values())
    ):
        return Diagnostic("references", "UNKNOWN_PROPERTY", path + ".property", "Unknown entity property.")
    if not _scalar_or_parameter(condition["value"], parameters):
        return Diagnostic("references", "INVALID_VALUE_REFERENCE", path + ".value", "Invalid scalar or parameter reference.")
    return None


def _validate_entity_and_direction(value: Mapping[str, Any], ids: list[str], parameters: Mapping[str, Any], path: str) -> Diagnostic | None:
    entity = value["entity"]
    direction = value["direction"]
    if not _entity_reference(entity, ids, parameters):
        return Diagnostic("references", "UNKNOWN_ENTITY", path + ".entity", "Unknown entity reference.")
    if not _direction_reference(direction, parameters):
        return Diagnostic("references", "INVALID_DIRECTION_REFERENCE", path + ".direction", "Unknown direction or parameter.")
    return None


def _validate_effect(
    effect: Any,
    ids: list[str],
    entity_properties: Mapping[str, set[str]],
    values: Mapping[str, Any],
    parameters: Mapping[str, Any],
    path: str,
    *,
    allow_repeat: bool = True,
) -> Diagnostic | None:
    if not isinstance(effect, dict) or effect.get("operation") not in EFFECT_OPERATIONS:
        return Diagnostic("shape", "INVALID_EFFECT", path, "Unsupported effect operation.")
    operation = effect["operation"]
    if operation == "repeat":
        if not allow_repeat:
            return Diagnostic("shape", "NESTED_REPEAT", path, "repeat cannot contain repeat.")
        if set(effect) != {"operation", "while", "effects"} or not isinstance(effect["effects"], list):
            return Diagnostic("shape", "INVALID_EFFECT", path, "Invalid repeat effect shape.")
        error = _validate_condition(
            effect["while"],
            ids,
            entity_properties,
            values,
            parameters,
            path + ".while",
        )
        if error:
            return error
        for index, child in enumerate(effect["effects"]):
            error = _validate_effect(
                child,
                ids,
                entity_properties,
                values,
                parameters,
                f"{path}.effects[{index}]",
                allow_repeat=False,
            )
            if error:
                return error
        return None
    if operation == "move":
        if set(effect) != {"operation", "entity", "direction"}:
            return Diagnostic("shape", "INVALID_EFFECT", path, "Invalid move effect shape.")
        return _validate_entity_and_direction(effect, ids, parameters, path)
    if operation == "move_toward":
        if set(effect) != {"operation", "entity", "target"}:
            return Diagnostic("shape", "INVALID_EFFECT", path, "Invalid move_toward effect shape.")
        for key in ("entity", "target"):
            if not _entity_reference(effect[key], ids, parameters):
                return Diagnostic("references", "UNKNOWN_ENTITY", path + "." + key, "Unknown entity reference.")
        return None
    if operation == "set_position":
        if set(effect) != {"operation", "entity", "destination"}:
            return Diagnostic("shape", "INVALID_EFFECT", path, "Invalid set_position effect shape.")
        if not _entity_reference(effect["entity"], ids, parameters):
            return Diagnostic("references", "UNKNOWN_ENTITY", path + ".entity", "Unknown entity reference.")
        destination = effect["destination"]
        if destination is None:
            return None
        if isinstance(destination, str):
            if not _entity_reference(destination, ids, parameters):
                return Diagnostic(
                    "references",
                    "UNKNOWN_ENTITY",
                    path + ".destination",
                    "Unknown entity reference.",
                )
            return None
        if (
            not isinstance(destination, list)
            or len(destination) != 2
            or any(type(coordinate) is not int for coordinate in destination)
        ):
            return Diagnostic(
                "shape",
                "INVALID_POSITION",
                path + ".destination",
                "Position must be a two-integer coordinate, entity reference, or null.",
            )
        return None
    if operation == "set_property":
        if set(effect) != {"operation", "entity", "property", "value"}:
            return Diagnostic("shape", "INVALID_EFFECT", path, "Invalid set_property effect shape.")
        entity = effect["entity"]
        if not _entity_reference(entity, ids, parameters):
            return Diagnostic("references", "UNKNOWN_ENTITY", path + ".entity", "Unknown entity reference.")
        if not isinstance(effect["property"], str):
            return Diagnostic("shape", "INVALID_PROPERTY", path + ".property", "Property name must be a string.")
        if entity in ids and effect["property"] not in entity_properties[entity]:
            return Diagnostic("references", "UNKNOWN_PROPERTY", path + ".property", "Unknown entity property.")
        if (
            isinstance(entity, str)
            and entity.startswith("$")
            and any(effect["property"] not in properties for properties in entity_properties.values())
        ):
            return Diagnostic(
                "references",
                "UNKNOWN_PROPERTY",
                path + ".property",
                "A property written through an entity parameter must exist on every possible entity target.",
            )
        if not _scalar_or_parameter(effect["value"], parameters):
            return Diagnostic("references", "INVALID_VALUE_REFERENCE", path + ".value", "Invalid scalar or parameter reference.")
        if effect["property"] == "symbol" and not _printable_ascii(effect["value"]):
            return Diagnostic("shape", "INVALID_SYMBOL_VALUE", path + ".value", "symbol must remain one printable ASCII character.")
        if effect["property"] == "solid" and type(effect["value"]) is not bool:
            return Diagnostic("shape", "INVALID_SOLID_VALUE", path + ".value", "solid must remain boolean.")
        return None
    if operation in {"set_value", "change_value"}:
        expected_fields = {"operation", "value", "new_value" if operation == "set_value" else "amount"}
        if set(effect) != expected_fields:
            return Diagnostic("shape", "INVALID_EFFECT", path, f"Invalid {operation} effect shape.")
        value_id = effect["value"]
        if not isinstance(value_id, str) or value_id not in values:
            return Diagnostic("references", "UNKNOWN_VALUE", path + ".value", "Unknown global value.")
        field = "new_value" if operation == "set_value" else "amount"
        new_value = effect[field]
        if isinstance(new_value, str) and new_value.startswith("$"):
            parameter_type = parameters.get(new_value[1:])
            required_type = "number" if operation == "change_value" else _parameter_type(values[value_id])
            if parameter_type != required_type:
                return Diagnostic("references", "INVALID_VALUE_REFERENCE", path + "." + field, "Invalid or incompatible parameter reference.")
        elif operation == "change_value":
            if not _numeric(values[value_id]) or not _numeric(new_value):
                return Diagnostic("references", "INCOMPATIBLE_VALUE_TYPE", path, "change_value requires numeric values.")
        elif not (_numeric(new_value) and _numeric(values[value_id])) and type(new_value) is not type(values[value_id]):
            return Diagnostic("references", "INCOMPATIBLE_VALUE_TYPE", path + ".new_value", "set_value must preserve the declared value type.")
        return None
    expected = {"operation", "event"} | ({"target"} if "target" in effect else set())
    if set(effect) != expected or not isinstance(effect["event"], str):
        return Diagnostic("shape", "INVALID_EFFECT", path, "Invalid emit effect shape.")
    if "target" in effect and not _entity_reference(effect["target"], ids, parameters):
        return Diagnostic("references", "UNKNOWN_ENTITY", path + ".target", "Unknown entity reference.")
    return None


def _entity_reference(value: Any, ids: list[str], parameters: Mapping[str, Any]) -> bool:
    return isinstance(value, str) and (
        value in ids or (value.startswith("$") and parameters.get(value[1:]) == "entity")
    )


def _direction_reference(value: Any, parameters: Mapping[str, Any]) -> bool:
    return isinstance(value, str) and (
        value in {"UP", "RIGHT", "DOWN", "LEFT"}
        or (value.startswith("$") and parameters.get(value[1:]) == "direction")
    )


def _scalar_or_parameter(value: Any, parameters: Mapping[str, Any]) -> bool:
    if isinstance(value, str) and value.startswith("$"):
        return value[1:] in parameters
    return _scalar(value)


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _numeric(value: Any) -> bool:
    return type(value) in {int, float}


def _parameter_type(value: Any) -> str | None:
    if _numeric(value):
        return "number"
    if isinstance(value, str):
        return "string"
    return None


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _printable_ascii(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 1 and 0x20 <= ord(value) <= 0x7E


def _failure(phase: str, code: str, path: str, message: str) -> GenerationFailed:
    return GenerationFailed("validation_rejected", (Diagnostic(phase, code, path, message),), ())


def _interpretation_drift() -> GenerationFailed:
    return _failure(
        "shape",
        "INTERPRETATION_DRIFT",
        "interpretation",
        "Repair attempts must preserve the first structurally valid interpretation exactly.",
    )


def _field_diagnostic(
    value: Mapping[str, Any], required: set[str], prefix: str, *, code: str = "INVALID_BUILD_RESPONSE"
) -> GenerationFailed:
    missing = sorted(required - set(value))
    field = missing[0] if missing else sorted(set(value) - required)[0]
    return _failure("shape", code, prefix + field, "Unexpected or missing field.")


def _generated_shape_is_valid(response: JsonObject) -> bool:
    if response.get("status") != "generated" or set(response) != {"status", "interpretation", "environment", "solution"}:
        return False
    if not _strings(response.get("interpretation")):
        return False
    environment = response.get("environment")
    if not isinstance(environment, dict) or not isinstance(response.get("solution"), list):
        return False
    diagnostic = _validate_environment_program(environment)
    return diagnostic is None or diagnostic.phase != "shape"
