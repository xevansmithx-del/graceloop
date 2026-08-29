"""Assertion-independent normal/-O parity probe for the sealed CKX capsule."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from graceloop.canonical import canonical_bytes, sha256_bytes
from graceloop.capsule import explain_capsule, simulate_capsule, verify_capsule


def main() -> int:
    project = Path(__file__).resolve(strict=True).parents[1]
    builder = project / "examples" / "ckx" / "build_public_demo.py"
    with tempfile.TemporaryDirectory(prefix="graceloop-public-probe-") as raw:
        destination = Path(raw) / "demo"
        subprocess.run(
            [sys.executable, str(builder), str(destination)],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        )
        capsule = destination / "capsule"
        verification = verify_capsule(capsule)
        explanation = explain_capsule(capsule, "E_ALL_SIX_IDENTITY_EXPRESSION")
        simulation = simulate_capsule(capsule, "E_ALL_SIX_IDENTITY_EXPRESSION", "O_POSITIVE")
        if verification["empirical_n"] != 0 or verification["experiment_authorized"] is not False:
            raise SystemExit("fixed N=0 boundary changed")
        if verification["status"] != "SELF_CONSISTENT_UNAUTHENTICATED":
            raise SystemExit("capsule verification status changed")
        if explanation["frontier_membership"] != {
            "currently_admissible": False,
            "conditional_scientific": True,
        }:
            raise SystemExit("CKX frontier membership changed")
        if simulation["status"] != "COUNTERFACTUAL_ONLY_NOT_AN_OBSERVATION":
            raise SystemExit("simulation crossed the observation boundary")
        output = {
            "run_id": verification["run_id"],
            "verify_sha256": sha256_bytes(canonical_bytes(verification)),
            "explain_sha256": sha256_bytes(canonical_bytes(explanation)),
            "simulate_sha256": sha256_bytes(canonical_bytes(simulation)),
        }
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
