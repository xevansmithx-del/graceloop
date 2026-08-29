"""Command-line interface for GraceLoop capture, compilation, replay, and simulation."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .canonical import GraceLoopError, atomic_write_canonical, read_json
from .capsule import (
    compile_capsule,
    explain_capsule,
    simulate_capsule,
    verify_capsule,
)
from .capture import (
    capture_declared_model,
    capture_gracegraph_capsule,
    capture_phytoperturb_proof,
    capture_tooluniverse,
)
from .models import COMPILER_VERSION


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="graceloop")
    parser.add_argument("--version", action="version", version=f"%(prog)s {COMPILER_VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)

    capture_tu = commands.add_parser(
        "capture-tu", help="capture a registered ToolUniverse documentary receipt"
    )
    capture_tu.add_argument("config", type=Path)
    capture_tu.add_argument("--out", type=Path, required=True)

    capture_phyto = commands.add_parser(
        "capture-phytoperturb", help="verify and capture the bounded CKX proof"
    )
    capture_phyto.add_argument("proof", type=Path)
    capture_phyto.add_argument("--verifier", type=Path)
    capture_phyto.add_argument("--receipt-id", required=True)
    capture_phyto.add_argument("--evidence-family", required=True)
    capture_phyto.add_argument("--out", type=Path, required=True)

    capture_graph = commands.add_parser(
        "capture-gracegraph", help="verify and capture a sealed GraceGraph structural base"
    )
    capture_graph.add_argument("capsule", type=Path)
    capture_graph.add_argument("--source-root", type=Path, required=True)
    capture_graph.add_argument("--project-root", type=Path)
    capture_graph.add_argument("--receipt-id", required=True)
    capture_graph.add_argument("--evidence-family", required=True)
    capture_graph.add_argument("--out", type=Path, required=True)

    capture_model = commands.add_parser(
        "capture-model", help="embed inspectable protocol locks and qualitative model matrices"
    )
    capture_model.add_argument("declaration", type=Path)
    capture_model.add_argument("--receipt-id", required=True)
    capture_model.add_argument("--evidence-family", required=True)
    capture_model.add_argument("--out", type=Path, required=True)

    compile_command = commands.add_parser(
        "compile", help="compile a deterministic counterfactual frontier capsule"
    )
    compile_command.add_argument("study", type=Path)
    compile_command.add_argument("--out", type=Path, required=True)

    verify = commands.add_parser("verify", help="replay and verify an exact capsule")
    verify.add_argument("capsule", type=Path)

    explain = commands.add_parser("explain", help="explain one experiment and its branches")
    explain.add_argument("capsule", type=Path)
    explain.add_argument("experiment_id")

    simulate = commands.add_parser(
        "simulate", help="replay one outcome as a counterfactual, never as an observation"
    )
    simulate.add_argument("capsule", type=Path)
    simulate.add_argument("experiment_id")
    simulate.add_argument("outcome_id")
    return parser


def _emit(value: object) -> None:
    print(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "capture-tu":
            receipt = capture_tooluniverse(read_json(arguments.config))
            atomic_write_canonical(arguments.out, receipt)
            result: object = receipt
        elif arguments.command == "capture-phytoperturb":
            receipt = capture_phytoperturb_proof(
                arguments.proof,
                arguments.receipt_id,
                arguments.evidence_family,
                verifier_path=arguments.verifier,
            )
            atomic_write_canonical(arguments.out, receipt)
            result = receipt
        elif arguments.command == "capture-gracegraph":
            receipt = capture_gracegraph_capsule(
                arguments.capsule,
                arguments.source_root,
                arguments.receipt_id,
                arguments.evidence_family,
                project_root=arguments.project_root,
            )
            atomic_write_canonical(arguments.out, receipt)
            result = receipt
        elif arguments.command == "capture-model":
            receipt = capture_declared_model(
                arguments.declaration,
                arguments.receipt_id,
                arguments.evidence_family,
            )
            atomic_write_canonical(arguments.out, receipt)
            result = receipt
        elif arguments.command == "compile":
            result = compile_capsule(arguments.study, arguments.out)
        elif arguments.command == "verify":
            result = verify_capsule(arguments.capsule)
        elif arguments.command == "explain":
            result = explain_capsule(arguments.capsule, arguments.experiment_id)
        else:
            result = simulate_capsule(
                arguments.capsule, arguments.experiment_id, arguments.outcome_id
            )
        _emit(result)
        return 0
    except (GraceLoopError, OSError, subprocess.SubprocessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
