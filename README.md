# GI environment generator

This harness asks a builder LLM to author a complete executable 2D environment, proves one proposed solution with a deterministic rule runtime, freezes the accepted program, and then asks a separate acting LLM to play it.

## The design

Approaching open-ended environment generation requires more than asking an LLM to fill in a fixed game template. The builder must be able to invent environment-specific actions and rules by composing a small vocabulary of generic state checks and state changes. Once accepted, that model-authored composition becomes an immutable program executed by deterministic code.

```text
Builder LLM authors the nouns, actions, and rules.
                         │
                         ▼ acceptance + freeze
Deterministic runtime owns state and executes those rules.
                         │
                         ▼ observations
Actor LLM chooses among the generated actions.
```

## Environment generation walkthrough

Steps 1–6 illustrate the pipeline using this example prompt:

> Create a grid environment where an explorer must claim a token, unseal a barrier,
> then reach a beacon with a multi-cell traversal action. Each action consumes charge
> and moves a wanderer toward the explorer; fail if charge runs out after the token is
> claimed or the wanderer catches the explorer.

The illustrative shapes below show what each stage receives and produces.

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

The first structured-output call interprets the prompt and declares the names it wants to use. This lets deterministic Python construct a strict schema even though those names are dynamic.

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

The second call fills those declared names with initial state, conditions, effects, automatic rules, objectives, failures, and one proposed solution. For example, the builder expresses `CLAIM` without an inventory primitive:

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

Here, `CLAIM`, `token`, `held_by`, and `claimed` are builder-authored data. In this
fragment, the generic operations implemented by the rule runtime are `adjacent`, `property_equals`,
`set_position`, `set_property`, and `emit`.

### 3. The candidate must pass deterministic checks

The builder's response is still only a candidate. It follows this fixed path:

```text
BUILDER CANDIDATE
  -> SHAPE: required fields and types are present; no extra fields
  -> CONNECTIONS: every reference resolves; map and rules fit together
  -> FREEZE: preserve this exact program before executing it
  -> RESET: every objective and failure condition starts false
  -> REPLAY: proposed actions reach success under the generated rules
  -> ACCEPT
```

For this candidate, the connection check confirms that `CLAIM` refers to the declared `explorer`, `token`, and `held_by` names. Replay then confirms that `CLAIM` -> `ADVANCE(RIGHT)` -> `CHANGE` -> `TRAVERSE(RIGHT)` reaches the generated goal. A failed gate returns a specific diagnostic for repair; generation stops after five rejected candidates, and repair cannot silently reinterpret the request.

### 4. Acceptance exposes only the frozen program

Only a frozen candidate whose replay succeeds is accepted. A SHA-256 hash identifies the exact program, and callers receive copies so they cannot mutate the stored rules. The proposed solution is kept as private validation evidence and is never shown to the actor.

### 5. The actor sees state and chooses a generated action

`start(...)` derives runtime state from the frozen map, legend, and values. The actor receives an observation containing that state and the generated action interface, then returns only an invocation:

```json
{"action": "CLAIM", "arguments": {}}
```

### 6. The runtime matches the action to its frozen rule and updates state

For this example, there is no `CLAIM` function in the rule runtime. `CLAIM` is the name of a rule stored inside the frozen environment program from step 2. The actor's choice selects that rule by name; for actions with parameters, the supplied arguments fill the placeholders used by that rule's checks and changes.

```text
Actor chooses CLAIM
  -> find the frozen rule named CLAIM
  -> ask its conditions about the current state
       explorer adjacent to token?  yes: positions are (1, 1) and (2, 1)
       token is unclaimed?           yes: held_by is null
  -> apply the rule's effects in order
       remove token from map         position becomes null
       record who holds it           held_by becomes "explorer"
       record what happened          append a "claimed" event
  -> run the frozen program's automatic rules
       decrease charge; move wanderer toward explorer
  -> check generated failures and ordered objectives
  -> produce and record the next state
```

The runtime only understands how to read conditions and apply generic effects; the frozen rule supplies their environment-specific meaning. The direct `CLAIM` portion of the recorded transition is:

```text
positions.token:           (2, 1) -> null
properties.token.held_by:  null   -> "explorer"
current_step_events:       []     -> [{event: "claimed", target: "token"}]
```

After those direct effects, the automatic rules decrease `charge` and move the `wanderer`. The rule runtime then evaluates the builder-authored objectives and failure conditions:

- The new `claimed` event completes the first objective, `claim_token`.
- That event remains in the run history, so the final `reach_beacon` objective can
  require both reaching the beacon and having claimed the token earlier.
- The run fails if charge reaches zero after the claim or if the wanderer catches the
  explorer.

The builder chose what those events and conditions mean. The runtime only evaluates them against state, preserves completed objectives, and records each change as evidence.

## What the rule language can express

`CLAIM` is one invented mechanic. The test suite exercises several others, each composed from the runtime's generic operations. A few other examples:

| Meaning invented by the builder | Program assembled from generic operations |
| --- | --- |
| Collect a token and use it to unlock a barrier | beside token -> remove it + store `held_by`; beside sealed barrier + holding token -> unseal it |
| Push a block onto a marker to open a gate | move an adjacent movable block; after the turn, `at(block, marker)` -> make gate non-solid |
| Traverse several cells | `repeat` while `can_move` and not at goal -> `move` one cell |
| Pursuit and capture | after each turn -> `move_toward(explorer)`; fail when `at(wanderer, explorer)` |
| Limited charge | after each turn -> `change_value(-1)`; fail when charge is at most zero after `claimed` |
| Ordered milestones | `event_occurred` + `at`; completed milestones stay complete and advance in order |

None of those mechanics are defined by the rule runtime. The same primitives could describe a key, oxygen tank, sliding move, pursuing ghost, or something not anticipated by this repository. Domain meaning lives in the generated program; state authority and execution semantics live in the rule runtime.

## Scope: what to ask it to build

This version is strongest when a prompt describes a compact, turn-based 2D grid whose mechanics can be stated as discrete checks and state changes.

| Good fit | Outside current scope |
| --- | --- |
| One player-controlled entity plus automatic entities | Simultaneous control of several player entities |
| Grid movement, relocation, collection, switches, pursuit, escorting, counters, and ordered tasks | Continuous physics such as gravity, velocity, projectiles, fluids, or terrain that can be dug into or destroyed |
| Goals checked from positions, properties, values, and events | Conversation-based or visually judged goals |
| Compact turn-based maps | Large open worlds, real-time simulation, or mechanics requiring operations outside the rule language |

A useful prompt names the controlled entity, the desired interactions, the success condition, and any failure pressure. The builder is instructed to return `unsupported` instead of weakening the request; the harness stops if it receives that response.

## Evidence and limits

| Claim | Evidence |
| --- | --- |
| The deterministic pipeline validates and executes composed mechanics | The credential-free [`tests`](tests/) suite |
| A provider-generated environment was accepted and completed by an independent actor | The recorded [reach-with-energy run](examples/reach-with-energy/) |
| The builder and independent actor completed three increasingly composed live prompts | The commands and observed results below |

For every accepted program, deterministic code checks its references, starts it in a nonterminal state, and replays its proposed solution through the same runtime used by the actor. The frozen hash ties validation and acting to the same rules, while the proposed solution remains hidden from the actor.

Successful replay proves one successful execution. It does not prove that the prompt was interpreted perfectly, that every action sequence is sensible, or that an environment is fun or novel.

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

The builder model is fixed to `gpt-5.6`; `--actor` selects the independent acting model. Runs write a timestamped evidence directory under `run-evidence/` unless `--evidence-dir PATH` is supplied.

## More environments, increasing complexity

These prompts were verified live, and all three produced accepted environments and were then completed by the independent actor. Generation is model-driven, so a rerun may produce a different valid program and step count.

| Level | Generated environment | Capabilities | Actor result |
| --- | --- | --- | --- |
| 1 | Gated teleporter | A console enables relocation between two otherwise disconnected rooms | Success in 7 steps |
| 2 | Decoy infiltration | Pickup, deployment, redirected sentry movement, four ordered milestones, and capture failure | Success in 10 steps |
| 3 | Two-drone evacuation | A 15×11 maze, drones in separate rooms, two reboots, autonomous following, and a 50-turn failure budget | Success in 38 steps |

<details>
<summary>1. Gated teleporter</summary>

```sh
uv run gi-env-gen \
  "Create a small laboratory split by impassable walls. The explorer must activate a transit console while beside it, step onto an origin pad, use a generated teleport action to move to a destination pad in the otherwise unreachable section, and then reach the exit. The proposed solution must actually use the teleporter; do not leave a walkable route between the sections." \
  --actor gpt-5.6 --max-steps 25
```

</details>

<details>
<summary>2. Decoy infiltration</summary>

```sh
uv run gi-env-gen \
  "Create a compact infiltration environment where an explorer retrieves a portable signal decoy, deploys it at the explorer's current location, and uses it to draw an autonomous sentry away before reaching a data terminal and then an exit. The sentry stays still before deployment and moves one traversable step toward the active decoy after each turn. Fail if the sentry occupies the explorer's position. Represent retrieval, deployment, sentry behavior, ordered milestones, success, and failure entirely with generated state, events, conditions, and effects." \
  --actor gpt-5.6 --max-steps 45
```

</details>

<details>
<summary>3. Two-drone evacuation</summary>

```sh
uv run gi-env-gen \
  "Create a maze-like evacuation facility at least 13 cells wide and 9 cells tall, with internal walls forming multiple rooms and corridors rather than one open box. One explorer must find and separately reboot two stranded non-solid drones in different rooms. Each rebooted drone automatically moves one traversable step toward the explorer after every turn. The explorer must lead both drones to a distant evacuation pad before a numeric turn budget expires; success requires both reboot events and the explorer plus both drones at the pad. Fail if time reaches zero first. Do not move the explorer or drones with set_position; all travel must use move or move_toward. Make the proposed successful solution at least 18 action invocations." \
  --actor gpt-5.6 --max-steps 70
```

</details>

## Verify deterministic execution locally

```sh
uv run --extra dev pytest
uv run --extra dev mypy src/harness scripts/smoke_builder_matrix.py
```

These checks exercise schema validation, state transitions, and the acting loop with
known inputs and no API key. They test deterministic execution, not whether the builder
LLM can author a valid environment.

## Evidence artifacts

An accepted run writes:

- `generation.json` — solution-redacted builder attempts and deterministic diagnostics.
- `accepted-environment.json` — interpretation, frozen program, and content hash.
- `private-validation.json` — proposed solution and deterministic replay, kept away
  from the actor.
- `acting-rollout.json` — observations, accepted actions, effect states, events,
  objective changes, and resulting states.
- `summary.json` — models, environment hash, final status, and terminal reason.

Failures write the applicable subset plus `summary.json`, with attribution to
generation, provider, actor output, generated rules, or the step limit.

## Architecture and reading order

```text
src/harness/
├── cli.py ───────────── command entry point
├── program.py ───────── generated environment vocabulary
├── builder.py ───────── bounded build/repair state machine
│   ├── openai_provider.py
│   ├── builder_schema.py
│   └── program_validation.py ── semantic checks + solution replay
├── runtime.py ───────── deterministic rule interpreter
├── acting.py ────────── independent policy loop
├── evidence.py ──────── machine-readable run artifacts
└── dashboard.py ─────── terminal presentation
```

1. Read `program.py` for the generated environment vocabulary.
2. Read `builder.build(...)` for generation, repair, rejection, and acceptance.
3. Read `program_validation.validate_candidate(...)` for deterministic acceptance.
4. Read `runtime.start(...)` and `runtime.step(...)` for authoritative execution.
5. Read `acting.play(...)` for the independent actor loop.
6. Inspect [examples/reach-with-energy](examples/reach-with-energy/) for a recorded run.

The complete rule-language contract is in
[docs/environment-program.md](docs/environment-program.md).
