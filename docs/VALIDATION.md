# GraceLoop 0.1.0a1 validation

Status: **research alpha; software validation only**

The public release gate runs the complete standalone unit and hostile suite under
normal Python and repeats an assertion-independent public-demo probe under
`python -O`. CI also checks Ruff, formatting, pre-commit, public-tree privacy,
source/test bytecode, a clean wheel and sdist, installed-wheel execution, and the
exact source freeze.

Pinned companion-adapter tests are integration tests. GraceGraph integration runs in
CI against the exact public `v0.1.0a1` tag, its source manifest, and a freshly compiled
synthetic capsule. PhytoPerturb proof integration runs only when the exact registered
proof and verifier are supplied through `GRACELOOP_PHYTOPERTURB_ROOT`; those artifacts
are deliberately not bundled or silently relicensed.

## Public demonstration contract

`examples/ckx/build_public_demo.py` creates a network-free capsule from one synthetic,
unauthenticated declared-model receipt. The expected result is:

- empirical `N=0`, zero performed experiments, zero biological gates closed;
- no target, result, experiment, material work, or release authorization;
- four declared worlds including one open residual;
- six decision-relevant world pairs;
- no currently admissible experiment;
- one conditional frontier member, `E_ALL_SIX_IDENTITY_EXPRESSION`;
- all failure, no-call, contradictory, and unexpected branches preserve every world;
- every simulation is labeled `COUNTERFACTUAL_ONLY_NOT_AN_OBSERVATION`.

The frontier means only that the synthetic, outcome-complete matrix is
decision-separating if its listed gates and frame bindings were later satisfied. It
does not validate the matrix's biology or authorize sample collection.

## Hostile behaviors covered

The suite rejects or bounds duplicate and malformed JSON, non-finite values, floats,
credential/path material, raw sequence-like payloads, schema drift, missing capability
ceilings, failed/no-result capture promotion, reference-frame substitution,
uncalibrated decisive cells, incomplete world/outcome matrices, missing open
residuals, hidden priors or scalar utilities, false pair separation through
`UNKNOWN`, failure-branch narrowing, source/capsule inventory drift, symlinks,
hardlinks, overwrite races, manifest/checksum drift, optimized-runtime changes, and
attempts to raise the fixed alpha boundary.

ToolUniverse capture is live and can legitimately return `PARTIAL` or `FAILED`.
Coverage and projection omissions remain explicit; a no-result response is not a
biological absence claim.

## Required release commands

```bash
uv sync --frozen --extra dev
uv run pytest
normal=$(uv run python tests/optimized_probe.py)
optimized=$(uv run python -O tests/optimized_probe.py)
test "$normal" = "$optimized"
uv run ruff check .
uv run ruff format --check .
uv run pre-commit run --all-files
uv run python scripts/privacy_scan.py .
uv run python -m compileall -q src tests examples
uv run python -m build
uv run python -m twine check dist/*
```

The wheel and sdist must then be extracted and privacy-scanned, the sdist suite must
pass, and an isolated wheel environment must build, verify, explain, and simulate a
fresh synthetic capsule with outputs matching the source execution.

Exact test counts, package digests, source-manifest digest, capsule run ID, and CI run
are recorded in the GitHub prerelease notes after a clean public checkout reproduces
the gate.

No software validation establishes biological truth, causal effect, empirical
performance, globally optimal experiment choice, clinical utility, target selection,
or authority to perform laboratory or clinical work.
