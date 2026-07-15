# Tickets: Reviewer clarity without behavior changes

These tickets make the General Intuition submission immediately understandable while preserving the observable builder, rule-runtime, acting, evidence, and terminal behavior captured by the 101-test baseline at commit `761520c`.

Work the **frontier**: any ticket whose blockers are all done. Every refactor must keep the public behavior suite and strict type checking green.

## Give environment programs one explicit home

**What to build:** A reviewer can find the environment-program vocabulary, semantic validation, and validation replay behind clearly named modules, while the builder module reads as the bounded builder-attempt state machine.

**Blocked by:** None — can start immediately.

- [x] Define the canonical environment-program JSON vocabulary in one discoverable module without changing the provider-facing JSON contract.
- [x] Move semantic environment-program validation out of builder orchestration.
- [x] Move initial-state and proposed-solution validation behind a clearly named validation boundary.
- [x] Give builder structured-output schema construction a name that identifies its builder-schema responsibility.
- [x] Preserve every existing builder outcome, diagnostic path and code, repair request, replay transition, and accepted frozen hash.
- [x] Keep all public-interface tests and strict type checking green.

## Make one rule-runtime turn read as explicit phases

**What to build:** A reviewer can read one generated-action turn as applicability, direct effects, after-action rules, state validation, terminal evaluation, and transition construction without tracing a large data clump.

**Blocked by:** Give environment programs one explicit home.

- [x] Group the mutable state and trace information for one turn behind one clearly named execution object.
- [x] Make direct effects, after-action rules, failure evaluation, ordered objective completion, and transition construction visible as distinct phases.
- [x] Replace indirect immutable-state reconstruction with an explicit dataclass operation.
- [x] Preserve exact runtime states, effect limits, direct and automatic effect traces, observations, outcomes, and error attribution.
- [x] Keep all runtime, composition, evidence, dashboard, and acting tests green.

## Make acting retries and observer updates explicit

**What to build:** A reviewer can follow one acting step through bounded response recovery, deterministic action execution, observer notification, and terminal attribution without decoding an optional-field event bag.

**Blocked by:** None — can start immediately.

- [x] Isolate the bounded request-and-validate loop from episode progression.
- [x] Rename the acting update boundary so it reads as an observer rather than a collection.
- [x] Make update payload construction keyword-explicit or phase-specific so response, action, transition, error, and status cannot be confused.
- [x] Preserve provider-call counts, recovery observations, unchanged-state behavior, acting results, evidence, and dashboard updates.
- [x] Keep all acting, CLI, evidence, and dashboard tests green.

## Separate dashboard projection, rule formatting, and Rich rendering

**What to build:** A reviewer can recognize the dashboard as a read-only presentation adapter, inspect generic-rule formatting independently, and ignore Rich layout details when reviewing deterministic semantics.

**Blocked by:** Make acting retries and observer updates explicit.

- [x] Keep a small, obvious public dashboard facade for CLI callers.
- [x] Separate generated-rule formatting from dashboard state projection and Rich rendering.
- [x] Separate read-only projection from terminal layout without adding presentation concepts to the rule runtime.
- [x] Preserve fixed-width rendering, compact rendering, change highlighting, non-interactive summaries, and read-only observer behavior exactly.
- [x] Keep all dashboard, CLI, and acting tests green.

## Ship a trustworthy reviewer-facing repository

**What to build:** A reviewer cloning the repository can understand, run, and inspect the harness in 15–20 minutes using only tracked files and accurate commands.

**Blocked by:** Give environment programs one explicit home; Make one rule-runtime turn read as explicit phases; Separate dashboard projection, rule formatting, and Rich rendering.

- [x] Track the reviewer README, offline tests, environment-program reference, approved ticket graph, and one curated generated example while leaving internal agent and planning material private.
- [x] Provide a copy-paste quickstart whose flags and attempt limits match the implementation.
- [x] Add a concise architecture and code-reading tour using the domain distinction: Builder authors rules; Runtime executes rules; Actor chooses actions.
- [x] Explain the deterministic proof boundary and the fallible interpretation boundary without overstating generated quality.
- [x] Make one representative accepted environment and acting rollout inspectable without credentials.
- [x] Keep dated reliability measurements out of the stable getting-started path.

## Verify the submission from a clean reviewer checkout

**What to build:** The final tracked submission passes its documented checks and survives a clarity review performed from the same files a General Intuition evaluator will receive.

**Blocked by:** Ship a trustworthy reviewer-facing repository.

- [ ] Run the complete offline test suite and strict type checking from documented commands.
- [ ] Verify the CLI help and credential-free documentation path from tracked files.
- [ ] Inspect a clean Git archive to confirm all promised reviewer artifacts are included and internal-only material remains excluded.
- [ ] Compare representative runtime, evidence, and dashboard outputs with the pre-refactor behavior baseline.
- [ ] Review the complete change against repository standards and these tickets, then resolve every material clarity or behavior-preservation finding.
