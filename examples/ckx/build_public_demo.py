#!/usr/bin/env python3
"""Build the synthetic, network-free GraceLoop public demonstration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_fixture import MODEL_RECEIPT_ID, build_study, declaration

from graceloop.canonical import GraceLoopError, atomic_write_canonical
from graceloop.capsule import compile_capsule, verify_capsule
from graceloop.capture import capture_declared_model

MODEL_EVIDENCE_FAMILY = "GRACELOOP_DECLARED_CKX_MODEL_20260828"


def build(destination: Path) -> dict[str, object]:
    if destination.is_symlink():
        raise GraceLoopError("public-demo destination must not be a symlink")
    if destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            raise GraceLoopError("public-demo destination must be absent or an empty directory")
    else:
        destination.mkdir(parents=True)

    declaration_path = destination / "declared_model.json"
    receipt_path = destination / "receipts" / f"{MODEL_RECEIPT_ID}.json"
    study_path = destination / "study.json"
    capsule_path = destination / "capsule"

    atomic_write_canonical(declaration_path, declaration())
    receipt = capture_declared_model(
        declaration_path,
        MODEL_RECEIPT_ID,
        MODEL_EVIDENCE_FAMILY,
        captured_at_utc="2026-08-28T00:00:00Z",
    )
    atomic_write_canonical(receipt_path, receipt)
    study = build_study(receipt)
    study["base_capsule"] = None
    study["receipt_files"] = [f"receipts/{MODEL_RECEIPT_ID}.json"]
    study["context_receipt_ids"] = [MODEL_RECEIPT_ID]
    atomic_write_canonical(study_path, study)
    analysis = compile_capsule(study_path, capsule_path)
    verification = verify_capsule(capsule_path)
    return {
        "analysis_run_id": analysis["run_id"],
        "capsule": "capsule",
        "verification": verification,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    try:
        result = build(arguments.destination)
    except (GraceLoopError, OSError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
