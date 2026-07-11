from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .builder import AcceptedBuild
from .model import JsonObject
from .runtime import Transition, start, step


class ActingProvider(Protocol):
    def choose_action(self, observation: JsonObject) -> JsonObject: ...


@dataclass(frozen=True)
class ActingResult:
    status: Literal["success", "failure", "step_limit"]
    transitions: tuple[Transition, ...]


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
    for _ in range(max_steps):
        observation = dict(transition.observation)
        observation.update(
            {
                "original_prompt": original_prompt,
                "interpretation": list(accepted.interpretation),
                "steps_remaining": max_steps - transition.state.step,
            }
        )
        invocation = provider.choose_action(observation)
        transition = step(accepted.environment, transition.state, invocation)
        transitions.append(transition)
        if transition.state.status != "running":
            return ActingResult(transition.state.status, tuple(transitions))
    return ActingResult("step_limit", tuple(transitions))
