from __future__ import annotations

import argparse
import json
from typing import Sequence

from .acting import play
from .builder import AcceptedBuild, GenerationFailed, ProviderFailed, UnsupportedBuild, build
from .openai_provider import DEFAULT_MODEL, MissingCredential, OpenAIProvider
from .runtime import start


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate, validate, freeze, and play a 2D world.")
    parser.add_argument("prompt", help="Freeform environment request")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-steps", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        provider = OpenAIProvider(model=args.model)
    except MissingCredential as error:
        parser.error(str(error))
    result = build(args.prompt, provider)
    if isinstance(result, UnsupportedBuild):
        print("Interpretation:")
        for item in result.interpretation:
            print(f"- {item}")
        print("Unsupported:", result.reason)
        return 2
    if isinstance(result, ProviderFailed):
        print("Builder provider failure:", result.reason)
        return 5
    if isinstance(result, GenerationFailed):
        print("Generated program rejected:")
        print(json.dumps([item.__dict__ for item in result.diagnostics], indent=2))
        return 3
    assert isinstance(result, AcceptedBuild)
    print("Interpretation:")
    for item in result.interpretation:
        print(f"- {item}")
    print(f"Frozen environment: {result.environment.content_hash}")
    print(f"Private validation replay: success ({len(result.validation.replay)} steps)")
    print("Initial map:")
    print("\n".join(start(result.environment).observation["map"]))
    acting = play(args.prompt, result, provider, max_steps=args.max_steps)
    for transition in acting.transitions:
        print(f"\nStep {transition.state.step}: {transition.outcome}")
        print("\n".join(transition.observation["map"]))
    print(f"\nActing result: {acting.status}")
    return 0 if acting.status == "success" else 4


if __name__ == "__main__":
    raise SystemExit(main())
