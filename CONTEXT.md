# Domain Context

## Purpose

The harness turns a natural-language prompt into a newly LLM-authored executable 2D environment, validates one successful execution, freezes the environment, and lets a separate LLM act inside it while deterministic code owns state and objective truth.

## Glossary

### Builder

The LLM role that interprets the prompt and authors a complete build response. It chooses the map, entities, values, action rules, automatic rules, objectives, failures, and proposed solution.

The builder does not execute live state transitions during acting.

### Build response

The structured generated or unsupported result returned by the builder. A generated response contains interpretation, environment program, and proposed solution.

### Interpretation

The builder's visible natural-language account of the request. It is fallible model judgment, not a deterministic prompt parse or proof of complete coverage.

### Builder manifest

The first strict structured response within one logical builder attempt. It declares
builder-chosen tokens, entity and property names, actions, and parameters so code can
construct a strict schema for the complete build response. It is private authoring
context, not the authoritative build response, environment program, or acting input.

### Environment program

The declarative executable program authored by the builder. It contains the initial ASCII map, entity declarations, global values, generated action rules, after-action rules, ordered objectives, and failure predicates.

Do not use environment program to mean the builder's proposed solution or a live runtime state.

### Generic operation

One instruction implemented by the deterministic rule runtime, such as at, can_move, move, set_property, emit, or repeat.

Generic operations are deliberately below the level of complete game mechanics. PUSH, door, key, ghost, pressure plate, oxygen, and ice are not generic operations.

### Generated action

An acting-phase action authored in an environment program by composing generic conditions and effects. Its name and parameters are selected by the builder.

### After-action rule

A builder-authored rule checked once, in declared order, after each well-formed acting attempt. It represents automatic world behavior without asking an LLM to improvise the next state.

### Objective

An ordered builder-authored condition evaluated against exact runtime state and events. Once completed, an objective remains complete.

### Failure condition

A builder-authored predicate checked after action and after-action effects. A true failure condition terminates the run and takes precedence over success.

### Proposed solution

The action sequence returned by the builder as evidence that its environment can be completed. Deterministic validation replays it. It is private validation evidence and is never shown to the acting LLM.

### Validation replay

Execution of the proposed solution through the same rule-runtime interface used during acting. A successful replay proves the existence of one successful execution under the generated rules.

### Rule runtime

The deterministic module that loads an environment program, evaluates conditions, applies effects, runs after-action rules, advances objectives, checks failures, renders observations, and records transitions.

The rule runtime does not understand environment-specific mechanics by name.

### Frozen environment

An accepted immutable environment program identified by a content hash. Validation and acting records must refer to the same hash.

### Runtime state

The mutable positions, entity properties, global values, objective progress, events, step count, and terminal status produced by executing a frozen environment.

### Acting policy

The separate LLM role that receives a complete current observation and returns one invocation of a generated action. It does not receive builder conversation or the proposed solution.

### Observation

The self-contained acting input containing the original task, interpretation, rendered map, exact current state, deterministic rendering of generated actions, objective progress, failure descriptions, prior outcome, and remaining step budget.

### Code-level objective

An objective evaluated from runtime state or emitted events rather than model prose or pixels. The objective itself may be builder-authored; its evaluation is deterministic.

### Environment-program error

A failure caused by invalid generated rules or state, such as an unknown reference, illegal effect, or execution-limit exhaustion. It is distinct from an acting-policy failure.

### Inapplicable action

A well-formed generated action invocation whose allowed_when conditions are false. It consumes a turn, does not apply action effects, and still permits after-action rules to run.

### Unusable actor output

An acting response with an unknown action, missing or extra arguments, incorrect types, or malformed structure. It does not advance state and may receive bounded formatting recovery.

## Central distinction

~~~text
Builder authors rules.
Runtime executes rules.
Actor chooses actions.
~~~

Never describe the runtime as hardcoding complete environment mechanics. Never describe the builder or actor as authoritative over live state.
