from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping

from .acting import ActingResult
from .builder import (
    AcceptedBuild,
    BuildAttempt,
    BuildResult,
    GenerationFailed,
    ProviderFailed,
    UnsupportedBuild,
)
from .model import RunModels


def save_run_evidence(
    directory: Path,
    *,
    original_prompt: str,
    models: RunModels,
    max_steps: int,
    build_result: BuildResult,
    acting_result: ActingResult | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for filename in (
        "generation.json",
        "accepted-environment.json",
        "private-validation.json",
        "acting-rollout.json",
        "summary.json",
    ):
        artifact = directory / filename
        if artifact.exists():
            artifact.unlink()
    _write_json(
        directory / "generation.json",
        {
            "original_prompt": original_prompt,
            "builder_model": models.builder,
            "max_steps": max_steps,
            "outcome": _build_outcome(build_result),
            "reason": getattr(build_result, "reason", None),
            "attempts": [
                {
                    "outcome": _attempt_outcome(attempt),
                    "response": _generation_response(attempt),
                    "diagnostics": _json_value(attempt.diagnostics),
                }
                for attempt in build_result.attempts
            ],
        },
    )
    if isinstance(build_result, AcceptedBuild):
        environment_hash = build_result.environment.content_hash
        _write_json(
            directory / "accepted-environment.json",
            {
                "environment_hash": environment_hash,
                "interpretation": list(build_result.interpretation),
                "environment": build_result.environment.program,
            },
        )
        _write_json(
            directory / "private-validation.json",
            {
                "environment_hash": environment_hash,
                "outcome": "success",
                "proposed_solution": _json_value(build_result.validation.solution),
                "replay": _json_value(build_result.validation.replay),
            },
        )
        if acting_result is not None:
            _write_json(
                directory / "acting-rollout.json",
                _acting_evidence(environment_hash, models.actor, acting_result),
            )
    final_status = acting_result.status if acting_result is not None else _build_outcome(build_result)
    _write_json(
        directory / "summary.json",
        {
            "original_prompt": original_prompt,
            "builder_model": models.builder,
            "actor_model": models.actor,
            "environment_hash": (
                build_result.environment.content_hash
                if isinstance(build_result, AcceptedBuild)
                else None
            ),
            "final_status": final_status,
            "reason": (
                acting_result.reason
                if acting_result is not None
                else getattr(build_result, "reason", None)
            ),
        },
    )


def _acting_evidence(
    environment_hash: str,
    actor_model: str,
    result: ActingResult,
) -> dict[str, Any]:
    completed_before: set[str] = set()
    steps: list[dict[str, Any]] = []
    for acting_step in result.steps:
        transition = acting_step.transition
        if transition is None:
            steps.append(
                {
                    "observation": _json_value(acting_step.observation),
                    "response_attempts": _json_value(acting_step.response_attempts),
                    "action": _json_value(acting_step.action),
                    "applicability_result": None,
                    "direct_effects": [],
                    "automatic_effects": [],
                    "events": [],
                    "objective_changes": [],
                    "resulting_state": _json_value(acting_step.resulting_state),
                }
            )
            continue
        completed_after = set(transition.state.completed_objectives)
        steps.append(
            {
                "observation": _json_value(acting_step.observation),
                "response_attempts": _json_value(acting_step.response_attempts),
                "action": _json_value(acting_step.action),
                "applicability_result": transition.applicable,
                "direct_effects": _json_value(transition.direct_effect_states),
                "automatic_effects": _json_value(transition.automatic_effect_states),
                "events": _json_value(transition.state.current_step_events),
                "objective_changes": [
                    objective
                    for objective in transition.state.completed_objectives
                    if objective not in completed_before
                ],
                "resulting_state": _json_value(transition.state),
            }
        )
        completed_before = completed_after
    return {
        "environment_hash": environment_hash,
        "actor_model": actor_model,
        "steps": steps,
        "final_status": result.status,
        "reason": result.reason,
    }


def _build_outcome(result: BuildResult) -> str:
    if isinstance(result, AcceptedBuild):
        return "accepted"
    if isinstance(result, UnsupportedBuild):
        return "unsupported"
    if isinstance(result, ProviderFailed):
        return "provider_failure"
    assert isinstance(result, GenerationFailed)
    return "retry_exhaustion"


def _attempt_outcome(attempt: BuildAttempt) -> str:
    if attempt.diagnostics:
        return "invalid_generated_program"
    return "unsupported" if attempt.response.get("status") == "unsupported" else "accepted"


def _generation_response(attempt: BuildAttempt) -> dict[str, Any]:
    return {
        key: _json_value(value)
        for key, value in attempt.response.items()
        if key != "solution"
    }


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
