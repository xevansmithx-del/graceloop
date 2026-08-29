# GraceLoop

GraceLoop is a prior-free compiler for one narrow but consequential question:
**given an explicitly declared biological decision and a set of mutually exclusive
counterfactual worlds, which registered experiment designs could distinguish the
remaining decision options?**

It turns typed scientific receipts, content-addressed reference-frame declarations,
open gates, total qualitative outcome matrices, and declared resource vectors into
two Pareto/minimax experiment frontiers:

- `currently_admissible`: decision-separating work with no current blocker. In the
  alpha boundary this can only be read-only planning work; it is not execution
  authority.
- `conditional_scientific`: what would be discriminating if its listed gates,
  reference bindings, and authority requirements were later satisfied. Membership is
  a counterfactual property of the declared model, not a recommendation to execute.

GraceLoop 0.1.0a1 is deliberately locked at empirical `N=0`. It does not select a
target, close a biological gate, authorize an experiment, start material work, or
claim that a declared prediction is true.

## Why it exists

The surrounding tools can retrieve source metadata, preserve structural plans, and
compile gated biological hypotheses. The remaining failure mode is downstream:
choosing the next information-generating action can silently mix incompatible
reference frames, treat database projections as biological facts, invent confidence
weights, or bury failure outcomes.

GraceLoop makes those assumptions inspectable. It requires every declared world,
every outcome branch, every qualitative `PERMITS`/`EXCLUDES`/`UNKNOWN` relation, and
every protocol/resource lock to be explicit and digest-bound. It then performs only
set operations and qualitative Pareto/minimax analysis.

```text
registered captures + local proof receipts + declared model receipt
                              |
                              v
       exact N=0 study, frames, gates, worlds, outcome matrices
                              |
                              v
         fail-closed branch replay and decision-pair separation
                              |
                              v
    current frontier + conditional frontier + tamper-evident capsule
```

The architectural decision and its alternatives are recorded in
[`docs/ADR-0001-graceloop.md`](docs/ADR-0001-graceloop.md). The validation contract is
in [`docs/VALIDATION.md`](docs/VALIDATION.md).

## Scientific boundary

Every accepted v1 study must reproduce this exact boundary, including JSON types:

```json
{
  "biological_gates_closed": 0,
  "empirical_n": 0,
  "experiment_authorized": false,
  "experiments_performed": 0,
  "material_work_started": false,
  "release_authorized": false,
  "results_present": false,
  "target_selected": false
}
```

At that boundary GraceLoop rejects observed-outcome receipts and recursively rejects
model fields such as priors, probabilities, likelihoods, posteriors, utilities,
weights, expected values, value-of-information fields, and scalar scores. Floats are
also rejected; resource dimensions are nonnegative integers or the literal
`"UNKNOWN"`.

The compiler therefore does not estimate uncertainty. `UNKNOWN` is a qualitative
relation that preserves a world, and unknown resources are incomparable rather than
being treated as zero or an arbitrary large number.

## What is bound—and what is not

### Scientific receipts

Receipts use `graceloop.scientific-receipt.v1`. They bind producer and adapter
digests, parameter locks, input/output descriptors, balanced coverage, subject alias,
reference-frame ID, correlation-lineage fields, calibration state, capabilities,
prohibitions, and a payload. Receipt kinds are:

- `SOURCE_SNAPSHOT`
- `MODEL_PREDICTION`
- `FRAME_TRANSFORM`
- `CALIBRATION`
- `ALIAS_EQUIVALENCE`
- `OBSERVATION` (defined by the schema but rejected by an N=0 study)

Capabilities are ceilings, not endorsements. A failed capture retains query-execution
metadata only. A no-result response is not an absence claim. Evidence-family labels
do not establish independence, and v1 accepts no attestations; receipt verification is
therefore `SELF_CONSISTENT_UNAUTHENTICATED`.

The ToolUniverse adapter currently registers bounded, sequence-free projections for
NCBI Datasets/Gene/Protein, PubMed, Europe PMC, Plant Reactome, OMA, and InterPro.
It hashes the raw response but stores only a safe projection in the public receipt;
`raw_response_retained` is `false`. Schema omissions, unknown totals, or incomplete
coverage force `PARTIAL`. Network snapshots are not claimed to be reproducible.

Local adapters also bind:

- the sealed GraceGraph structural capsule and its pinned source manifest; static
  replay establishes self-consistency only, while live-project replay is diagnostic
  and cannot upgrade provenance;
- the pinned PhytoPerturb CKX proof, verifier, and memory head; and
- a canonical declared-model artifact containing inspectable protocol locks and total
  qualitative matrices. That receipt remains synthetic, uncalibrated, and
  unauthenticated.

### Reference frames

A frame ID is the SHA-256 address of its complete declaration: kind, content-binding
mode, coordinate convention, feature/comparator/assayed-space digests, and optional
transform receipt. Supported content-binding modes are `FULL_CONTENT_SHA256`,
`ASSEMBLY_MANIFEST_SHA256`, and `UNAVAILABLE`.

An accession label is not a byte-level content binding. A frame declared
`UNAVAILABLE` is reported as `UNBOUND_METADATA_LABEL_ONLY`, and an experiment using
it receives a blocker. GraceLoop never infers coordinate equivalence between frames;
an explicit, output-bound transform receipt is required.

### Outcome models

A study declares 2–32 mutually exclusive worlds and exactly one open-world residual.
Each world maps to one substantive decision option plus the defer option. Every
experiment must contain a total world-by-outcome matrix and exactly one branch for
each of:

- informative positive;
- informative negative;
- `OTHER`;
- no call;
- QC failure;
- contradictory result; and
- unexpected result.

One informative-alternative branch is optional. Fail-closed branches must use
`UNKNOWN`, cite no affirmative evidence, and preserve every active world. If a
scientific branch excludes every declared world, GraceLoop labels model
misspecification and performs no update. The open residual must be permitted by the
`OTHER` branch.

For a decisive cell, the cited declared-model receipt must be complete and must bind
the exact protocol digest, reference-frame set, resource basis, decision/world/gate
context, and compiled matrix. Those locks detect drift; they do not validate the
biology that produced the declaration.

## Frontier semantics

GraceLoop considers only world pairs that imply different substantive decision
options. An outcome separates a pair only when one world is `PERMITS` and the other is
`EXCLUDES`; `UNKNOWN` never separates a pair.

The qualitative Pareto frontier maximizes:

- worst-case reduction in remaining substantive options;
- whether every declared informative branch conditionally resolves the decision;
- decision pairs separated on every scientific branch; and
- decision pairs separated on at least one scientific branch.

It minimizes worst-case remaining options and the declared duration, sample, cost,
material-risk, and irreversibility dimensions. Minimax selection occurs inside the
Pareto set. Tied epistemic candidates are all reported; lexicographic experiment ID is
only a display tie-breaker, never a scientific preference.

## CKX acceptance fixture

`examples/ckx` encodes the Cannabis CKX Stage-1 problem without choosing a target. Its
four substantive dispositions are:

- retain CKX2-only for later review;
- retain CKX3-only for later review;
- retain a combined/redundant model; or
- retain neither/other and redesign.

Every disposition also retains defer, and the neither/other world is the open
residual. The fixture registers six candidate experiments and 17 expected receipts
(14 ToolUniverse captures, GraceGraph, PhytoPerturb, and the declared model). Its
acceptance result is:

| Property | Expected value |
|---|---|
| Decision-relevant world pairs | `6` |
| Currently admissible frontier | `[]` |
| Currently admissible minimax | `null` |
| Conditional frontier | `["E_ALL_SIX_IDENTITY_EXPRESSION"]` |
| Conditional minimax | `E_ALL_SIX_IDENTITY_EXPRESSION` |
| Conditional worst remaining substantive options | `1` |
| Conditional minimax option gain | `3` |
| Pairs separated on at least one scientific branch | `6` |
| Pairs separated on every scientific branch | `0` |
| Every declared informative classification branch conditionally resolves | `true` |
| Failure branches preserve all active worlds | `true` |

This result means only that the declared all-six actual-stock identity plus
tissue/stage expression qualification is conditionally discriminating across the
four declared models. It remains blocked by open gates, unbound frame content, and
the alpha authorization boundary. It is not an instruction to collect samples.

## Quick start

GraceLoop requires Python 3.11 or later. Core compilation and replay have no runtime
dependencies; live ToolUniverse capture requires a separately installed `tu` CLI,
and pinned local adapters require their exact registered companion artifacts. The
no-clobber capsule publisher is tested on Linux and macOS.

```bash
git clone https://github.com/xevansmithx-del/graceloop.git
cd graceloop
python3.11 -m pip install -e .
graceloop --help
```

Once a study and its receipt files have been assembled, compile and replay a
tamper-evident, no-clobber capsule:

```bash
GL_DEMO="$(mktemp -d)"
python3.11 examples/ckx/build_public_demo.py "$GL_DEMO"
graceloop verify "$GL_DEMO/capsule"
graceloop explain "$GL_DEMO/capsule" \
  E_ALL_SIX_IDENTITY_EXPRESSION
graceloop simulate "$GL_DEMO/capsule" \
  E_ALL_SIX_IDENTITY_EXPRESSION O_POSITIVE
```

`simulate` always emits `COUNTERFACTUAL_ONLY_NOT_AN_OBSERVATION`. Compilation and
capture commands refuse to overwrite existing destinations; use a fresh output path
for every run.

### Build the public CKX demonstration

The public demonstration is generated from one synthetic, unauthenticated
declared-model receipt. It contains no network response projections and does not
claim that the qualitative model is biologically correct. Build into a fresh path so
the no-clobber controls remain meaningful:

```bash
GL_REBUILD="$(mktemp -d)"
python3.11 examples/ckx/build_public_demo.py "$GL_REBUILD"
graceloop verify "$GL_REBUILD/capsule"
```

The ToolUniverse, GraceGraph, and PhytoPerturb adapters remain available, but their
receipts must be acquired separately under the source providers' terms. Pinned local
adapter tests run only when the exact registered assets are present; otherwise they
are reported as optional skips. A live capture may legitimately yield `PARTIAL` or
`FAILED`, and GraceLoop preserves that state rather than converting it into a
positive or negative biological finding.

## Capsule contents and replay

Compilation stages, verifies, fsyncs, and publishes a no-clobber directory containing
canonical `study.json`, `analysis.json`, `frontier.json`, `report.md`, a flat receipt
inventory, and an exact recursive `manifest.json`. Verification rejects checksum,
byte-count, inventory, canonical-JSON, symlink, hardlink, receipt-ID, analysis, frontier,
or report drift and replays the analysis from the locked study and receipts.

Successful verification establishes internal reproducibility and reports
`SELF_CONSISTENT_UNAUTHENTICATED`. It does not authenticate source claims or establish
empirical validity.

## Development

```bash
python3.11 -m pip install -e '.[dev]'
python3.11 -m compileall -q src examples tests
ruff check src tests examples
python3.11 -m pytest
```

See [`docs/VALIDATION.md`](docs/VALIDATION.md) for the full adversarial matrix and the
final recorded results.

## Nonclaims

- No CKX target is selected.
- No experiment, material work, or release is authorized.
- Database records and projections do not establish Cannabis function or causality.
- Stable accessions do not establish coordinate equivalence across Pink Pepper,
  suppressed cs10, and the actual experimental stock.
- The missing CKX4 label is not evidence of biological absence.
- A Pareto or minimax position is conditional analysis of declared inputs, not proof,
  advice, or permission.
- GraceLoop does not infer causality, search beyond the declared candidate set, or
  prove a globally optimal experiment.
- GraceLoop is not a medical device and provides no patient-specific diagnosis,
  treatment, dose, clinical advice, or laboratory execution authority.
