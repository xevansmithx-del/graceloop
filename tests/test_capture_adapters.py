"""Offline ToolUniverse projections and pinned local-adapter tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from conftest import PACKAGE_ROOT, GraceLoopCase

from graceloop import capture
from graceloop.canonical import GraceLoopError, canonical_bytes, read_json, write_canonical
from graceloop.capture import (
    capture_declared_model,
    capture_gracegraph_capsule,
    capture_phytoperturb_proof,
    capture_tooluniverse,
)
from graceloop.models import validate_study
from graceloop.receipt import build_receipt

INTEGRATION_ROOT = PACKAGE_ROOT / ".integration-assets"
PHYTOPERTURB_ROOT = (
    Path(os.environ["GRACELOOP_PHYTOPERTURB_ROOT"])
    if "GRACELOOP_PHYTOPERTURB_ROOT" in os.environ
    else INTEGRATION_ROOT / "phytoperturb-proof-v0.1.0"
)
PHYTOPERTURB_PROOF = PHYTOPERTURB_ROOT / "proof-results.json"
PHYTOPERTURB_VERIFIER = PHYTOPERTURB_ROOT / "verify_proof.py"
GRACEGRAPH_SOURCE = Path(
    os.environ.get(
        "GRACELOOP_GRACEGRAPH_SOURCE",
        str(INTEGRATION_ROOT / "gracegraph"),
    )
)
GRACEGRAPH_CAPSULE = (
    Path(os.environ["GRACELOOP_GRACEGRAPH_CAPSULE"])
    if "GRACELOOP_GRACEGRAPH_CAPSULE" in os.environ
    else INTEGRATION_ROOT / "gracegraph-capsule"
)
PHYTOPERTURB_ASSETS_AVAILABLE = PHYTOPERTURB_PROOF.is_file() and PHYTOPERTURB_VERIFIER.is_file()
GRACEGRAPH_ASSETS_AVAILABLE = (
    GRACEGRAPH_SOURCE.is_dir()
    and (GRACEGRAPH_SOURCE / "SOURCE_SHA256SUMS.txt").is_file()
    and GRACEGRAPH_CAPSULE.is_dir()
)
requires_phytoperturb_assets = pytest.mark.skipif(
    not PHYTOPERTURB_ASSETS_AVAILABLE,
    reason="exact pinned PhytoPerturb proof assets are not installed",
)
requires_gracegraph_assets = pytest.mark.skipif(
    not GRACEGRAPH_ASSETS_AVAILABLE,
    reason="exact pinned GraceGraph source and capsule assets are not installed",
)


def test_declared_model_fixed_timestamp_is_replayable_and_validated(
    tmp_path: Path,
    ckx_builder: Any,
) -> None:
    declaration_path = tmp_path / "declared-model.json"
    write_canonical(declaration_path, ckx_builder.declaration())
    arguments = (
        declaration_path,
        "R_FIXED_TIMESTAMP",
        "SYNTHETIC_FIXED_TIMESTAMP_TEST",
    )

    first = capture_declared_model(
        *arguments,
        captured_at_utc="2026-08-28T00:00:00Z",
    )
    second = capture_declared_model(
        *arguments,
        captured_at_utc="2026-08-28T00:00:00Z",
    )

    assert canonical_bytes(first) == canonical_bytes(second)
    assert first["core"]["payload"]["captured_at_utc"] == "2026-08-28T00:00:00Z"
    with pytest.raises(GraceLoopError, match="whole-second UTC timestamp"):
        capture_declared_model(
            *arguments,
            captured_at_utc="2026-02-30T00:00:00Z",
        )


def _config(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    receipt_id: str = "R_OFFLINE_CAPTURE",
) -> dict[str, Any]:
    return {
        "schema_version": "graceloop.capture-tooluniverse.v1",
        "receipt_id": receipt_id,
        "tool_name": tool_name,
        "arguments": arguments,
        "evidence_family": "OFFLINE_ADVERSARIAL_CAPTURE",
        "subject_alias": None,
        "reference_frame_id": None,
    }


def _offline_capture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    config: dict[str, Any],
    response: Any,
    *,
    returncode: int = 0,
) -> dict[str, Any]:
    fake_tu = tmp_path / "tu"
    fake_tu.write_bytes(b"pinned fake ToolUniverse executable for offline tests\n")
    stdout = response if isinstance(response, bytes) else canonical_bytes(response)
    monkeypatch.setattr(
        capture.shutil,
        "which",
        lambda name: str(fake_tu) if name == "tu" else None,
    )
    monkeypatch.setattr(capture, "_tool_version", lambda path: "1.4.1-test")
    monkeypatch.setattr(
        capture,
        "_run_bounded_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0] if args else [],
            returncode=returncode,
            stdout=stdout,
            stderr=b"offline fixture stderr" if returncode else b"",
        ),
    )
    return capture_tooluniverse(deepcopy(config))


def test_safe_projection_drops_unregistered_raw_fields_and_marks_partial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw_sequence = "acgt" * 30
    receipt = _offline_capture(
        monkeypatch,
        tmp_path,
        _config(
            "PubMed_search_articles",
            {"query": "CKX", "limit": 1, "include_abstract": False},
        ),
        {
            "status": "success",
            "data": [
                {
                    "pmid": "21224426",
                    "title": "A safe projected title",
                    "url": "https://pubmed.ncbi.nlm.nih.gov/21224426/",
                    "abstract": "must not enter the projection",
                    "protein_sequence": raw_sequence,
                }
            ],
            "metadata": {"total": 1},
        },
    )
    core = receipt["core"]
    record = core["payload"]["projection"]["records"][0]
    projected_bytes = canonical_bytes(core["payload"]["projection"]).decode("utf-8")

    assert set(record) == {"pmid", "title", "url"}
    assert "abstract" not in projected_bytes
    assert raw_sequence not in projected_bytes
    assert core["payload"]["projection_omitted_field_count"] == 2
    assert core["execution"]["state"] == "PARTIAL"
    assert "PROJECTION_SCHEMA_FIELDS_DROPPED" in core["execution"]["coverage"]["reason_codes"]


def test_safe_projection_encodes_floats_as_decimal_strings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt = _offline_capture(
        monkeypatch,
        tmp_path,
        _config("NCBIDatasets_get_genome_assembly", {"accession": "GCF_029168945.1"}),
        {
            "status": "success",
            "data": {"accession": "GCF_029168945.1", "gc_percent": 34.5},
            "metadata": {},
        },
    )

    assert receipt["core"]["payload"]["projection"]["data"]["gc_percent"] == "34.5"
    assert receipt["core"]["execution"]["state"] == "COMPLETE"


def test_nested_ncbi_search_count_drives_partial_coverage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt = _offline_capture(
        monkeypatch,
        tmp_path,
        _config("NCBIGene_search", {"term": "Cannabis CKX", "retmax": 2}),
        {
            "status": "success",
            "data": {
                "esearchresult": {
                    "count": "3",
                    "idlist": ["115705068", "115704143"],
                    "querytranslation": "Cannabis CKX",
                }
            },
        },
    )
    coverage = receipt["core"]["execution"]["coverage"]

    assert receipt["core"]["execution"]["state"] == "PARTIAL"
    assert coverage == {
        "mode": "QUERY_SLICE",
        "requested": 3,
        "examined": 2,
        "skipped": 1,
        "failed": 0,
        "reason_codes": ["PAGINATED_SOURCE_NOT_EXHAUSTED"],
    }


def test_unknown_search_total_is_partial_not_a_census(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt = _offline_capture(
        monkeypatch,
        tmp_path,
        _config("OMA_resolve_xref", {"search": "XP_030488167.2", "limit": 25}),
        {"status": "success", "data": [{"omaid": "CANSA00001"}]},
    )
    coverage = receipt["core"]["execution"]["coverage"]

    assert receipt["core"]["execution"]["state"] == "PARTIAL"
    assert coverage["mode"] == "QUERY_SLICE"
    assert coverage["examined"] == 1
    assert coverage["reason_codes"] == ["SOURCE_TOTAL_UNKNOWN"]


def test_no_result_has_query_metadata_only_and_is_not_an_absence_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt = _offline_capture(
        monkeypatch,
        tmp_path,
        _config("OMA_resolve_xref", {"search": "XP_030488167.2", "limit": 25}),
        {"status": "success", "data": [], "metadata": {"total": 0}},
    )
    core = receipt["core"]

    assert core["execution"]["state"] == "PARTIAL"
    assert core["capabilities"] == ["QUERY_EXECUTION_METADATA"]
    assert "NO_RESULT_IN_RESPONSE" in core["execution"]["coverage"]["reason_codes"]
    assert core["payload"]["result_disposition"] == ("NO_RESULT_IN_RESPONSE_NOT_AN_ABSENCE_CLAIM")
    assert "NO_ABSENCE_CLAIM" in core["prohibitions"]


def test_oma_nonmapping_slice_drops_orthology_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt = _offline_capture(
        monkeypatch,
        tmp_path,
        _config("OMA_resolve_xref", {"search": "XP_030488167.2", "limit": 25}),
        {
            "status": "success",
            "data": [{"id": "XP_030488167.2", "mapping_status": "not_found"}],
            "metadata": {"total": 1},
        },
    )
    core = receipt["core"]

    assert core["execution"]["state"] == "COMPLETE"
    assert "ORTHOLOGY_PROJECTION" not in core["capabilities"]
    assert core["payload"]["result_disposition"] == (
        "NO_MAPPING_IN_RETURNED_SLICE_NOT_AN_ABSENCE_CLAIM"
    )


def test_tool_process_failure_has_query_execution_capability_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt = _offline_capture(
        monkeypatch,
        tmp_path,
        _config("NCBIDatasets_get_gene", {"gene_id": "115705068"}),
        b"tool failed before emitting JSON",
        returncode=2,
    )
    core = receipt["core"]

    assert core["execution"]["state"] == "FAILED"
    assert core["capabilities"] == ["QUERY_EXECUTION_METADATA"]
    assert core["execution"]["coverage"]["reason_codes"] == ["TOOL_EXECUTION_FAILED"]
    assert core["payload"]["projection"] == {"failure_code": "TOOL_PROCESS_OR_RESPONSE_FAILURE"}


@requires_phytoperturb_assets
def test_phytoperturb_pinned_adapter_happy_path() -> None:
    receipt = capture_phytoperturb_proof(
        PHYTOPERTURB_PROOF,
        "R_PHYTOPERTURB_OFFLINE_TEST",
        "LOCAL_PHYTOPERTURB_PIN_TEST",
        verifier_path=PHYTOPERTURB_VERIFIER,
    )
    core = receipt["core"]

    assert core["execution"]["state"] == "COMPLETE"
    assert core["capabilities"] == ["DESIGN_STRUCTURE", "MODEL_PREDICTION"]
    assert core["payload"]["verifier_result"]["valid"] is True
    assert core["payload"]["projection"]["experiment_authorized"] is False
    assert "NO_TARGET_SELECTION" in core["prohibitions"]


@requires_phytoperturb_assets
def test_phytoperturb_rejects_mutated_proof_before_execution(tmp_path: Path) -> None:
    mutated = tmp_path / "proof-results.json"
    mutated.write_bytes(PHYTOPERTURB_PROOF.read_bytes() + b" ")

    with pytest.raises(GraceLoopError, match="does not match the registered artifact digest"):
        capture_phytoperturb_proof(
            mutated,
            "R_PHYTOPERTURB_MUTATED_PROOF",
            "LOCAL_PHYTOPERTURB_PIN_TEST",
            verifier_path=PHYTOPERTURB_VERIFIER,
        )


@requires_phytoperturb_assets
def test_phytoperturb_rejects_mutated_verifier_before_execution(tmp_path: Path) -> None:
    mutated = tmp_path / "verify_proof.py"
    mutated.write_bytes(PHYTOPERTURB_VERIFIER.read_bytes() + b"\n")

    with pytest.raises(GraceLoopError, match="does not match the registered source digest"):
        capture_phytoperturb_proof(
            PHYTOPERTURB_PROOF,
            "R_PHYTOPERTURB_MUTATED_VERIFIER",
            "LOCAL_PHYTOPERTURB_PIN_TEST",
            verifier_path=mutated,
        )


@requires_gracegraph_assets
def test_gracegraph_pinned_adapter_happy_path() -> None:
    receipt = capture_gracegraph_capsule(
        GRACEGRAPH_CAPSULE,
        GRACEGRAPH_SOURCE,
        "R_GRACEGRAPH_OFFLINE_TEST",
        "LOCAL_GRACEGRAPH_PIN_TEST",
    )
    core = receipt["core"]

    assert core["execution"]["state"] == "COMPLETE"
    assert core["capabilities"] == ["DESIGN_STRUCTURE"]
    assert core["payload"]["verification_status"] == "PASS_SEALED_BYTES_ONLY"
    assert core["payload"]["claim_boundary"]["empirical_n"] == 0


@requires_gracegraph_assets
def test_gracegraph_rejects_mutated_claim_boundary(tmp_path: Path) -> None:
    mutated = tmp_path / "gracegraph-capsule"
    shutil.copytree(GRACEGRAPH_CAPSULE, mutated)
    evaluation_path = mutated / "evaluation.json"
    evaluation = read_json(evaluation_path)
    evaluation["claim_boundary"]["empirical_n"] = 1
    write_canonical(evaluation_path, evaluation)

    with pytest.raises(GraceLoopError, match="exceeds the N=0 claim boundary"):
        capture_gracegraph_capsule(
            mutated,
            GRACEGRAPH_SOURCE,
            "R_GRACEGRAPH_MUTATED_BOUNDARY",
            "LOCAL_GRACEGRAPH_PIN_TEST",
        )


def _study_with_gracegraph_base(
    ckx_case: GraceLoopCase,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], str]:
    if not GRACEGRAPH_ASSETS_AVAILABLE:
        pytest.skip("exact pinned GraceGraph source and capsule assets are not installed")
    receipt_id = "R_GRACEGRAPH_OFFLINE_BASE"
    base_receipt = capture_gracegraph_capsule(
        GRACEGRAPH_CAPSULE,
        GRACEGRAPH_SOURCE,
        receipt_id,
        "LOCAL_GRACEGRAPH_PIN_TEST",
    )
    payload = base_receipt["core"]["payload"]
    study = deepcopy(ckx_case.study)
    study["base_capsule"] = {
        "run_id": payload["capsule_run_id"],
        "manifest_sha256": payload["capsule_manifest_sha256"],
        "receipt_id": receipt_id,
    }
    study["receipt_files"].append(f"receipts/{receipt_id}.json")
    study["context_receipt_ids"].append(receipt_id)
    receipts = {**ckx_case.receipts, receipt_id: base_receipt}
    return study, receipts, receipt_id


@pytest.mark.parametrize(
    "missing_field",
    [
        "static_verification_status",
        "static_verification_sha256",
        "static_verification_bytes",
        "live_replay_status",
        "source_capsule_embedded",
    ],
)
def test_gracegraph_base_requires_every_diagnostic_field(
    ckx_case: GraceLoopCase,
    missing_field: str,
) -> None:
    study, receipts, receipt_id = _study_with_gracegraph_base(ckx_case)
    validate_study(study, receipts)
    core = deepcopy(receipts[receipt_id]["core"])
    del core["payload"][missing_field]
    receipts[receipt_id] = build_receipt(receipt_id, core)

    with pytest.raises(GraceLoopError, match="base capsule receipt payload"):
        validate_study(study, receipts)


def test_gracegraph_base_rejects_producer_and_output_masquerade(
    ckx_case: GraceLoopCase,
) -> None:
    study, receipts, receipt_id = _study_with_gracegraph_base(ckx_case)
    core = deepcopy(receipts[receipt_id]["core"])
    core["producer"]["tool"] = "Masquerading tool"
    core["producer"]["source_sha256"] = "0" * 64
    core["execution"]["parameter_lock_sha256"] = "1" * 64
    manifest_output = next(
        item for item in core["execution"]["outputs"] if item["role"] == "capsule-manifest"
    )
    manifest_output["sha256"] = "2" * 64
    receipts[receipt_id] = build_receipt(receipt_id, core)

    with pytest.raises(GraceLoopError, match="internal bindings are not exact"):
        validate_study(study, receipts)


def test_gracegraph_base_live_diagnostic_cannot_upgrade_provenance(
    ckx_case: GraceLoopCase,
) -> None:
    study, receipts, receipt_id = _study_with_gracegraph_base(ckx_case)
    core = deepcopy(receipts[receipt_id]["core"])
    core["payload"]["verification_status"] = "PASS_LIVE_REPLAY"
    receipts[receipt_id] = build_receipt(receipt_id, core)

    with pytest.raises(
        GraceLoopError,
        match="does not prove the declared structural base",
    ):
        validate_study(study, receipts)
