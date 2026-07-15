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


@dataclass(frozen=True, kw_only=True)
class ActingUpdate:
    phase: ActingUpdatePhase
    observation: JsonObject
    state: RuntimeState
    response: object | None = None
    error: str | None = None
    action: JsonObject | None = None
    transition: Transition | None = None
    status: ActingStatus | None = None


class ActingObserver(Protocol):
    def on_acting_update(self, update: ActingUpdate) -> None: ...


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


@dataclass(frozen=True, kw_only=True)
class _ActionRequestResult:
    response_attempts: tuple[ActorResponseAttempt, ...]
    invocation: JsonObject | None
    transition: Transition | None
    failure_status: ActingStatus | None = None
    reason: str | None = None


def play(
    original_prompt: str,
    accepted: AcceptedBuild,
    provider: ActingProvider,
    *,
    max_steps: int,
    updates: ActingObserver | None = None,
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
        action_request = _request_action(
            accepted,
            transition,
            observation,
            provider,
            updates,
        )
        if action_request.transition is None:
            assert action_request.failure_status is not None
            acting_steps.append(
                ActingStep(
                    copy.deepcopy(observation),
                    action_request.response_attempts,
                    copy.deepcopy(action_request.invocation),
                    None,
                    transition.state,
                )
            )
            result = ActingResult(
                action_request.failure_status,
                tuple(transitions),
                tuple(acting_steps),
                action_request.reason,
            )
            _publish_termination(updates, transition, result)
            return result
        invocation = action_request.invocation
        assert invocation is not None
        transition = action_request.transition
        transitions.append(transition)
        acting_steps.append(
            ActingStep(
                copy.deepcopy(observation),
                action_request.response_attempts,
                copy.deepcopy(invocation),
                transition,
                transition.state,
            )
        )
        _publish(
            updates,
            ActingUpdate(
                phase="after_transition",
                observation=copy.deepcopy(transition.observation),
                state=transition.state,
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


def _request_action(
    accepted: AcceptedBuild,
    current: Transition,
    observation: JsonObject,
    provider: ActingProvider,
    updates: ActingObserver | None,
) -> _ActionRequestResult:
    response_attempts: list[ActorResponseAttempt] = []
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
                phase="before_actor_request",
                observation=copy.deepcopy(attempt_observation),
                state=current.state,
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
                    phase="after_response_attempt",
                    observation=copy.deepcopy(attempt_observation),
                    state=current.state,
                    response=copy.deepcopy(error.response),
                    error=str(error),
                ),
            )
            continue
        except Exception as error:
            response_attempts.append(ActorResponseAttempt(attempt_observation, None, str(error)))
            _publish(
                updates,
                ActingUpdate(
                    phase="after_response_attempt",
                    observation=copy.deepcopy(attempt_observation),
                    state=current.state,
                    error=str(error),
                ),
            )
            return _ActionRequestResult(
                response_attempts=tuple(response_attempts),
                invocation=None,
                transition=None,
                failure_status="provider_failure",
                reason=str(error),
            )
        _publish(
            updates,
            ActingUpdate(
                phase="after_response_attempt",
                observation=copy.deepcopy(attempt_observation),
                state=current.state,
                response=copy.deepcopy(invocation),
            ),
        )
        try:
            next_transition = step(accepted.environment, current.state, invocation)
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
                    phase="response_error",
                    observation=copy.deepcopy(attempt_observation),
                    state=current.state,
                    response=copy.deepcopy(invocation),
                    error=str(error),
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
            _publish(
                updates,
                ActingUpdate(
                    phase="response_error",
                    observation=copy.deepcopy(attempt_observation),
                    state=current.state,
                    response=copy.deepcopy(invocation),
                    error=str(error),
                    action=copy.deepcopy(invocation),
                ),
            )
            return _ActionRequestResult(
                response_attempts=tuple(response_attempts),
                invocation=copy.deepcopy(invocation),
                transition=None,
                failure_status="invalid_generated_program",
                reason=str(error),
            )
        response_attempts.append(
            ActorResponseAttempt(attempt_observation, copy.deepcopy(invocation))
        )
        return _ActionRequestResult(
            response_attempts=tuple(response_attempts),
            invocation=copy.deepcopy(invocation),
            transition=next_transition,
        )
    return _ActionRequestResult(
        response_attempts=tuple(response_attempts),
        invocation=None,
        transition=None,
        failure_status="unusable_actor_output",
        reason=response_attempts[-1].error,
    )


def _publish(updates: ActingObserver | None, update: ActingUpdate) -> None:
    if updates is not None:
        try:
            updates.on_acting_update(copy.deepcopy(update))
        except Exception:
            # A read-only projection cannot alter acting or provider-call semantics.
            return


def _publish_termination(
    updates: ActingObserver | None,
    transition: Transition,
    result: ActingResult,
) -> None:
    _publish(
        updates,
        ActingUpdate(
            phase="termination",
            observation=copy.deepcopy(transition.observation),
            state=transition.state,
            error=result.reason,
            status=result.status,
        ),
    )
