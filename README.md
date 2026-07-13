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

Each logical builder attempt uses two strict structured-output calls. The first
declares builder-chosen dynamic names in a manifest; Python uses those names to create
the strict schema for the complete second response. Structural enforcement does not
replace deterministic reference checks, initial-state validation, or solution replay.

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

To measure live builder reliability across every currently supported vocabulary slice:

```sh
uv run python scripts/smoke_builder_matrix.py
```

The JSON report separates first-attempt acceptance, repaired acceptance, unsupported,
retry exhaustion, and provider failure. It is live generation evidence and is distinct
from the offline provider fixtures.

Add `--trace` to include the complete strict schema and decoded output for every
physical builder call, local JSON Schema errors, complete build attempts and
diagnostics, the frozen environment hash, and private proposed-solution replay:

```sh
uv run python scripts/smoke_builder_matrix.py --case bounded_repeat --trace
```

To verify generated numeric state and failure rules specifically:

```sh
uv run python scripts/smoke_builder_matrix.py --case timed_values --trace
```

Trace mode exits nonzero if any captured response fails its exact local schema check.
The trace is local validation evidence: its proposed solution remains under the
`private_validation_evidence` field and is never sent to the acting LLM. Compact mode
remains the default for repeated reliability measurements.

The `gpt-5.6` smoke run on 2026-07-11 accepted reach, push/trigger, and bounded-repeat
cases on their first logical attempt and accepted possession/prerequisite after one
repair: first-attempt `3/4` (`0.75`), repaired `1/4` (`0.25`), unsupported `0`,
exhausted `0`, and provider failure `0`.

The `gpt-5.6` timed-values smoke run on 2026-07-13 was accepted on its first logical
attempt with zero strict-schema errors. Its generated solution replay reached success
in four steps with one turn remaining (`e4523984c5699e1790b6eed72ea4a7b73d9802df18444c92373f0bdc2712ebdf`).
A separate full CLI run generated and froze a fresh timed environment
(`87be12f13f78ab25d42a706efe13b29b76c1db8d53d56312a2817fd9da313955`), then the
independent acting LLM reached generated success in four calls.
