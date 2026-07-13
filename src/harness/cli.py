from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .acting import play
from .builder import (
    AcceptedBuild,
    BuildResult,
    GenerationFailed,
    ProviderFailed,
    UnsupportedBuild,
    build,
)
from .evidence import save_run_evidence
from .openai_provider import DEFAULT_MODEL, MissingCredential, OpenAIProvider
from .runtime import start


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate, validate, freeze, and play a 2D world.")
    parser.add_argument("prompt", help="Freeform environment request")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-steps", type=_positive_int, default=20)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="Directory for this run's five machine-readable evidence artifacts",
    )
    args = parser.parse_args(argv)
    evidence_dir = args.evidence_dir or _default_evidence_directory()
    try:
        provider = OpenAIProvider(model=args.model)
    except MissingCredential as error:
        parser.error(str(error))
    result = build(args.prompt, provider)
    print("=== Configuration ===")
    print(f"Prompt: {args.prompt}")
    print(f"Model: {args.model}")
    print(f"Maximum steps: {args.max_steps}")
    print("=== Generation ===")
    print(f"Builder attempts: {len(result.attempts)}")
    if isinstance(result, UnsupportedBuild):
        print("=== Interpretation ===")
        for item in result.interpretation:
            print(f"- {item}")
        print("Unsupported:", result.reason)
        return _finish_without_acting(
            result,
            final_status="unsupported",
            exit_code=2,
            evidence_dir=evidence_dir,
            original_prompt=args.prompt,
            model=args.model,
            max_steps=args.max_steps,
        )
    if isinstance(result, ProviderFailed):
        print("Builder provider failure:", result.reason)
        return _finish_without_acting(
            result,
            final_status="provider_failure",
            exit_code=5,
            evidence_dir=evidence_dir,
            original_prompt=args.prompt,
            model=args.model,
            max_steps=args.max_steps,
        )
    if isinstance(result, GenerationFailed):
        print("Generated program rejected:")
        print(json.dumps([item.__dict__ for item in result.diagnostics], indent=2))
        return _finish_without_acting(
            result,
            final_status="retry_exhaustion",
            exit_code=3,
            evidence_dir=evidence_dir,
            original_prompt=args.prompt,
            model=args.model,
            max_steps=args.max_steps,
        )
    assert isinstance(result, AcceptedBuild)
    print("=== Interpretation ===")
    for item in result.interpretation:
        print(f"- {item}")
    print("=== Generated program ===")
    print(json.dumps(result.environment.program, indent=2, sort_keys=True))
    print("=== Validation ===")
    print(f"success ({len(result.validation.replay)} replay steps)")
    print("=== Frozen environment ===")
    print(result.environment.content_hash)
    print("=== Acting transitions ===")
    acting = play(args.prompt, result, provider, max_steps=args.max_steps)
    for transition in acting.transitions:
        print(f"Step {transition.state.step}: {transition.outcome}")
        print("\n".join(transition.observation["map"]))
    final_transition = acting.transitions[-1] if acting.transitions else start(result.environment)
    print("=== Objectives ===")
    print(json.dumps(final_transition.observation["objectives"], indent=2))
    print("=== Failures ===")
    print(json.dumps(final_transition.observation["failures"], indent=2))
    print("=== Final status ===")
    print(acting.status)
    save_run_evidence(
        evidence_dir,
        original_prompt=args.prompt,
        model=args.model,
        max_steps=args.max_steps,
        build_result=result,
        acting_result=acting,
    )
    print("=== Evidence ===")
    print(evidence_dir)
    return 0 if acting.status == "success" else 4


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _finish_without_acting(
    result: BuildResult,
    *,
    final_status: str,
    exit_code: int,
    evidence_dir: Path,
    original_prompt: str,
    model: str,
    max_steps: int,
) -> int:
    print("=== Final status ===")
    print(final_status)
    save_run_evidence(
        evidence_dir,
        original_prompt=original_prompt,
        model=model,
        max_steps=max_steps,
        build_result=result,
    )
    print("=== Evidence ===")
    print(evidence_dir)
    return exit_code


def _default_evidence_directory() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return Path("run-evidence") / timestamp


if __name__ == "__main__":
    raise SystemExit(main())
