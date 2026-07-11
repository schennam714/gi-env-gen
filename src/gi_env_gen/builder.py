from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .model import FrozenEnvironment, JsonObject, freeze_environment
from .runtime import EnvironmentProgramError, Transition, _condition, start, step


class BuilderProvider(Protocol):
    def generate_build(self, prompt: str) -> JsonObject: ...


@dataclass(frozen=True)
class Diagnostic:
    phase: str
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ValidationEvidence:
    solution: tuple[JsonObject, ...]
    replay: tuple[Transition, ...]


@dataclass(frozen=True)
class AcceptedBuild:
    interpretation: tuple[str, ...]
    environment: FrozenEnvironment
    validation: ValidationEvidence


@dataclass(frozen=True)
class UnsupportedBuild:
    interpretation: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class GenerationFailed:
    diagnostics: tuple[Diagnostic, ...]


BuildResult = AcceptedBuild | UnsupportedBuild | GenerationFailed


def build(prompt: str, provider: BuilderProvider) -> BuildResult:
    response = provider.generate_build(prompt)
    if response.get("status") == "unsupported":
        if set(response) == {"status", "interpretation", "reason"} and _strings(response.get("interpretation")) and isinstance(response.get("reason"), str):
            return UnsupportedBuild(tuple(response["interpretation"]), response["reason"])
        return _failure("shape", "INVALID_UNSUPPORTED_RESPONSE", "$", "Invalid unsupported response.")
    if response.get("status") != "generated":
        return _failure("shape", "INVALID_BUILD_RESPONSE", "status", "Expected generated or unsupported.")
    if set(response) != {"status", "interpretation", "environment", "solution"}:
        return _failure("shape", "INVALID_BUILD_RESPONSE", "$", "Generated response has unexpected or missing fields.")
    if not _strings(response.get("interpretation")):
        return _failure("shape", "INVALID_INTERPRETATION", "interpretation", "Expected non-empty strings.")
    environment = response.get("environment")
    solution = response.get("solution")
    if not isinstance(environment, dict) or not isinstance(solution, list):
        return _failure("shape", "INVALID_BUILD_RESPONSE", "$", "Missing environment or solution.")
    diagnostic = _validate_minimal_program(environment)
    if diagnostic is not None:
        return GenerationFailed((diagnostic,))
    frozen = freeze_environment(environment)
    initial = start(frozen)
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
    try:
        for index, invocation in enumerate(solution):
            transition = step(frozen, state, invocation)
            if not transition.applicable:
                return _failure(
                    "solution_replay",
                    "ACTION_INAPPLICABLE",
                    f"solution[{index}]",
                    "Proposed solution action was inapplicable.",
                )
            replay.append(transition)
            state = transition.state
    except (KeyError, TypeError, EnvironmentProgramError) as error:
        return _failure("solution_replay", "INVALID_SOLUTION", "solution", str(error))
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
    )


def _validate_minimal_program(program: JsonObject) -> Diagnostic | None:
    required = {"actor", "map", "legend", "values", "actions", "after_action", "objectives", "failures"}
    if set(program) != required:
        return Diagnostic("shape", "INVALID_ENVIRONMENT_SHAPE", "environment", "Unexpected or missing fields.")
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
    for token, declaration in legend.items():
        if not isinstance(declaration, dict) or not isinstance(declaration.get("id"), str):
            return Diagnostic("shape", "INVALID_ENTITY", f"environment.legend.{token}", "Invalid entity declaration.")
        props = declaration.get("properties")
        if not isinstance(props, dict) or set(props) != {"symbol", "solid"} or not _printable_ascii(props.get("symbol")) or type(props.get("solid")) is not bool:
            return Diagnostic("shape", "INVALID_ENTITY_PROPERTIES", f"environment.legend.{token}.properties", "symbol and solid are required.")
        ids.append(declaration["id"])
    if len(ids) != len(set(ids)) or program["actor"] not in ids:
        return Diagnostic("references", "INVALID_ACTOR_OR_ENTITY_IDS", "environment.actor", "Actor must name a unique entity.")
    if program["values"] != {} or program["after_action"] != [] or program["failures"] != []:
        return Diagnostic("shape", "OUTSIDE_MINIMAL_VOCABULARY", "environment", "This slice requires empty values, triggers, and failures.")
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
        if not isinstance(parameters, dict) or any(kind != "direction" for kind in parameters.values()):
            return Diagnostic("shape", "INVALID_PARAMETERS", path + ".parameters", "Minimal actions accept direction parameters only.")
        if not isinstance(action["allowed_when"], list) or not isinstance(action["effects"], list):
            return Diagnostic("shape", "INVALID_ACTION_RULES", path, "Conditions and effects must be arrays.")
        for condition in action["allowed_when"]:
            error = _validate_condition(condition, ids, set(parameters), path + ".allowed_when")
            if error:
                return error
        for effect in action["effects"]:
            if not isinstance(effect, dict) or effect.get("operation") != "move" or set(effect) != {"operation", "entity", "direction"}:
                return Diagnostic("shape", "INVALID_EFFECT", path + ".effects", "Only the generic move effect is supported.")
            error = _validate_entity_and_direction(effect, ids, set(parameters), path + ".effects")
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
        error = _validate_condition(objective["satisfied_when"], ids, set(), path + ".satisfied_when")
        if error:
            return error
    return None


def _validate_condition(condition: Any, ids: list[str], parameters: set[str], path: str) -> Diagnostic | None:
    if not isinstance(condition, dict) or condition.get("operation") not in {"at", "can_move"}:
        return Diagnostic("shape", "INVALID_CONDITION", path, "Only at and can_move conditions are supported.")
    expected = {"operation", "first", "second"} if condition["operation"] == "at" else {"operation", "entity", "direction"}
    if set(condition) != expected:
        return Diagnostic("shape", "INVALID_CONDITION", path, "Condition fields do not match its operation.")
    if condition["operation"] == "at":
        for key in ("first", "second"):
            if condition[key] not in ids:
                return Diagnostic("references", "UNKNOWN_ENTITY", path + "." + key, "Unknown entity reference.")
        return None
    return _validate_entity_and_direction(condition, ids, parameters, path)


def _validate_entity_and_direction(value: Mapping[str, Any], ids: list[str], parameters: set[str], path: str) -> Diagnostic | None:
    entity = value["entity"]
    direction = value["direction"]
    if entity not in ids:
        return Diagnostic("references", "UNKNOWN_ENTITY", path + ".entity", "Unknown entity reference.")
    if direction not in {"UP", "RIGHT", "DOWN", "LEFT"} and not (
        isinstance(direction, str) and direction.startswith("$") and direction[1:] in parameters
    ):
        return Diagnostic("references", "INVALID_DIRECTION_REFERENCE", path + ".direction", "Unknown direction or parameter.")
    return None


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _printable_ascii(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 1 and 0x20 <= ord(value) <= 0x7E


def _failure(phase: str, code: str, path: str, message: str) -> GenerationFailed:
    return GenerationFailed((Diagnostic(phase, code, path, message),))
