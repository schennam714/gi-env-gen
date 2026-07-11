# GI environment generator

The harness asks an OpenAI builder model to author an ASCII environment, validates its
proposed solution with deterministic code, freezes the accepted program, then gives a
separate acting role only the current observation. Action names, rules, the map, and
objectives come from the builder; the runtime implements only the documented generic
condition and effect operations.

## Offline tests

Requires Python 3.11 or newer.

```sh
python -m pip install -e '.[dev]'
pytest
mypy src
```

Tests use clearly identified provider fakes. They do not present fixtures as fresh
generated output.

Rejected programs receive path-specific deterministic diagnostics in a stateless
repair request containing the original prompt and complete prior response. The first
structurally valid interpretation is frozen, and generation stops after three rejected
candidates. A valid `unsupported` response stops immediately and is shown with the
builder's interpretation and reason; the harness does not approximate the request or
repair generated geometry and rules itself.

The current rule language also supports builder-chosen scalar entity properties,
entity and direction action parameters, `adjacent` and `property_equals` conditions,
sequential `move`, `set_property`, and `emit` effects, and ordered after-action rules.
These are generic operations: generated actions and automatic rules compose them into
environment-specific behavior without runtime branches for complete mechanics.

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
