from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Literal, Protocol

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
    status: Literal[
        "success",
        "generated_failure",
        "step_limit",
        "unusable_actor_output",
        "provider_failure",
        "invalid_generated_program",
    ]
    transitions: tuple[Transition, ...]
    steps: tuple[ActingStep, ...] = ()
    reason: str | None = None


def play(
    original_prompt: str,
    accepted: AcceptedBuild,
    provider: ActingProvider,
    *,
    max_steps: int,
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
                return ActingResult(
                    "provider_failure",
                    tuple(transitions),
                    tuple(acting_steps),
                    str(error),
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
                return ActingResult(
                    "invalid_generated_program",
                    tuple(transitions),
                    tuple(acting_steps),
                    str(error),
                )
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
            return ActingResult(
                "unusable_actor_output",
                tuple(transitions),
                tuple(acting_steps),
                response_attempts[-1].error,
            )
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
        if transition.state.status != "running":
            return ActingResult(
                (
                    "success"
                    if transition.state.status == "success"
                    else "generated_failure"
                ),
                tuple(transitions),
                tuple(acting_steps),
            )
    return ActingResult("step_limit", tuple(transitions), tuple(acting_steps))
