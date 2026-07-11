# ADR 0002: Two-Stage Strict Builder Output

Status: accepted

## Context

The environment-program contract intentionally lets the builder choose legend tokens,
entity IDs, property names, action names, and parameter names. OpenAI strict structured
outputs require every object key to be declared and `additionalProperties` to be false.
A single static strict schema therefore cannot preserve the authoritative dynamic maps.

Using a fixed property catalog would violate ADR 0001. Changing the environment program
to arrays of name/value entries would replace the documented runtime contract.

## Decision

Each logical builder attempt uses two model calls:

1. A static strict manifest response plans an interpretation and declares every
   dynamic entity token, ID, property name, action name, and parameter name/type.
2. Deterministic Python validates that manifest and constructs a strict schema with
   those exact keys. A second model call returns the complete authoritative generated
   or unsupported build response under that schema.

The complete second response, including its interpretation, remains authoritative and
independently traceable and is the only candidate
passed to the existing builder validator. Cross-references, map invariants, initial
state, interpretation freezing, solution replay, and objective truth remain
deterministic Python responsibilities.

## Consequences

- Provider-backed build responses have schema-enforced structural forms while retaining
  builder-chosen names.
- Every logical attempt costs two provider calls and the manifest schema may add latency.
- The manifest is builder-authoring context and is never shown to the acting LLM.
- A valid strict response may still fail semantic validation and enter the existing
  bounded repair loop.
- Offline fixtures remain provider fakes; a separate credentialed smoke matrix measures
  live first-attempt, repaired, unsupported, exhausted, and provider-failure outcomes.
