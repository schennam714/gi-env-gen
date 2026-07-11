# GI environment generator

This first tracer bullet asks an OpenAI builder model to author a tiny ASCII reach
world, validates its proposed solution with deterministic code, freezes the accepted
program, then gives a separate acting role only the current observation. Action names,
movement rules, the map, and the objective come from the builder; the runtime only
implements the generic `at`, `can_move`, and `move` operations.

## Offline tests

Requires Python 3.11 or newer.

```sh
python -m pip install -e '.[dev]'
pytest
mypy src
```

Tests use clearly identified provider fakes. They do not present fixtures as fresh
generated output.

## Credentialed smoke path

Set an API key and submit a freeform prompt:

```sh
export OPENAI_API_KEY='...'
gi-env-gen 'Create a small maze where an explorer must reach a beacon.' --max-steps 20
```

The command uses the OpenAI Responses API and defaults to `gpt-5.6`. It prints the
builder's fallible interpretation, frozen content hash, validation status, maps, and
acting result. The proposed solution is retained as private validation evidence and is
never included in an acting observation.
