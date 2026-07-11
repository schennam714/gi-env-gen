from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Any

from jsonschema import Draft202012Validator

from gi_env_gen.builder import AcceptedBuild, GenerationFailed, ProviderFailed, UnsupportedBuild, build
from gi_env_gen.openai_provider import DEFAULT_MODEL, OpenAIProvider, StructuredResponseTrace

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
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Include complete structured responses, schemas, and validation replay evidence.",
    )
    args = parser.parse_args()
    structured_responses: list[StructuredResponseTrace] = []
    provider = OpenAIProvider(
        model=args.model,
        structured_response_observer=structured_responses.append if args.trace else None,
    )
    results: list[CaseResult] = []
    case_reports: list[dict[str, Any]] = []
    trace_schema_failed = False
    selected_cases = args.case or list(CASES)
    for case in selected_cases:
        prompt = CASES[case]
        trace_start = len(structured_responses)
        result = build(prompt, provider)
        if isinstance(result, AcceptedBuild):
            outcome = "first_attempt" if len(result.attempts) == 1 else "repaired"
            case_result = CaseResult(case, outcome, len(result.attempts), None)
        elif isinstance(result, UnsupportedBuild):
            case_result = CaseResult(case, "unsupported", len(result.attempts), result.reason)
        elif isinstance(result, GenerationFailed):
            case_result = CaseResult(case, "exhausted", len(result.attempts), result.reason)
        else:
            assert isinstance(result, ProviderFailed)
            case_result = CaseResult(case, "provider_failure", len(result.attempts), result.reason)
        results.append(case_result)
        case_report = asdict(case_result)
        if args.trace:
            trace = _trace_report(
                prompt,
                result,
                structured_responses[trace_start:],
            )
            case_report["trace"] = trace
            trace_schema_failed = trace_schema_failed or trace["schema_error_count"] > 0
        case_reports.append(case_report)
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
                "cases": case_reports,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if counts["provider_failure"] == 0 and not trace_schema_failed else 1


def _trace_report(
    prompt: str,
    result: AcceptedBuild | UnsupportedBuild | GenerationFailed | ProviderFailed,
    structured_responses: list[StructuredResponseTrace],
) -> dict[str, Any]:
    response_reports = [
        _structured_response_report(response) for response in structured_responses
    ]
    report: dict[str, Any] = {
        "prompt": prompt,
        "physical_openai_calls": len(structured_responses),
        "schema_error_count": sum(
            response["schema_error_count"]
            for response in response_reports
            if isinstance(response["schema_error_count"], int)
        ),
        "structured_responses": response_reports,
        "build_attempts": [
            {
                "response": attempt.response,
                "diagnostics": [asdict(diagnostic) for diagnostic in attempt.diagnostics],
            }
            for attempt in result.attempts
        ],
    }
    if isinstance(result, AcceptedBuild):
        report["validation_outcome"] = {
            "status": "accepted",
            "frozen_environment_hash": result.environment.content_hash,
        }
        report["private_validation_evidence"] = {
            "proposed_solution": list(result.validation.solution),
            "replay": [asdict(transition) for transition in result.validation.replay],
            "final_state": asdict(result.validation.replay[-1].state),
            "never_sent_to_acting_llm": True,
        }
    elif isinstance(result, UnsupportedBuild):
        report["validation_outcome"] = {
            "status": "unsupported",
            "reason": result.reason,
        }
    elif isinstance(result, GenerationFailed):
        report["validation_outcome"] = {
            "status": "generation_failed",
            "reason": result.reason,
            "diagnostics": [asdict(diagnostic) for diagnostic in result.diagnostics],
        }
    else:
        report["validation_outcome"] = {
            "status": "provider_failed",
            "reason": result.reason,
        }
    return report


def _structured_response_report(response: StructuredResponseTrace) -> dict[str, Any]:
    if response.output is None:
        return {
            "name": response.name,
            "schema": response.schema,
            "output": None,
            "error": response.error,
            "schema_error_count": None,
            "schema_errors": [],
        }
    errors = sorted(
        Draft202012Validator(response.schema).iter_errors(response.output),
        key=lambda error: list(error.absolute_path),
    )
    return {
        "name": response.name,
        "schema": response.schema,
        "output": response.output,
        "schema_error_count": len(errors),
        "schema_errors": [
            {
                "path": list(error.absolute_path),
                "message": error.message,
            }
            for error in errors
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
