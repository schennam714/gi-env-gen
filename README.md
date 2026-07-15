# GI environment generator

This harness asks a builder LLM to author a complete executable 2D environment,
proves one proposed solution with a deterministic rule runtime, freezes the accepted
program, and then asks a separate acting LLM to play it.

## The design bet

Approaching open-ended environment generation requires more than asking an LLM to
fill in a fixed game template. The builder must be able to invent
environment-specific actions and rules by composing a small vocabulary of generic
state checks and state changes. Once that composition is accepted, it must stop being
model output and become an immutable program executed by deterministic code.

```text
Builder LLM authors the nouns, actions, and rules.
                         │
                         ▼ acceptance + freeze
Deterministic runtime owns state and executes those rules.
                         │
                         ▼ observations
Actor LLM chooses among the generated actions.
```

The generated names below are not defined in Python. The runtime only implements the
generic operations used to express them:

| Meaning invented by the builder | Program assembled from generic operations |
| --- | --- |
| Possess a `token` | `adjacent` -> `set_position(null)` + `set_property(held_by)` + `emit(claimed)` |
| Traverse several cells | `repeat` while `can_move` -> `move` one cell |
| Autonomous `wanderer` | after every action -> `move_toward(explorer)` |
| Limited `charge` | after every action -> `change_value(-1)`; fail on `value_compare(lte, 0)` |
| Ordered mission | objectives query current-step or episode events and world state |

The same primitives can describe a key, oxygen tank, sliding move, pursuing ghost, or
something not anticipated by this repository. Domain meaning lives in the generated
program; state authority and execution semantics live in the runtime.

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

1. Read `program.py` for the generated environment vocabulary.
2. Read `builder.build(...)` for generation, repair, rejection, and acceptance.
3. Read `program_validation.validate_candidate(...)` for the acceptance proof.
4. Read `runtime.start(...)` and `runtime.step(...)` for authoritative execution.
5. Read `acting.play(...)` to see the separate actor consume observations.
6. Inspect [`examples/reach-with-energy`](examples/reach-with-energy/) for one real
   generated environment and a compact successful rollout.

The complete rule-language contract is in
[`docs/environment-program.md`](docs/environment-program.md).

## One environment, top to bottom

```text
LLM AUTHORING
natural-language prompt
  -> strict manifest of builder-chosen names
  -> strict environment program + proposed solution

DETERMINISTIC ACCEPTANCE
static semantic checks -> freeze candidate -> initialize + replay -> accept

DETERMINISTIC PLAY
observe -> actor invocation -> runtime rule lookup + effects -> transition evidence
```

### 1. The builder declares its vocabulary

The first structured-output call interprets the prompt and declares the names it wants
to use. This lets Python construct a strict schema even though those names are dynamic.

```json
{
  "interpretation": ["Claim the token, change the barrier, and reach the beacon."],
  "plan": {
    "status": "generated",
    "entities": [
      {"token": "A", "id": "explorer", "properties": ["symbol", "solid"]},
      {"token": "T", "id": "token", "properties": ["symbol", "solid", "held_by"]},
      {"token": "D", "id": "barrier", "properties": ["symbol", "solid", "sealed"]},
      {"token": "E", "id": "beacon", "properties": ["symbol", "solid"]},
      {"token": "H", "id": "wanderer", "properties": ["symbol", "solid"]}
    ],
    "actions": [
      {"name": "ADVANCE", "parameters": [{"name": "heading", "type": "direction"}]},
      {"name": "CLAIM", "parameters": []},
      {"name": "CHANGE", "parameters": []},
      {"name": "TRAVERSE", "parameters": [{"name": "heading", "type": "direction"}]}
    ],
    "values": ["charge"]
  }
}
```

### 2. The builder composes a complete environment program

The second call fills those declared names with initial state, conditions, effects,
automatic rules, objectives, failures, and one proposed solution. For example, the
builder expresses `CLAIM` without an inventory primitive:

```json
{
  "name": "CLAIM",
  "allowed_when": [
    {"operation": "adjacent", "first": "explorer", "second": "token"},
    {"operation": "property_equals", "entity": "token", "property": "held_by", "value": null}
  ],
  "effects": [
    {"operation": "set_position", "entity": "token", "destination": null},
    {"operation": "set_property", "entity": "token", "property": "held_by", "value": "explorer"},
    {"operation": "emit", "event": "claimed", "target": "token"}
  ]
}
```

Here, `CLAIM`, `token`, `held_by`, and `claimed` are builder-authored data. Python
defines only `adjacent`, `property_equals`, `set_position`, `set_property`, and `emit`.

### 3. Deterministic code decides whether to accept it

Acceptance has five layers:

1. The manifest-derived JSON Schema enforces the exact response shape, declared names,
   argument types, and no extra fields.
2. Static semantic validation checks references, unique IDs, map geometry, operation
   operands, and other cross-field invariants that JSON Schema cannot express.
3. The semantically valid candidate is serialized canonically and frozen before any
   runtime execution.
4. `start(...)` derives the initial runtime state; validation rejects an objective or
   failure condition that is already true.
5. The proposed solution is replayed through the same `start`/`step` runtime used
   later. It must reach generated success without triggering a generated failure.

A rejection returns the complete prior response and one exact diagnostic for a bounded,
stateless repair attempt. The first structurally valid interpretation remains fixed;
generation stops after five rejected candidates. A valid `unsupported` response stops
immediately.

### 4. Acceptance exposes only the frozen program

Only a frozen candidate whose replay succeeds is accepted. It is content-addressed
with SHA-256 and exposed through detached copies. From this point on, neither LLM can
change its rules. The proposed solution is retained as private validation evidence and
is never shown to the actor.

### 5. The actor sees state and chooses a generated action

`start(...)` derives runtime state from the frozen map, legend, and values. The actor
receives an observation containing that state and the generated action interface, then
returns only an invocation:

```json
{"action": "CLAIM", "arguments": {}}
```

### 6. The runtime looks up the rule and owns every state change

For that invocation, `step(...)` follows one fixed path:

```text
look up actions[name == "CLAIM"]
-> validate and bind arguments
-> evaluate allowed_when against current state
   -> true:  apply direct effects in declared order
   -> false: skip direct effects; the attempt still consumes a turn
-> run after_action rules in declared order
-> evaluate failures, then ordered objectives
-> return the next state and observation
```

The direct effects above produce a trace like this:

```text
positions.token:           (2, 1) -> null
properties.token.held_by:  null   -> "explorer"
current_step_events:       []     -> [{event: "claimed", target: "token"}]
```

Then generated automatic rules decrement `charge` and move the `wanderer`. Generated
objectives can query the `claimed` event for the current step or the whole episode;
generated failures can query `charge` or whether the wanderer reached the explorer.
Each intermediate effect state and the final transition is recorded as evidence.

For example, the first generated objective recognizes the event emitted by `CLAIM`:

```json
{
  "id": "claim_token",
  "description": "Emit a claim for the token this turn.",
  "satisfied_when": {
    "operation": "event_occurred",
    "event": "claimed",
    "target": "token",
    "scope": "current_step"
  }
}
```

Once completed, that objective stays complete. Later objectives can require the
episode-level `claimed` event alongside new state, while failures such as depleted
`charge` or interception use the same condition language. The runtime understands the
conditions and their ordering, not what “claiming,” “charge,” or “interception” mean.

That is the full division of labor: the builder invents what a mechanic means, the
actor decides when to attempt it, and the runtime alone decides and records what
happens.

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
