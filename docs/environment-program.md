# Environment Program Reference

This document is the normative version-one contract between the builder and the deterministic rule runtime. The examples show programs the builder LLM may author. They are not mechanics implemented by the runtime.

## Builder request

~~~typescript
type BuildRequest = {
  original_prompt: string;
  frozen_interpretation: string[] | null;
  previous_response: BuildResponse | null;
  diagnostics: ValidationDiagnostic[];
};
~~~

The environment-program schema and operation semantics are static builder instructions. A repair attempt receives the complete prior response and diagnostics; it does not depend on hidden provider conversation state.

## Build response

Exactly one of these shapes is returned.

### Generated

~~~typescript
type GeneratedBuildResponse = {
  status: "generated";
  interpretation: string[];
  environment: EnvironmentProgram;
  solution: ActionInvocation[];
};
~~~

### Unsupported

~~~typescript
type UnsupportedBuildResponse = {
  status: "unsupported";
  interpretation: string[];
  reason: string;
};

type BuildResponse = GeneratedBuildResponse | UnsupportedBuildResponse;
~~~

The interpretation is an auditable model judgment. It is not a deterministic parse of the prompt.

## Environment program

~~~typescript
type Scalar = boolean | number | string | null;
type EntityId = string;
type ValueId = string;
type ObjectiveId = string;
type MapToken = string;
type Coordinate = [number, number];

type EnvironmentProgram = {
  actor: EntityId;
  map: string[];
  legend: Record<MapToken, EntityDeclaration>;
  values: Record<ValueId, Scalar>;
  actions: ActionRule[];
  after_action: TriggerRule[];
  objectives: ObjectiveRule[];
  failures: FailureRule[];
};

type EntityDeclaration = {
  id: EntityId;
  properties: {
    symbol: string;
    solid: boolean;
    [name: string]: Scalar;
  };
};
~~~

actor identifies the entity controlled by acting-phase actions. It must reference exactly one declared entity. The runtime does not require that entity to use a particular token, ID, or action vocabulary.

## Map loading

The map rules are:

1. Every row has the same nonzero length.
2. # is an impassable wall.
3. . is empty traversable floor.
4. Every other source token has exactly one legend entry.
5. Every legend token occurs exactly once in the source map.
6. Entity position is inferred from the token location.
7. Coordinates are zero-based [x, y], with x increasing rightward and y increasing downward.
8. A null runtime position means the entity is not currently on the grid.

Map tokens and rendered symbols are exactly one printable ASCII character. # and . cannot be redefined in the legend.

Unique source tokens do not restrict rendered appearance. Several entities may have the same properties.symbol even though their source tokens differ.

## Runtime state

Loading a program creates:

~~~typescript
type RuntimeState = {
  positions: Record<EntityId, Coordinate | null>;
  properties: Record<EntityId, Record<string, Scalar>>;
  values: Record<ValueId, Scalar>;
  completed_objectives: ObjectiveId[];
  current_step_events: EventRecord[];
  episode_events: EventRecord[];
  step: number;
  status: "running" | "success" | "failure";
  failure_id: string | null;
};

type EventRecord = {
  event: string;
  target: EntityId | null;
  step: number;
};
~~~

The environment program is immutable after acceptance. Runtime state is the only value changed during replay or acting.

## References and parameters

An entity reference is either a declared entity ID or an action-parameter reference beginning with $.

~~~typescript
type EntityRef = string; // entity ID or a parameter reference beginning with $
type Direction = "UP" | "RIGHT" | "DOWN" | "LEFT";
type DirectionRef = string; // direction literal or parameter reference
type ArgumentRef = string; // parameter reference beginning with $
type ScalarOrArgumentRef = Scalar | ArgumentRef;
~~~

For an invocation with arguments.target equal to crate, $target resolves to crate. Parameter references are valid only inside their declaring action.

## Conditions

~~~typescript
type Condition =
  | {
      operation: "all";
      conditions: Condition[];
    }
  | {
      operation: "any";
      conditions: Condition[];
    }
  | {
      operation: "not";
      condition: Condition;
    }
  | {
      operation: "at";
      first: EntityRef;
      second: EntityRef;
    }
  | {
      operation: "adjacent";
      first: EntityRef;
      second: EntityRef;
      direction?: DirectionRef;
    }
  | {
      operation: "can_move";
      entity: EntityRef;
      direction: DirectionRef;
    }
  | {
      operation: "property_equals";
      entity: EntityRef;
      property: string;
      value: ScalarOrArgumentRef;
    }
  | {
      operation: "value_compare";
      value: ValueId;
      comparator: "eq" | "ne" | "lt" | "lte" | "gt" | "gte";
      expected: number | ArgumentRef;
    }
  | {
      operation: "event_occurred";
      event: string;
      target?: EntityRef;
      scope: "current_step" | "episode";
    };
~~~

Condition meanings are fixed:

| Operation | Meaning |
| --- | --- |
| all | Every child condition is true. |
| any | At least one child condition is true. |
| not | The child condition is false. |
| at | Both entities have the same non-null position. |
| adjacent | Entities are orthogonally adjacent; an optional direction constrains second relative to first. |
| can_move | The next cell is in bounds, not #, and contains no solid entity. |
| property_equals | The named property exists and equals the resolved value. |
| value_compare | The named global numeric value satisfies the comparison. |
| event_occurred | A matching emitted event exists in the selected scope. |

## Effects

~~~typescript
type Effect =
  | {
      operation: "move";
      entity: EntityRef;
      direction: DirectionRef;
    }
  | {
      operation: "move_toward";
      entity: EntityRef;
      target: EntityRef;
    }
  | {
      operation: "set_position";
      entity: EntityRef;
      destination: EntityRef | Coordinate | null;
    }
  | {
      operation: "set_property";
      entity: EntityRef;
      property: string;
      value: ScalarOrArgumentRef;
    }
  | {
      operation: "set_value";
      value: ValueId;
      new_value: ScalarOrArgumentRef;
    }
  | {
      operation: "change_value";
      value: ValueId;
      amount: number | ArgumentRef;
    }
  | {
      operation: "emit";
      event: string;
      target?: EntityRef;
    }
  | {
      operation: "repeat";
      while: Condition;
      effects: NonRepeatEffect[];
    };
~~~

Effect meanings are fixed:

| Operation | Meaning |
| --- | --- |
| move | Move one grid cell. An effect that would create invalid state is an environment-program error. |
| move_toward | Move one traversable shortest-path cell toward the target; no path is a no-op; ties use UP, RIGHT, DOWN, LEFT. |
| set_position | Set an exact coordinate, copy another entity's position, or remove the entity from the map with null. |
| set_property | Replace one declared entity property. |
| set_value | Replace one declared global value. |
| change_value | Add a numeric amount to a declared numeric global value. |
| emit | Append an exact event to current-step and episode event records. |
| repeat | Re-evaluate a condition and execute non-repeat child effects while true. |

Effects run in declared order. repeat cannot contain repeat. One requested action, including its action effects and all after-action effects, may apply at most 100 effects.

## Actions

~~~typescript
type ParameterType = "direction" | "entity" | "number" | "string";

type ActionRule = {
  name: string;
  parameters: Record<string, ParameterType>;
  allowed_when: Condition[];
  effects: Effect[];
};

type ActionInvocation = {
  action: string;
  arguments: Record<string, Scalar>;
};
~~~

The builder authors action names, parameters, conditions, and effects. The runtime has no fixed player action names.

An invocation with a known name and correctly typed arguments is well-formed. If any allowed_when condition is false, the action is inapplicable: its effects do not run, the turn is consumed, and after-action rules still run.

Unknown names, missing or extra arguments, and incorrect argument types are unusable actor output. They do not advance state and may receive bounded formatting recovery.

## After-action rules

~~~typescript
type TriggerRule = {
  id: string;
  when: Condition[];
  effects: Effect[];
};
~~~

After-action rules run once in array order after each well-formed action attempt. Each rule observes all changes already made during that turn. The list does not restart after an effect.

## Objectives and failures

~~~typescript
type ObjectiveRule = {
  id: ObjectiveId;
  description: string;
  satisfied_when: Condition;
};

type FailureRule = {
  id: string;
  description: string;
  when: Condition;
};
~~~

Objectives are ordered. A completed objective remains complete. After each turn, failure conditions are checked first. If none is true, the runtime completes every consecutive objective whose condition is currently true. All objectives complete means success.

## Turn execution

~~~text
receive action invocation
→ validate name and arguments
→ resolve parameters
→ evaluate allowed_when
→ apply action effects if applicable
→ run after_action rules once in order
→ validate resulting state
→ check failures
→ advance ordered objectives
→ set success when all objectives complete
→ render observation and record transition
~~~

## Rendering

Rendering copies the immutable # and . terrain and overlays every entity with a non-null position using properties.symbol. A missing or non-string symbol is invalid. Non-solid entities may share cells. Two solid entities may not share a cell.

## Complete illustrative builder response

This pressure-plate program is an example of what a builder may generate from a prompt. PUSH, crate, plate, and gate are not runtime features.

~~~json
{
  "status": "generated",
  "interpretation": [
    "The player can push the crate.",
    "Putting the crate on the plate opens the gate.",
    "The player must reach the exit."
  ],
  "environment": {
    "actor": "player",
    "map": [
      "###########",
      "#@.....#..#",
      "#..B...#..#",
      "#..P...G.E#",
      "#......#..#",
      "###########"
    ],
    "legend": {
      "@": {
        "id": "player",
        "properties": {
          "symbol": "@",
          "solid": true
        }
      },
      "B": {
        "id": "crate",
        "properties": {
          "symbol": "B",
          "solid": true,
          "movable": true
        }
      },
      "P": {
        "id": "plate",
        "properties": {
          "symbol": "P",
          "solid": false
        }
      },
      "G": {
        "id": "gate",
        "properties": {
          "symbol": "G",
          "solid": true,
          "open": false
        }
      },
      "E": {
        "id": "exit",
        "properties": {
          "symbol": "E",
          "solid": false
        }
      }
    },
    "values": {},
    "actions": [
      {
        "name": "MOVE",
        "parameters": {
          "direction": "direction"
        },
        "allowed_when": [
          {
            "operation": "can_move",
            "entity": "player",
            "direction": "$direction"
          }
        ],
        "effects": [
          {
            "operation": "move",
            "entity": "player",
            "direction": "$direction"
          }
        ]
      },
      {
        "name": "PUSH",
        "parameters": {
          "target": "entity",
          "direction": "direction"
        },
        "allowed_when": [
          {
            "operation": "adjacent",
            "first": "player",
            "second": "$target",
            "direction": "$direction"
          },
          {
            "operation": "property_equals",
            "entity": "$target",
            "property": "movable",
            "value": true
          },
          {
            "operation": "can_move",
            "entity": "$target",
            "direction": "$direction"
          }
        ],
        "effects": [
          {
            "operation": "move",
            "entity": "$target",
            "direction": "$direction"
          },
          {
            "operation": "move",
            "entity": "player",
            "direction": "$direction"
          },
          {
            "operation": "emit",
            "event": "pushed",
            "target": "$target"
          }
        ]
      }
    ],
    "after_action": [
      {
        "id": "open_gate_when_crate_reaches_plate",
        "when": [
          {
            "operation": "at",
            "first": "crate",
            "second": "plate"
          },
          {
            "operation": "property_equals",
            "entity": "gate",
            "property": "open",
            "value": false
          }
        ],
        "effects": [
          {
            "operation": "set_property",
            "entity": "gate",
            "property": "open",
            "value": true
          },
          {
            "operation": "set_property",
            "entity": "gate",
            "property": "solid",
            "value": false
          },
          {
            "operation": "set_property",
            "entity": "gate",
            "property": "symbol",
            "value": "/"
          },
          {
            "operation": "emit",
            "event": "opened",
            "target": "gate"
          }
        ]
      }
    ],
    "objectives": [
      {
        "id": "place_crate",
        "description": "Push the crate onto the pressure plate.",
        "satisfied_when": {
          "operation": "at",
          "first": "crate",
          "second": "plate"
        }
      },
      {
        "id": "open_gate",
        "description": "Open the gate.",
        "satisfied_when": {
          "operation": "property_equals",
          "entity": "gate",
          "property": "open",
          "value": true
        }
      },
      {
        "id": "reach_exit",
        "description": "Reach the exit.",
        "satisfied_when": {
          "operation": "at",
          "first": "player",
          "second": "exit"
        }
      }
    ],
    "failures": []
  },
  "solution": [
    {"action": "MOVE", "arguments": {"direction": "RIGHT"}},
    {"action": "MOVE", "arguments": {"direction": "RIGHT"}},
    {"action": "PUSH", "arguments": {"target": "crate", "direction": "DOWN"}},
    {"action": "MOVE", "arguments": {"direction": "RIGHT"}},
    {"action": "MOVE", "arguments": {"direction": "DOWN"}},
    {"action": "MOVE", "arguments": {"direction": "RIGHT"}},
    {"action": "MOVE", "arguments": {"direction": "RIGHT"}},
    {"action": "MOVE", "arguments": {"direction": "RIGHT"}},
    {"action": "MOVE", "arguments": {"direction": "RIGHT"}},
    {"action": "MOVE", "arguments": {"direction": "RIGHT"}}
  ]
}
~~~

During solution replay, the third invocation moves the crate onto the plate. The after-action rule changes the generated gate properties. The first two objectives then complete from the same resulting state. The final invocation places the generated actor at the generated exit and completes the final objective.

## Validation result

~~~typescript
type ValidationResult =
  | {
      valid: true;
      environment_hash: string;
      replay: ValidationStep[];
    }
  | {
      valid: false;
      diagnostics: ValidationDiagnostic[];
    };

type ValidationDiagnostic = {
  phase: "shape" | "references" | "initial_state" | "solution_replay";
  code: string;
  path: string;
  message: string;
};
~~~

Validation proves only that the structured program is valid and its proposed solution reaches generated success without generated failure. It does not prove that the builder perfectly interpreted the source prompt.
