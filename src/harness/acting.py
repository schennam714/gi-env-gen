from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias

from .builder import AcceptedBuild
from .model import JsonObject
from .runtime import (
    EnvironmentProgramError,
    RuntimeState,
    Transition,
    UnusableActorOutputError,
    start,
    step,
)


class ActingProvider(Protocol):
    def choose_action(self, observation: JsonObject) -> JsonObject: ...


ActingStatus: TypeAlias = Literal[
    "success",
    "generated_failure",
    "step_limit",
    "unusable_actor_output",
    "provider_failure",
    "invalid_generated_program",
]

ActingUpdatePhase: TypeAlias = Literal[
    "before_actor_request",
    "after_response_attempt",
    "response_error",
    "after_transition",
    "termination",
]


@dataclass(frozen=True)
class ActingUpdate:
    phase: ActingUpdatePhase
    observation: JsonObject
    state: RuntimeState
    response: object | None = None
    error: str | None = None
    action: JsonObject | None = None
    transition: Transition | None = None
    status: ActingStatus | None = None


class ActingUpdates(Protocol):
    def acting_updated(self, update: ActingUpdate) -> None: ...


class UnusableActorResponse(ValueError):
    def __init__(self, response: object, message: str) -> None:
        super().__init__(message)
        self.response = response


@dataclass(frozen=True)
class ActorResponseAttempt:
    observation: JsonObject
    response: object | None
    error: str | None = None


@dataclass(frozen=True)
class ActingStep:
    observation: JsonObject
    response_attempts: tuple[ActorResponseAttempt, ...]
    action: JsonObject | None
    transition: Transition | None
    resulting_state: RuntimeState


@dataclass(frozen=True)
class ActingResult:
    status: ActingStatus
    transitions: tuple[Transition, ...]
    steps: tuple[ActingStep, ...] = ()
    reason: str | None = None


def play(
    original_prompt: str,
    accepted: AcceptedBuild,
    provider: ActingProvider,
    *,
    max_steps: int,
    updates: ActingUpdates | None = None,
) -> ActingResult:
    if max_steps < 1:
        raise ValueError("max_steps must be positive")
    transition = start(accepted.environment)
    transitions: list[Transition] = []
    acting_steps: list[ActingStep] = []
    for _ in range(max_steps):
        observation = dict(transition.observation)
        observation.update(
            {
                "original_prompt": original_prompt,
                "interpretation": list(accepted.interpretation),
                "steps_remaining": max_steps - transition.state.step,
            }
        )
        response_attempts: list[ActorResponseAttempt] = []
        invocation: JsonObject | None = None
        next_transition: Transition | None = None
        for _ in range(3):
            attempt_observation = copy.deepcopy(observation)
            if response_attempts:
                previous_attempt = response_attempts[-1]
                attempt_observation["formatting_recovery"] = {
                    "previous_response": copy.deepcopy(previous_attempt.response),
                    "error": previous_attempt.error,
                }
            _publish(
                updates,
                ActingUpdate(
                    "before_actor_request",
                    copy.deepcopy(attempt_observation),
                    transition.state,
                ),
            )
            try:
                invocation = provider.choose_action(copy.deepcopy(attempt_observation))
            except UnusableActorResponse as error:
                response_attempts.append(
                    ActorResponseAttempt(
                        attempt_observation,
                        copy.deepcopy(error.response),
                        str(error),
                    )
                )
                _publish(
                    updates,
                    ActingUpdate(
                        "after_response_attempt",
                        copy.deepcopy(attempt_observation),
                        transition.state,
                        copy.deepcopy(error.response),
                        str(error),
                    ),
                )
                continue
            except Exception as error:
                response_attempts.append(
                    ActorResponseAttempt(attempt_observation, None, str(error))
                )
                acting_steps.append(
                    ActingStep(
                        copy.deepcopy(observation),
                        tuple(response_attempts),
                        None,
                        None,
                        transition.state,
                    )
                )
                result = ActingResult(
                    "provider_failure",
                    tuple(transitions),
                    tuple(acting_steps),
                    str(error),
                )
                _publish(
                    updates,
                    ActingUpdate(
                        "after_response_attempt",
                        copy.deepcopy(attempt_observation),
                        transition.state,
                        error=str(error),
                    ),
                )
                _publish_termination(updates, transition, result)
                return result
            _publish(
                updates,
                ActingUpdate(
                    "after_response_attempt",
                    copy.deepcopy(attempt_observation),
                    transition.state,
                    copy.deepcopy(invocation),
                ),
            )
            try:
                next_transition = step(accepted.environment, transition.state, invocation)
            except UnusableActorOutputError as error:
                response_attempts.append(
                    ActorResponseAttempt(
                        attempt_observation,
                        copy.deepcopy(invocation),
                        str(error),
                    )
                )
                _publish(
                    updates,
                    ActingUpdate(
                        "response_error",
                        copy.deepcopy(attempt_observation),
                        transition.state,
                        copy.deepcopy(invocation),
                        str(error),
                    ),
                )
                continue
            except EnvironmentProgramError as error:
                response_attempts.append(
                    ActorResponseAttempt(
                        attempt_observation,
                        copy.deepcopy(invocation),
                        str(error),
                    )
                )
                acting_steps.append(
                    ActingStep(
                        copy.deepcopy(observation),
                        tuple(response_attempts),
                        copy.deepcopy(invocation),
                        None,
                        transition.state,
                    )
                )
                result = ActingResult(
                    "invalid_generated_program",
                    tuple(transitions),
                    tuple(acting_steps),
                    str(error),
                )
                _publish(
                    updates,
                    ActingUpdate(
                        "response_error",
                        copy.deepcopy(attempt_observation),
                        transition.state,
                        copy.deepcopy(invocation),
                        str(error),
                        action=copy.deepcopy(invocation),
                    ),
                )
                _publish_termination(updates, transition, result)
                return result
            response_attempts.append(
                ActorResponseAttempt(
                    attempt_observation,
                    copy.deepcopy(invocation),
                )
            )
            break
        if next_transition is None:
            acting_steps.append(
                ActingStep(
                    copy.deepcopy(observation),
                    tuple(response_attempts),
                    None,
                    None,
                    transition.state,
                )
            )
            result = ActingResult(
                "unusable_actor_output",
                tuple(transitions),
                tuple(acting_steps),
                response_attempts[-1].error,
            )
            _publish_termination(updates, transition, result)
            return result
        transition = next_transition
        transitions.append(transition)
        acting_steps.append(
            ActingStep(
                copy.deepcopy(observation),
                tuple(response_attempts),
                copy.deepcopy(invocation),
                transition,
                transition.state,
            )
        )
        _publish(
            updates,
            ActingUpdate(
                "after_transition",
                copy.deepcopy(transition.observation),
                transition.state,
                action=copy.deepcopy(invocation),
                transition=transition,
            ),
        )
        if transition.state.status != "running":
            result = ActingResult(
                (
                    "success"
                    if transition.state.status == "success"
                    else "generated_failure"
                ),
                tuple(transitions),
                tuple(acting_steps),
            )
            _publish_termination(updates, transition, result)
            return result
    result = ActingResult("step_limit", tuple(transitions), tuple(acting_steps))
    _publish_termination(updates, transition, result)
    return result


def _publish(updates: ActingUpdates | None, update: ActingUpdate) -> None:
    if updates is not None:
        try:
            updates.acting_updated(copy.deepcopy(update))
        except Exception:
            # A read-only projection cannot alter acting or provider-call semantics.
            return


def _publish_termination(
    updates: ActingUpdates | None,
    transition: Transition,
    result: ActingResult,
) -> None:
    _publish(
        updates,
        ActingUpdate(
            "termination",
            copy.deepcopy(transition.observation),
            transition.state,
            error=result.reason,
            status=result.status,
        ),
    )
