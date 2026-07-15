# GI environment generator

This harness asks a builder LLM to author a complete executable 2D environment,
proves one proposed solution with a deterministic rule runtime, freezes the accepted
program, and then asks a separate acting LLM to play it.

The central distinction is:

```text
Builder authors rules.
Runtime executes rules.
Actor chooses actions.
```

Generated action names and mechanics are data. The Python runtime knows generic
operations such as `can_move`, `move`, `set_property`, and `emit`; it does not contain
scenario branches for doors, keys, enemies, oxygen, pressure plates, or other complete
mechanics.

## Run it

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and an OpenAI API key.

```sh
cp .env.example .env
# Add OPENAI_API_KEY to .env

uv run gi-env-gen \
  'Create a small maze where an explorer must reach a beacon.' \
  --actor gpt-5.6 \
  --max-steps 20
```

The builder model is fixed to `gpt-5.6`; `--actor` selects the independent acting
model. `--evidence-dir PATH` chooses where the run artifacts are written. Without it,
the CLI creates a timestamped directory under `run-evidence/`.

The command exits clearly before making a provider call when `OPENAI_API_KEY` is
missing. Use `uv run gi-env-gen --help` for the complete CLI surface.

## Run the offline proof suite

```sh
uv run --extra dev pytest
uv run --extra dev mypy src/harness scripts/smoke_builder_matrix.py
```

The offline tests use clearly named hand-authored fixtures through provider fakes and
make no live API calls. Live builder reliability is measured separately by the
credentialed smoke path below.

## Architecture and reading order

```text
cli.py
├── builder.py ───────── bounded build/repair state machine
│   ├── openai_provider.py
│   ├── builder_schema.py
│   └── program_validation.py ── semantic checks + solution replay
├── runtime.py ───────── start/step deterministic rule interpreter
├── acting.py ────────── independent policy loop + bounded formatting recovery
├── evidence.py ──────── machine-readable proof artifacts
└── dashboard.py ─────── small facade over read-only terminal presentation
```

For a 15-minute review:

1. Read `program.py` for the generated environment vocabulary.
2. Read `builder.build(...)` for generation, repair, rejection, and acceptance.
3. Read `program_validation.validate_candidate(...)` for the acceptance proof.
4. Read `runtime.start(...)` and `runtime.step(...)` for authoritative execution.
5. Read `acting.play(...)` to see the separate actor consume observations.
6. Inspect [`examples/reach-with-energy`](examples/reach-with-energy/) for one real
   generated environment and a compact successful rollout.

The complete rule-language contract is in
[`docs/environment-program.md`](docs/environment-program.md).

## End-to-end flow

```text
natural-language prompt
  → strict builder manifest
  → strict complete build response
  → semantic validation
  → deterministic proposed-solution replay
  → frozen, content-addressed environment
  → independent acting observations and actions
  → deterministic transition/evidence trace
```

One logical builder attempt uses two strict structured-output calls. The manifest
declares builder-chosen entity, property, value, action, and parameter names. Python
uses those names to construct the strict schema for the complete response. A rejected
candidate receives a stateless repair request containing the original prompt, complete
previous response, and exact diagnostic. Generation stops after five rejected
candidates.

The first structurally valid interpretation is frozen during repair. A valid
`unsupported` response stops immediately; the harness does not weaken the request or
repair generated geometry and rules itself.

## Proof boundary

Deterministic code establishes that:

- The accepted program uses only declared generic operations and valid references.
- Its initial runtime state is valid and nonterminal.
- The builder's proposed solution reaches success through the same `start`/`step`
  interface used during acting.
- The environment is frozen and identified by a content hash before acting begins.
- Every acting state change, event, objective, and failure comes from the frozen
  program.
- The acting LLM never receives the proposed solution or builder repair context.

The builder's interpretation remains visible, fallible model judgment. Successful
replay proves one successful execution; it does not prove that the prompt was perfectly
understood, that every action sequence is sensible, or that an environment is fun or
novel.

## Evidence artifacts

An accepted run writes:

- `generation.json` — solution-redacted builder attempts and deterministic diagnostics.
- `accepted-environment.json` — interpretation, frozen program, and content hash.
- `private-validation.json` — proposed solution and deterministic replay, kept away
  from the actor.
- `acting-rollout.json` — observations, response attempts, accepted actions, direct and
  automatic effect states, events, objective changes, and resulting states.
- `summary.json` — models, environment hash, final status, and terminal reason.

Generation and acting failures write the applicable subset plus `summary.json`, with
distinct attribution for unsupported requests, provider failures, retry exhaustion,
invalid generated programs, unusable actor output, generated failure conditions, and
step limits.

## Credentialed reliability smoke path

To measure live generation across the supported generic vocabulary:

```sh
uv run python scripts/smoke_builder_matrix.py
uv run python scripts/smoke_builder_matrix.py --case bounded_repeat --trace
```

Trace mode includes strict schemas, decoded structured responses, local schema errors,
build diagnostics, frozen hashes, and private validation replay. This is live local
evidence and is separate from the offline fixture suite.
