# Tickets: LLM-Authored Executable 2D Environments

These tracer-bullet tickets build the prompt-to-program, deterministic validation, and independent acting flow defined in [PRD.md](PRD.md). Each mechanic named below is an example generated program used to exercise generic operations; it is not a mechanic to hardcode into the runtime.

Work the **frontier**: any ticket whose blockers are all complete. Tickets that add independent rule-language capabilities may proceed in parallel once their shared runtime foundation is complete.

## Generate and play a minimal rule-authored reach world

**What to build:** A reviewer can submit a simple reach-the-exit prompt, receive a fresh LLM-authored ASCII environment whose movement action and reach objective are defined in the environment program, validate its proposed solution, freeze it, and watch a separate LLM act through the deterministic runtime.

**Blocked by:** None — can start immediately.

- [x] Select one version-one provider and require its credential for live builder and acting calls.
- [x] Accept the generated/unsupported build-response shapes and the minimal environment-program shape.
- [x] Load a rectangular ASCII map, infer entity positions from legend tokens, and identify the generated actor reference.
- [x] Interpret the generic at, can_move, and move operations without providing a fixed player action name.
- [x] Let the builder define its movement action, parameters, applicability, effects, ordered reach objective, and proposed solution.
- [x] Reject an objective already satisfied at reset and replay the proposed solution through the runtime before acceptance.
- [x] Split private solution evidence from the frozen environment and identify the environment with a content hash.
- [x] Give a separate acting LLM the full current observation and a deterministic rendering of the generated action rule.
- [x] Apply one acting action per normal model call until generated success or the step limit.
- [x] Prove the vertical slice with provider fakes and document one credentialed smoke path without presenting fixtures as generated output.



## Repair rejected programs and stop unsupported requests

**What to build:** The builder can inspect deterministic validation errors and repair an invalid environment program without weakening its declared interpretation, while genuinely unsupported requests stop clearly.

**Blocked by:** Generate and play a minimal rule-authored reach world.

- [x] Return path-specific shape, reference, initial-state, and solution-replay diagnostics.
- [x] Send the original prompt, complete previous response, and diagnostics to the next builder attempt.
- [x] Freeze the first structurally valid interpretation and reject later attempts that change it.
- [x] Require every repair attempt to return a complete independently traceable build response.
- [x] Stop after three failed attempts with generation-failure attribution.
- [x] Stop immediately on an unsupported response and show the builder's interpretation and reason.
- [x] Never silently apply an approximation or let deterministic code repair map geometry or rules.
- [x] Cover successful repair, interpretation drift, retry exhaustion, provider failure, and unsupported output with provider fakes.



## Generate a state-changing push-and-trigger puzzle

**What to build:** From a pressure-plate-style prompt, the builder authors a new map, a parameterized push action, an automatic state-changing rule, ordered code-level objectives, and a successful solution using only generic rule operations.

**Blocked by:** Repair rejected programs and stop unsupported requests.

- [x] Require every generated entity to declare symbol as a string and solid as a boolean. Preserve any additional builder-chosen boolean, number, string, or null properties so generated rules can read and change them; do not predefine names such as movable or open.
- [x] For a generated action invocation, type-check its declared entity and direction arguments and replace matching $parameter references inside that action's conditions and effects.
- [x] Implement adjacent as orthogonal adjacency, optionally constrained by direction, and property_equals as equality against an entity's current declared property.
- [x] Apply generated effects in array order, so one effect may move a target away before the next effect moves another entity into the vacated cell.
- [x] Implement set_property by changing one current entity property and emit by recording an exact event. Do not add runtime functions or branches named for pushing, crates, plates, or gates.
- [x] After each well-formed action attempt, evaluate every generated after_action rule once in array order. Later rules see earlier changes, and the rule list does not restart.
- [x] After automatic rules finish, permanently complete the next ordered objective when its condition is true, then continue through any immediately true consecutive objectives.
- [x] Render each positioned entity using its current symbol property and make can_move use its current solid property, so generated property changes affect both display and collision.
- [x] Validate the builder's generated push/trigger solution and run the same frozen environment with the separate acting LLM through the existing runtime start and step interfaces.



## Generate possession and prerequisite mechanics

**What to build:** From a retrieval-and-prerequisite prompt, the builder authors possession, access, relocation, and completion rules from entity properties and positions rather than using built-in inventory, key, door, or pickup behavior.

**Blocked by:** Generate a state-changing push-and-trigger puzzle.

- [x] Interpret set_position for exact coordinates, another entity's position, and null.
- [x] Remove null-position entities from rendering while retaining their properties in authoritative state.
- [x] Allow generated actions to express possession through builder-chosen properties such as held_by.
- [x] Allow a generated access action to test possession and change an obstacle's properties.
- [x] Validate that every generated property and entity reference exists and has a compatible type.
- [x] Prove a generated prerequisite solution through replay without any runtime branch named for inventory, keys, doors, or collection.
- [x] Show the acting LLM off-map entities and relevant properties in its complete current observation.



## Generate bounded repeated movement

**What to build:** From an ice or conveyor prompt, the builder authors an action that repeatedly applies generic effects while a condition holds, and the runtime executes it deterministically within a strict limit.

**Blocked by:** Generate a state-changing push-and-trigger puzzle.

- [ ] Interpret all, any, and not condition composition.
- [ ] Interpret repeat with condition re-evaluation after each child-effect pass.
- [ ] Reject nested repeat.
- [ ] Enforce at most 100 total effect applications across the action and its after-action rules.
- [ ] Attribute limit exhaustion to the generated environment program rather than the acting policy.
- [ ] Replay a generated sliding solution and show every intermediate state change in validation evidence.
- [ ] Prove through tests that repeated movement is expressed by generated rules rather than a runtime slide mechanic.



## Generate autonomous threats and exact failures

**What to build:** From a moving-threat prompt, the builder authors automatic pursuit and a code-level failure predicate, while acting mistakes and generated-program failures remain distinguishable.

**Blocked by:** Generate a state-changing push-and-trigger puzzle.

- [ ] Interpret move_toward as one traversable shortest-path step with fixed UP, RIGHT, DOWN, LEFT tie breaking.
- [ ] Treat no path for move_toward as a deterministic no-op.
- [ ] Run autonomous generated rules after applicable and inapplicable well-formed action attempts.
- [ ] Check generated failures after automatic rules and before objective completion.
- [ ] Make failure win when failure and final success become true in the same turn.
- [ ] Reject a proposed solution that triggers any generated failure predicate.
- [ ] Render autonomous entity movement and record it separately from the acting action's direct effects.
- [ ] Prove a generated pursuit environment without adding ghost, enemy, hazard, or chase branches to the runtime.



## Generate value-driven timed environments

**What to build:** From an oxygen, time, energy, or similar prompt, the builder authors numeric state, automatic changes, comparisons, and terminal conditions using generic value operations.

**Blocked by:** Generate a state-changing push-and-trigger puzzle.

- [ ] Load declared global scalar values into runtime state.
- [ ] Interpret set_value and change_value with numeric type checks.
- [ ] Interpret eq, ne, lt, lte, gt, and gte value comparisons.
- [ ] Expose current generated values in every acting observation.
- [ ] Let generated after-action rules update values after inapplicable action attempts.
- [ ] Replay a generated time-limited solution that succeeds before its generated failure condition.
- [ ] Reject value operations with unknown values, incompatible types, or invalid parameter references.
- [ ] Prove the feature without adding oxygen, timer, health, battery, or resource branches to the runtime.



## Compose the complete rule language in one generated environment

**What to build:** A single prompt can produce and run a mixed-mechanics environment that combines spatial rules, properties, possession, repetition, autonomous changes, values, events, objectives, and failures without new environment-specific runtime code.

**Blocked by:** Generate possession and prerequisite mechanics; Generate bounded repeated movement; Generate autonomous threats and exact failures; Generate value-driven timed environments.

- [ ] Interpret event_occurred at current-step and episode scope.
- [ ] Use generated events in at least one code-level objective or failure predicate.
- [ ] Validate unique action, trigger, objective, failure, entity, and value IDs across the complete program.
- [ ] Validate all operation-specific fields, parameter references, and scalar types before replay.
- [ ] Replay the builder's mixed-mechanics solution through the same frozen environment later used for acting.
- [ ] Deterministically render the complete generated action set for the acting LLM on every turn.
- [ ] Keep the proposed solution and builder conversation absent from every acting request.
- [ ] Demonstrate generated success and at least one separate validation-passed but acting-failed rollout through provider fakes.
- [ ] Confirm that adding the mixed environment required no interpreter branch named after its scenario or mechanics.



## Persist evidence and ship the reviewer CLI

**What to build:** A reviewer can run freeform prompts, inspect the accepted program and proof, watch independent acting, and save machine-readable evidence that keeps generation, validation, and acting claims separate.

**Blocked by:** Compose the complete rule language in one generated environment.

- [ ] Require a freeform prompt and expose model and maximum-step configuration without generation-mode or mechanic selectors.
- [ ] Fail immediately and clearly when the selected provider credential is missing.
- [ ] Show interpretation, generated program, validation outcome, frozen hash, acting transitions, objectives, failures, and final status as distinct sections.
- [ ] Save builder attempts and diagnostics without private chain-of-thought.
- [ ] Save the accepted environment separately from the private proposed-solution replay.
- [ ] Save each acting observation, response attempt, action, applicability result, direct effects, automatic effects, events, objective changes, and resulting state.
- [ ] Distinguish unsupported, provider failure, invalid generated program, retry exhaustion, unusable actor output, generated failure, step limit, and success.
- [ ] Document that interpretation is model judgment while state execution and objective evaluation are deterministic.
- [ ] Provide one offline test command using provider fakes and one concise credentialed quickstart.
- [ ] Confirm the repository contains no catalog of user-facing maps or complete mechanics.
