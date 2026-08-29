"""Sealing, tamper detection, and inventory tests for GraceLoop capsules."""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from graceloop import capsule as capsule_module
from graceloop.canonical import (
    GraceLoopError,
    read_json,
    sha256_file,
    write_canonical,
)
from graceloop.capsule import compile_capsule, explain_capsule, verify_capsule


@pytest.fixture
def compiled_capsule(tmp_path: Path, capsule_source: Path) -> tuple[Path, Path]:
    destination = tmp_path / "capsule"
    compile_capsule(capsule_source, destination)
    return capsule_source, destination


def test_compiled_capsule_replays_with_exact_n_zero_boundary(
    compiled_capsule: tuple[Path, Path],
) -> None:
    _source, capsule = compiled_capsule

    result = verify_capsule(capsule)

    assert result["status"] == "SELF_CONSISTENT_UNAUTHENTICATED"
    assert result["scientific_status"] == "PLAN_ONLY_NO_EMPIRICAL_EVIDENCE"
    assert result["empirical_n"] == 0
    assert result["experiment_authorized"] is False
    assert result["receipt_count"] == 1
    assert result["run_id"] == read_json(capsule / "analysis.json")["run_id"]


def test_compile_refuses_overwrite_and_preserves_original_capsule(
    compiled_capsule: tuple[Path, Path],
) -> None:
    source, capsule = compiled_capsule
    original_manifest = (capsule / "manifest.json").read_bytes()

    with pytest.raises(GraceLoopError, match="refusing to overwrite"):
        compile_capsule(source, capsule)

    assert (capsule / "manifest.json").read_bytes() == original_manifest
    assert verify_capsule(capsule)["status"] == "SELF_CONSISTENT_UNAUTHENTICATED"


def test_payload_byte_tamper_is_detected(compiled_capsule: tuple[Path, Path]) -> None:
    _source, capsule = compiled_capsule
    report = capsule / "report.md"
    report.write_text(report.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")

    with pytest.raises(GraceLoopError, match="(checksum|byte-count) mismatch"):
        verify_capsule(capsule)


def test_extra_root_member_is_rejected(compiled_capsule: tuple[Path, Path]) -> None:
    _source, capsule = compiled_capsule
    (capsule / "unregistered.txt").write_text("extra", encoding="utf-8")

    with pytest.raises(GraceLoopError, match="top-level inventory mismatch"):
        verify_capsule(capsule)


def test_empty_nested_directory_is_rejected(compiled_capsule: tuple[Path, Path]) -> None:
    _source, capsule = compiled_capsule
    (capsule / "receipts" / "nested").mkdir()

    with pytest.raises(GraceLoopError, match="unexpected directory"):
        verify_capsule(capsule)


def test_hardlinked_payload_is_rejected(compiled_capsule: tuple[Path, Path]) -> None:
    _source, capsule = compiled_capsule
    report = capsule / "report.md"
    report.unlink()
    os.link(capsule / "analysis.json", report)

    with pytest.raises(GraceLoopError, match="single-link regular files"):
        verify_capsule(capsule)


def test_symlinked_capsule_root_is_rejected(
    tmp_path: Path,
    compiled_capsule: tuple[Path, Path],
) -> None:
    _source, capsule = compiled_capsule
    link = tmp_path / "capsule-link"
    link.symlink_to(capsule, target_is_directory=True)

    with pytest.raises(GraceLoopError, match="root must not be a symlink"):
        verify_capsule(link)


def test_manifest_byte_count_rejects_boolean_integer_alias(
    compiled_capsule: tuple[Path, Path],
) -> None:
    _source, capsule = compiled_capsule
    manifest_path = capsule / "manifest.json"
    manifest = read_json(manifest_path)
    manifest["members"]["analysis.json"]["bytes"] = True
    write_canonical(manifest_path, manifest)

    with pytest.raises(GraceLoopError, match="bytes must be a nonnegative integer"):
        verify_capsule(capsule)


def test_oversize_report_fails_before_unbounded_text_read(
    compiled_capsule: tuple[Path, Path],
) -> None:
    _source, capsule = compiled_capsule
    report = capsule / "report.md"
    with report.open("wb") as handle:
        handle.truncate(capsule_module.MAX_REPORT_BYTES + 1)
    manifest_path = capsule / "manifest.json"
    manifest = read_json(manifest_path)
    manifest["members"]["report.md"] = {
        "sha256": sha256_file(report),
        "bytes": report.stat().st_size,
    }
    write_canonical(manifest_path, manifest)

    with pytest.raises(GraceLoopError, match="report exceeds"):
        verify_capsule(capsule)


def test_explain_uses_verified_snapshot_after_concurrent_path_mutation(
    compiled_capsule: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, capsule = compiled_capsule
    original = capsule_module._verify_capsule_snapshots

    def racing_verify(path: Path):
        snapshots = original(path)
        write_canonical(path / "analysis.json", {"unverified": "replacement"})
        return snapshots

    monkeypatch.setattr(capsule_module, "_verify_capsule_snapshots", racing_verify)
    explanation = explain_capsule(capsule, "E_ALL_SIX_IDENTITY_EXPRESSION")

    assert explanation["experiment"]["id"] == "E_ALL_SIX_IDENTITY_EXPRESSION"
    assert explanation["verification_scope"] == ("COUNTERFACTUAL_MODEL_AND_RECEIPT_STRUCTURE_ONLY")


def test_concurrent_compilers_publish_exactly_one_capsule(
    tmp_path: Path,
    capsule_source: Path,
) -> None:
    destination = tmp_path / "capsule-race"
    barrier = threading.Barrier(2)

    def compile_after_barrier() -> str:
        barrier.wait()
        try:
            compile_capsule(capsule_source, destination)
        except GraceLoopError as exc:
            assert "refusing to overwrite" in str(exc)
            return "REFUSED_NO_CLOBBER"
        return "PUBLISHED"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(lambda _index: compile_after_barrier(), range(2)))

    assert results == ["PUBLISHED", "REFUSED_NO_CLOBBER"]
    assert verify_capsule(destination)["status"] == "SELF_CONSISTENT_UNAUTHENTICATED"
    assert list(tmp_path.glob(".capsule-race.stage-*")) == []
