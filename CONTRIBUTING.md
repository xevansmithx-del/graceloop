# Contributing

Contributions are welcome when they preserve the fail-closed and claim-boundary
contracts.

1. Fork the repository and create a focused branch.
2. Do not add restricted data, credentials, local paths, raw sequences, patient
   records, or biological rows without complete rights and provenance receipts.
3. Add positive and adversarial tests for every state transition or gate.
4. Run `uv sync --frozen --extra dev`, tests under normal and optimized Python, Ruff,
   pre-commit, the privacy scanner, and the package checks.
5. Submit a pull request describing the failure mode addressed and exact acceptance
   evidence.

No contribution may invent a prior, convert `UNKNOWN` into evidence, raise empirical
`N`, select a target, or imply clinical, laboratory, material, or release authority
merely because software checks pass.
