from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .model import FrozenEnvironment, JsonObject
from .program_validation import Diagnostic as Diagnostic
from .program_validation import ValidationEvidence as ValidationEvidence
from .program_validation import validate_candidate, validate_environment_program


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
MAX_BUILD_ATTEMPTS = 5


def build(prompt: str, provider: BuilderProvider) -> BuildResult:
    attempts: list[BuildAttempt] = []
    frozen_interpretation: tuple[str, ...] | None = None
    previous_response: JsonObject | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    for _ in range(MAX_BUILD_ATTEMPTS):
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
    validated = validate_candidate(environment, solution)
    if isinstance(validated, Diagnostic):
        return GenerationFailed("validation_rejected", (validated,), ())
    return AcceptedBuild(
        tuple(response["interpretation"]),
        validated.environment,
        validated.evidence,
        (),
    )


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


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
    diagnostic = validate_environment_program(environment)
    return diagnostic is None or diagnostic.phase != "shape"
