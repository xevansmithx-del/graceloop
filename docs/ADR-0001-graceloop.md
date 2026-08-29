# ADR-0001: Prior-free counterfactual experiment-frontier compiler

- Status: Accepted for `0.1.0a1`
- Date: 2026-08-28
- Decision owners: Machines of Loving Grace

## Context

The program already has tools that retrieve biomedical metadata, preserve scientific
artifacts, enumerate hypotheses, and enforce static biological gates. Those tools do
not fully solve the next-action problem: after contradictory or incomplete evidence,
which additional measurement could actually distinguish the remaining decision
options?

A conventional ranking layer would attach probabilities, evidence weights, or scalar
value-of-information scores. At empirical `N=0`, those quantities would be invented
unless a separately calibrated model supplied them. The source portfolio also has
known hazards that a ranker could obscure:

- assembly labels, coordinate frames, and actual-stock material can be conflated;
- database metadata and electronic projections can be upgraded into causal claims;
- repeated records can be counted as independent evidence;
- no-result responses can become absence claims;
- success-only outcome models can hide QC, contradiction, and model-misspecification
  branches; and
- a planning result can be mistaken for experiment or target authority.

The new component must improve action discrimination without crossing any of those
boundaries or modifying sealed predecessor tools.

## Decision

Build GraceLoop as a small, dependency-free sidecar compiler with a fixed empirical
`N=0` boundary.

### 1. Compile explicit decisions and worlds

Every study declares one decision, at least two substantive options plus defer, 2–32
mutually exclusive worlds, and exactly one open-world residual. Each world maps to
exactly one substantive option plus defer. The residual maps to its own substantive
`OTHER`/redesign option so the declared model never claims exhaustiveness.

GraceLoop analyzes only world pairs that imply different substantive options.

### 2. Use total qualitative outcome matrices

Every experiment declares a total world-by-outcome matrix using only `PERMITS`,
`EXCLUDES`, and `UNKNOWN`. Positive, negative, `OTHER`, no-call, QC-failed,
contradictory, and unexpected branches are mandatory; at most one informative
alternative is allowed.

`UNKNOWN` never separates a world pair. Failure branches carry no affirmative source,
preserve all active worlds, and cause no update. A scientific outcome that excludes
all worlds is model misspecification and also causes no update. The residual world
must be permitted by `OTHER`.

### 3. Require typed, capability-limited receipts

Inputs are exact-schema, digest-bound scientific receipts. Receipt kind constrains
capabilities. Producer, adapter, parameter, input/output, coverage, reference-frame,
lineage, calibration, prohibition, and payload fields are explicit. Failed and
no-result captures lose result capabilities rather than manufacturing negative
evidence. Evidence families do not imply independence.

V1 attestations are empty, so every receipt remains unauthenticated. Observations are
not accepted into an N=0 study.

The ToolUniverse integration uses registered, bounded, sequence-free projections. It
hashes but does not retain raw responses in the public receipt. Local adapters pin and
replay the GraceGraph structural capsule, the PhytoPerturb CKX proof, and the
GraceLoop declared-model artifact.

### 4. Make reference frames content-addressed

A reference-frame ID hashes the full frame declaration. Content may be bound by a
full-content digest, an assembly-manifest digest, or explicitly `UNAVAILABLE`.
Metadata-only frames block current readiness. Accessions do not imply coordinate
equivalence; an explicit typed transform receipt is required.

### 5. Bind protocol and model semantics

Each declared experiment includes a complete protocol lock: operation, execution
class, purpose, denominator, comparator, outcome classifier, QC rules, reference
frames, gates, and resource basis. The model digest binds the decision, worlds,
gates, outcomes, matrix, resources, and protocol digest. Every decisive matrix cell
must cite the same complete declared-model receipt that embeds the exact compiled
experiment and bindings.

This makes mutation detectable. It does not certify that the qualitative relations or
resource estimates are scientifically correct.

### 6. Produce two qualitative frontiers

The compiler emits:

- a currently admissible frontier, restricted to decision-separating experiments with
  no blockers; and
- a conditional scientific frontier, which exposes the discriminatory value of
  blocked designs without treating that value as execution authority.

Pareto analysis maximizes option reduction, conditional resolution across all declared
informative classification branches, guaranteed pair separation, and possible pair
separation while minimizing worst-case remaining options and declared resources.
Failure, no-call, contradictory, and unexpected branches are not informative; they
preserve every active world. `UNKNOWN` resource values are incomparable.
Minimax is applied only inside the Pareto set, reports all epistemic ties, and uses an
experiment ID only for deterministic display.

Every non-read-only design receives the fixed blocker
`ALPHA_EXPERIMENT_AUTHORIZATION_FALSE`. Open gates, unbound frames, incompatible or
partial model receipts, and other schema failures remain explicit blockers.

### 7. Publish replayable, no-clobber capsules

Compilation writes canonical JSON, a deterministic Markdown report, a flat receipt
inventory, and an exact manifest into a staged directory. It verifies and fsyncs the
stage before an atomic no-replace publication. Replay recomputes the analysis,
frontier, report, receipt identities, hashes, byte counts, and inventory.

Successful replay means `SELF_CONSISTENT_UNAUTHENTICATED`, not empirically validated.

## Alternatives considered

### Bayesian or weighted evidence ranking

Rejected for v1. No calibrated prior, likelihood, independence model, or utility
function exists at the locked boundary. Adding plausible-looking numbers would hide
rather than reduce epistemic uncertainty.

### Generic hypothesis or gate compiler

Rejected as the core contribution. Existing Plant Evidence Compiler, PhytoResolve,
and PhytoPerturb components already cover static evidence/gate compilation. GraceLoop
instead focuses on counterfactual outcome separation and the experiment frontier.

### Autonomous experiment orchestrator

Rejected. Planning and authority are different control planes. GraceLoop must not
close biological, owner, legal, or human gates, collect material, select a target, or
launch an experiment.

### Direct synthesis of database outputs

Rejected. Merging records into one narrative would erase capability ceilings,
coverage limitations, frame mismatches, correlation lineage, and no-result semantics.
Typed receipts preserve those distinctions.

### One scalar “best experiment” score

Rejected. A scalar collapses resource and epistemic trade-offs and requires hidden
weights. GraceLoop exposes the Pareto set, then applies an epistemic minimax rule while
leaving resources Pareto.

## Consequences

### Benefits

- Hidden outcome and frame assumptions become machine-checkable.
- A blocked but genuinely discriminating design can be distinguished from a cheap
  action that cannot change the decision.
- Failure, contradiction, residual-world, and model-misspecification branches fail
  closed.
- Output is deterministic under order changes and optimized Python execution.
- Sealed predecessor packages remain unchanged.

### Costs and limitations

- Results are only as useful as the declared qualitative model. GraceLoop verifies
  bindings and logic, not biological truth.
- Strict schemas require more up-front modeling work.
- Qualitative minimax cannot express calibrated expected value at N=0.
- Unknown resources remain incomparable, which can intentionally enlarge a frontier.
- ToolUniverse raw responses are not retained by the public receipt, so the receipt
  cannot independently reconstruct a transient network response from its digest.
- V1 has no signed attestations and makes no independence claim.
- Content-unbound frames and open gates can leave the current frontier empty.

## CKX acceptance decision

For the four CKX Stage-1 dispositions—CKX2-only, CKX3-only, combined/redundant, and
neither/other—the fixture must report six decision-relevant world pairs, no current
frontier, and one conditional frontier member:
`E_ALL_SIX_IDENTITY_EXPRESSION`.

All four scientific classification branches of that declared design must leave one
substantive option, collectively separate all six pairs, and have no pair separated on
every branch. Every failure branch must retain all four active worlds. This is a
model-level acceptance property, not authorization for the measurement.

## Future decisions

The following require separate ADRs and evidence boundaries:

- authenticated receipt attestations and trust roots;
- a private raw-response companion store with explicit access controls;
- calibrated prediction and resource models;
- empirical `N>0` observations and update semantics;
- execution-system integration or named authority handoff; and
- additional biological domains and declared-model adapters.
