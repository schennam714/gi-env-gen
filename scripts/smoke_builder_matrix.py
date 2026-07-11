from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

from gi_env_gen.builder import AcceptedBuild, GenerationFailed, ProviderFailed, UnsupportedBuild, build
from gi_env_gen.openai_provider import DEFAULT_MODEL, OpenAIProvider

CASES = {
    "reach": "Create a small corridor where an explorer must reach a beacon.",
    "push_trigger": (
        "Create a small puzzle where an explorer moves a solid object onto a marker, "
        "which changes a barrier before the explorer reaches a goal."
    ),
    "possession_prerequisite": (
        "Create a small retrieval puzzle where the explorer must take an object off the map, "
        "record who holds it, use that prerequisite to change a barrier, and reach a goal."
    ),
    "bounded_repeat": (
        "Create a small ice-like corridor where one generated action repeatedly moves the "
        "explorer while movement remains possible and stops at the goal."
    ),
}


@dataclass(frozen=True)
class CaseResult:
    case: str
    outcome: str
    attempts: int
    detail: str | None


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure live builder outcomes by vocabulary slice.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--case", action="append", choices=sorted(CASES))
    args = parser.parse_args()
    provider = OpenAIProvider(model=args.model)
    results: list[CaseResult] = []
    selected_cases = args.case or list(CASES)
    for case in selected_cases:
        prompt = CASES[case]
        result = build(prompt, provider)
        if isinstance(result, AcceptedBuild):
            outcome = "first_attempt" if len(result.attempts) == 1 else "repaired"
            results.append(CaseResult(case, outcome, len(result.attempts), None))
        elif isinstance(result, UnsupportedBuild):
            results.append(CaseResult(case, "unsupported", len(result.attempts), result.reason))
        elif isinstance(result, GenerationFailed):
            results.append(CaseResult(case, "exhausted", len(result.attempts), result.reason))
        else:
            assert isinstance(result, ProviderFailed)
            results.append(CaseResult(case, "provider_failure", len(result.attempts), result.reason))
    counts = {
        outcome: sum(result.outcome == outcome for result in results)
        for outcome in ("first_attempt", "repaired", "unsupported", "exhausted", "provider_failure")
    }
    total = len(results)
    print(
        json.dumps(
            {
                "model": args.model,
                "total": total,
                "counts": counts,
                "rates": {key: value / total for key, value in counts.items()},
                "cases": [asdict(result) for result in results],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if counts["provider_failure"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
