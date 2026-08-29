"""Atomic, exact-member GraceLoop capsule compilation and replay verification."""

from __future__ import annotations

import ctypes
import errno
import os
import shutil
import stat
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from .canonical import (
    MAX_JSON_BYTES,
    GraceLoopError,
    canonical_bytes,
    read_json_bytes,
    require_relative,
    require_sha256,
    sha256_bytes,
    sha256_file,
    write_canonical,
)
from .frontier import analyze_study, explain_experiment, simulate_outcome
from .models import load_study, validate_study
from .receipt import validate_receipt

ROOT_PAYLOAD_FILES = {"study.json", "analysis.json", "frontier.json", "report.md"}
ROOT_FILES = ROOT_PAYLOAD_FILES | {"manifest.json"}
MAX_CAPSULE_MEMBERS = 512
MAX_CAPSULE_BYTES = 64 * 1024 * 1024
MAX_REPORT_BYTES = 1024 * 1024


def _receipt_locator(receipt_id: str) -> str:
    return f"receipts/{sha256_bytes(receipt_id.encode('utf-8'))[:24]}.json"


def frontier_document(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "graceloop.frontier.v1",
        "run_id": analysis["run_id"],
        "boundary": analysis["boundary"],
        "frontiers": analysis["frontiers"],
        "minimax": analysis["minimax"],
        "selection_policy": analysis["selection_policy"],
        "experiments": [
            {
                "id": item["id"],
                "current_status": item["current_status"],
                "blocked_reasons": item["blocked_reasons"],
                "decision_separating": item["decision_separating"],
                "conditional_worst_remaining_option_count": item[
                    "conditional_worst_remaining_option_count"
                ],
                "conditional_minimax_option_gain": item["conditional_minimax_option_gain"],
                "conditional_guaranteed_pair_count": item["conditional_guaranteed_pair_count"],
                "conditional_possible_pair_count": item["conditional_possible_pair_count"],
                "all_declared_informative_outcomes_resolve": item[
                    "all_declared_informative_outcomes_resolve"
                ],
                "resources": item["resources"],
            }
            for item in analysis["experiments"]
        ],
    }


def report_text(analysis: dict[str, Any]) -> str:
    current = analysis["minimax"]["currently_admissible"]
    conditional = analysis["minimax"]["conditional_scientific"]
    lines = [
        "# GraceLoop counterfactual experiment frontier",
        "",
        f"- Study: `{analysis['study_id']}`",
        f"- Run: `{analysis['run_id']}`",
        f"- Status: `{analysis['scientific_status']}`",
        f"- Empirical N: `{analysis['boundary']['empirical_n']}`",
        f"- Experiments performed: `{analysis['boundary']['experiments_performed']}`",
        f"- Target selected: `{str(analysis['boundary']['target_selected']).lower()}`",
        f"- Experiment authorized: `{str(analysis['boundary']['experiment_authorized']).lower()}`",
        "",
        "## Outcome",
        "",
    ]
    if current is None:
        lines.append("No currently admissible decision-separating experiment is registered.")
    else:
        lines.append(
            "Currently admissible minimax candidate: "
            f"`{current['experiment_id']}` (read-only planning status only)."
        )
    if conditional is None:
        lines.append("No conditional scientific decision-separating experiment is registered.")
    else:
        lines.append(
            "Conditional scientific minimax candidate: "
            f"`{conditional['experiment_id']}`. This is not execution authority."
        )
    lines.extend(
        [
            "",
            (
                "GraceLoop's frontier computation consumes no numeric priors, likelihoods, "
                "probabilities, expected values, evidence votes, or scalar authority scores. "
                "The derivation of upstream declared models is not authenticated."
            ),
            (
                "Every qualitative prediction and resource value is declared, uncalibrated, and "
                "unauthenticated. Frontier position is model analysis, not proof that the model is "
                "true."
            ),
            "",
            "## Experiments",
            "",
            "| Experiment | Status | Separates decision? | Worst options | All declared informative classification branches resolve? |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for item in analysis["experiments"]:
        lines.append(
            f"| `{item['id']}` | `{item['current_status']}` | "
            f"`{str(item['decision_separating']).lower()}` | "
            f"{item['conditional_worst_remaining_option_count']} | "
            f"`{str(item['all_declared_informative_outcomes_resolve']).lower()}` |"
        )
    lines.extend(
        [
            "",
            (
                "The resolution column covers only the declared informative classification matrix. "
                "No-call, QC-failed, contradictory, unexpected, and model-misspecification "
                "branches preserve the active worlds and make no update."
            ),
        ]
    )
    lines.extend(["", "## Receipt and frame boundary", ""])
    lines.append(
        f"- Receipts: `{analysis['receipt_summary']['total']}`; authenticated: `0`; "
        "empirical-N contribution: `0`."
    )
    state_counts = analysis["receipt_summary"]["execution_states"]
    lines.append(
        "- Receipt execution states: "
        + "; ".join(
            f"`{state}`: `{state_counts.get(state, 0)}`"
            for state in ("COMPLETE", "PARTIAL", "FAILED", "NOT_RUN")
        )
        + "."
    )
    base_diagnostic = analysis["base_capsule_diagnostic"]
    if base_diagnostic is not None:
        lines.append(
            f"- Structural base `{base_diagnostic['receipt_id']}`: static "
            f"`{base_diagnostic['static_verification_status']}`; live replay diagnostic "
            f"`{base_diagnostic['live_replay_status']}`; source capsule embedded: "
            f"`{str(base_diagnostic['source_capsule_embedded']).lower()}`."
        )
    for frame in analysis["reference_frame_audit"]:
        lines.append(
            f"- `{frame['id']}`: `{frame['comparison_status']}` "
            f"(`{frame['accession_version'] or 'NO_ACCESSION'}`)."
        )
    lines.extend(["", "## Nonclaims", ""])
    lines.extend(f"- {item}" for item in analysis["nonclaims"])
    lines.append("")
    return "\n".join(lines)


def _regular_members(root: Path) -> set[str]:
    members: set[str] = set()
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        relative_directory = directory_path.relative_to(root).as_posix()
        if relative_directory not in {".", "receipts"}:
            raise GraceLoopError(f"capsule contains an unexpected directory: {relative_directory}")
        for dirname in list(dirnames):
            candidate = directory_path / dirname
            if candidate.is_symlink():
                raise GraceLoopError("capsule directories must not be symlinks")
            child = candidate.relative_to(root).as_posix()
            if child != "receipts":
                raise GraceLoopError(f"capsule contains an unexpected directory: {child}")
        for filename in filenames:
            candidate = directory_path / filename
            if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_nlink != 1:
                raise GraceLoopError("capsule members must be single-link regular files")
            members.add(candidate.relative_to(root).as_posix())
    return members


def _snapshot_regular_file(path: Path, limit: int) -> bytes:
    """Read one bounded, single-link file once and bind the snapshot to its path."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise GraceLoopError(f"cannot open capsule member {path.name}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise GraceLoopError("capsule members must be single-link regular files")
        if before.st_size > limit:
            raise GraceLoopError(f"capsule member exceeds its byte limit: {path.name}")
        chunks = bytearray()
        while len(chunks) <= limit:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
        after = os.fstat(descriptor)
        if len(chunks) > limit:
            raise GraceLoopError(f"capsule member exceeds its byte limit: {path.name}")
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_nlink,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_nlink,
        ) or len(chunks) != after.st_size:
            raise GraceLoopError(f"capsule member changed during snapshot: {path.name}")
        current = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or (current.st_dev, current.st_ino, current.st_size)
            != (after.st_dev, after.st_ino, after.st_size)
        ):
            raise GraceLoopError(f"capsule member path changed during snapshot: {path.name}")
        return bytes(chunks)
    except OSError as exc:
        raise GraceLoopError(f"cannot snapshot capsule member {path.name}: {exc}") from exc
    finally:
        os.close(descriptor)


def _fsync_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file():
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
        elif path.is_dir():
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    descriptor = os.open(root, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_directory_noreplace(stage: Path, output: Path) -> None:
    """Atomically publish a directory while refusing every pre-existing target."""

    library = ctypes.CDLL(None, use_errno=True)
    old = os.fsencode(stage)
    new = os.fsencode(output)
    result: int | None = None
    if sys.platform == "darwin" and hasattr(library, "renamex_np"):
        renamex = library.renamex_np
        renamex.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex.restype = ctypes.c_int
        result = renamex(old, new, 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        renameat2 = library.renameat2
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(-100, old, -100, new, 1)  # AT_FDCWD, RENAME_NOREPLACE
    if result is None:
        # Unsupported platforms get a cooperative lock plus a second exact check.
        import fcntl

        lock_path = output.parent / f".{output.name}.graceloop.lock"
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            if output.exists() or output.is_symlink():
                raise GraceLoopError(f"refusing to overwrite capsule destination: {output.name}")
            os.rename(stage, output)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        return
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise GraceLoopError(f"refusing to overwrite capsule destination: {output.name}")
        raise OSError(error_number, os.strerror(error_number), str(output))


def _write_capsule(
    stage: Path,
    study: dict[str, Any],
    receipts: dict[str, dict[str, Any]],
    analysis: dict[str, Any],
) -> None:
    (stage / "receipts").mkdir()
    write_canonical(stage / "study.json", study)
    write_canonical(stage / "analysis.json", analysis)
    write_canonical(stage / "frontier.json", frontier_document(analysis))
    (stage / "report.md").write_text(report_text(analysis), encoding="utf-8")
    for receipt_id, receipt in sorted(receipts.items()):
        write_canonical(stage / _receipt_locator(receipt_id), receipt)
    payload_members = _regular_members(stage)
    manifest = {
        "schema_version": "graceloop.manifest.v1",
        "run_id": analysis["run_id"],
        "members": {
            name: {
                "sha256": sha256_file(stage / name),
                "bytes": (stage / name).stat().st_size,
            }
            for name in sorted(payload_members)
        },
    }
    write_canonical(stage / "manifest.json", manifest)


def compile_capsule(study_path: Path, output: Path) -> dict[str, Any]:
    source_study, receipts = load_study(study_path)
    locked = deepcopy(source_study)
    locked["receipt_files"] = [_receipt_locator(identity) for identity in sorted(receipts)]
    locked = validate_study(locked, receipts)
    analysis = analyze_study(locked, receipts)
    if output.exists() or output.is_symlink():
        raise GraceLoopError(f"refusing to overwrite capsule destination: {output.name}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output = output.parent.resolve(strict=True) / output.name
    if output.exists() or output.is_symlink():
        raise GraceLoopError(f"refusing to overwrite capsule destination: {output.name}")
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        _write_capsule(stage, locked, receipts, analysis)
        verify_capsule(stage)
        _fsync_tree(stage)
        _publish_directory_noreplace(stage, output)
        parent_descriptor = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except BaseException:
        if (
            stage.exists()
            and stage.parent == output.parent
            and stage.name.startswith(f".{output.name}.stage-")
        ):
            shutil.rmtree(stage)
        raise
    return analysis


def _verify_capsule_snapshots(
    capsule: Path,
) -> tuple[
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, Any],
    set[str],
]:
    if capsule.is_symlink():
        raise GraceLoopError("capsule root must not be a symlink")
    capsule = capsule.resolve(strict=True)
    if not capsule.is_dir():
        raise GraceLoopError("capsule must be a regular directory")
    top_names = {path.name for path in capsule.iterdir()}
    if top_names != ROOT_FILES | {"receipts"}:
        raise GraceLoopError(f"capsule top-level inventory mismatch: {sorted(top_names)}")
    if not (capsule / "receipts").is_dir() or (capsule / "receipts").is_symlink():
        raise GraceLoopError("capsule receipts must be a regular directory")
    actual = _regular_members(capsule)
    if len(actual) > MAX_CAPSULE_MEMBERS:
        raise GraceLoopError("capsule contains too many members")
    manifest_raw = _snapshot_regular_file(capsule / "manifest.json", MAX_JSON_BYTES)
    manifest = read_json_bytes(manifest_raw, "manifest.json")
    if canonical_bytes(manifest) + b"\n" != manifest_raw:
        raise GraceLoopError("manifest is not canonical JSON")
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "run_id", "members"}:
        raise GraceLoopError("manifest schema is not exact")
    if manifest.get("schema_version") != "graceloop.manifest.v1":
        raise GraceLoopError("unknown manifest schema")
    require_sha256(manifest.get("run_id"), "manifest.run_id")
    payload_actual = actual - {"manifest.json"}
    members = manifest.get("members")
    if not isinstance(members, dict) or set(members) != payload_actual:
        raise GraceLoopError("manifest inventory is not exact")
    if not payload_actual >= ROOT_PAYLOAD_FILES:
        raise GraceLoopError("capsule is missing a required payload")
    receipt_members = sorted(name for name in payload_actual if name.startswith("receipts/"))
    if not receipt_members or any(
        Path(name).parent.as_posix() != "receipts" for name in receipt_members
    ):
        raise GraceLoopError("receipt inventory must be nonempty and flat")
    if payload_actual != ROOT_PAYLOAD_FILES | set(receipt_members):
        raise GraceLoopError("capsule contains an unregistered payload member")
    total_bytes = 0
    snapshots: dict[str, bytes] = {}
    for name, descriptor in members.items():
        require_relative(name, "manifest member")
        if not isinstance(descriptor, dict) or set(descriptor) != {"sha256", "bytes"}:
            raise GraceLoopError(f"manifest descriptor is malformed: {name}")
        require_sha256(descriptor.get("sha256"), f"manifest descriptor {name}.sha256")
        if type(descriptor.get("bytes")) is not int or descriptor["bytes"] < 0:
            raise GraceLoopError(f"manifest descriptor {name}.bytes must be a nonnegative integer")
        if name == "report.md" and descriptor["bytes"] > MAX_REPORT_BYTES:
            raise GraceLoopError("capsule report exceeds the bounded report size")
        if name != "report.md" and descriptor["bytes"] > MAX_JSON_BYTES:
            raise GraceLoopError(f"capsule member exceeds the bounded JSON size: {name}")
        byte_limit = MAX_REPORT_BYTES if name == "report.md" else MAX_JSON_BYTES
        raw = _snapshot_regular_file(capsule / name, byte_limit)
        actual_size = len(raw)
        if descriptor["bytes"] != actual_size:
            raise GraceLoopError(f"capsule byte-count mismatch: {name}")
        if name == "report.md" and actual_size > MAX_REPORT_BYTES:
            raise GraceLoopError("capsule report exceeds the bounded report size")
        if name != "report.md" and actual_size > MAX_JSON_BYTES:
            raise GraceLoopError(f"capsule member exceeds the bounded JSON size: {name}")
        total_bytes += actual_size
        if total_bytes > MAX_CAPSULE_BYTES:
            raise GraceLoopError("capsule exceeds the aggregate byte limit")
        if descriptor["sha256"] != sha256_bytes(raw):
            raise GraceLoopError(f"capsule checksum mismatch: {name}")
        snapshots[name] = raw
    json_values: dict[str, Any] = {}
    for name in ("study.json", "analysis.json", "frontier.json", *receipt_members):
        value = read_json_bytes(snapshots[name], name)
        if canonical_bytes(value) + b"\n" != snapshots[name]:
            raise GraceLoopError(f"capsule JSON is not canonical: {name}")
        json_values[name] = value
    receipts: dict[str, dict[str, Any]] = {}
    for name in receipt_members:
        receipt = validate_receipt(json_values[name])
        if receipt["receipt_id"] in receipts:
            raise GraceLoopError("capsule contains duplicate receipt ids")
        if _receipt_locator(receipt["receipt_id"]) != name:
            raise GraceLoopError("receipt filename is not bound to its id")
        receipts[receipt["receipt_id"]] = receipt
    study = validate_study(json_values["study.json"], receipts)
    if set(study["receipt_files"]) != set(receipt_members):
        raise GraceLoopError("study and capsule receipt locators differ")
    expected = analyze_study(study, receipts)
    observed = json_values["analysis.json"]
    if canonical_bytes(expected) != canonical_bytes(observed):
        raise GraceLoopError("analysis does not replay from the locked study and receipts")
    if canonical_bytes(frontier_document(expected)) != canonical_bytes(
        json_values["frontier.json"]
    ):
        raise GraceLoopError("frontier does not replay from the analysis")
    expected_report = report_text(expected)
    expected_report_bytes = expected_report.encode("utf-8")
    observed_report_bytes = snapshots["report.md"]
    if len(observed_report_bytes) != len(expected_report_bytes):
        raise GraceLoopError("report does not replay from the analysis")
    try:
        observed_report = observed_report_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise GraceLoopError("capsule report is not valid UTF-8") from exc
    if observed_report != expected_report:
        raise GraceLoopError("report does not replay from the analysis")
    if manifest.get("run_id") != expected["run_id"]:
        raise GraceLoopError("manifest run id mismatch")
    return study, receipts, expected, actual


def verify_capsule(capsule: Path) -> dict[str, Any]:
    _study, receipts, expected, actual = _verify_capsule_snapshots(capsule)
    return {
        "status": "SELF_CONSISTENT_UNAUTHENTICATED",
        "scientific_status": expected["scientific_status"],
        "run_id": expected["run_id"],
        "members": sorted(actual),
        "receipt_count": len(receipts),
        "empirical_n": expected["boundary"]["empirical_n"],
        "experiment_authorized": expected["boundary"]["experiment_authorized"],
    }


def _load_verified(
    capsule: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    study, receipts, analysis, _actual = _verify_capsule_snapshots(capsule)
    return study, receipts, analysis


def explain_capsule(capsule: Path, experiment_id: str) -> dict[str, Any]:
    _study, _receipts, analysis = _load_verified(capsule)
    return explain_experiment(analysis, experiment_id)


def simulate_capsule(capsule: Path, experiment_id: str, outcome_id: str) -> dict[str, Any]:
    study, receipts, _analysis = _load_verified(capsule)
    return simulate_outcome(study, receipts, experiment_id, outcome_id)
