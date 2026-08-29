"""Adversarial serialization, privacy, and receipt-ceiling tests."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from conftest import MODEL_RECEIPT_ID, GraceLoopCase

from graceloop.canonical import (
    MAX_JSON_BYTES,
    GraceLoopError,
    canonical_bytes,
    read_json,
    read_json_bytes,
    reject_floats,
    reject_private_material,
)
from graceloop.receipt import build_receipt, validate_receipt


def test_duplicate_json_keys_are_rejected_at_every_depth() -> None:
    with pytest.raises(GraceLoopError, match="duplicate JSON key: repeated"):
        read_json_bytes(
            b'{"outer":{"repeated":1,"repeated":2}}',
            "duplicate fixture",
        )


def test_oversized_json_file_is_rejected_from_stat_before_parse(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as handle:
        handle.truncate(MAX_JSON_BYTES + 1)

    with pytest.raises(GraceLoopError, match=f"exceeds {MAX_JSON_BYTES} bytes"):
        read_json(oversized)


def test_oversized_json_byte_buffer_is_rejected() -> None:
    with pytest.raises(GraceLoopError, match=f"exceeds {MAX_JSON_BYTES} bytes"):
        read_json_bytes(b" " * (MAX_JSON_BYTES + 1), "oversized buffer")


def test_deeply_nested_json_is_wrapped_as_fail_closed_error() -> None:
    raw = ("[" * 2000 + "0" + "]" * 2000).encode("ascii")
    with pytest.raises(GraceLoopError, match="cannot parse"):
        read_json_bytes(raw, "deep nesting")


def test_oversized_json_integer_is_rejected_without_raw_value_error() -> None:
    raw = ("{" + '"integer":' + "9" * 5000 + "}").encode("ascii")
    with pytest.raises(GraceLoopError, match="integer exceeds"):
        read_json_bytes(raw, "oversized integer")


@pytest.mark.parametrize(
    "value",
    [
        0.5,
        {"nested": [1, {"decimal": 0.125}]},
        [{"still_nested": -2.5}],
    ],
)
def test_floats_are_rejected_recursively(value: Any) -> None:
    with pytest.raises(GraceLoopError, match="decimals as strings"):
        reject_floats(value)


def test_nonfinite_float_cannot_be_canonicalized() -> None:
    with pytest.raises(GraceLoopError, match="not canonical JSON"):
        canonical_bytes({"not_a_number": float("nan")})


def test_public_https_and_doi_urls_are_not_treated_as_private_paths() -> None:
    reject_private_material(
        {
            "doi_url": "https://doi.org/10.1038/s41586-026-00001-1",
            "record_url": "https://www.ncbi.nlm.nih.gov/gene/115705068",
            "repository_url": "https://github.com/example/project/tree/main/docs",
        }
    )


@pytest.mark.parametrize(
    "private_value",
    [
        "/" + "Users/researcher/private/sample.json",
        "file:///private/var/tmp/sample.json",
        "~/confidential/sample.json",
        r"C:\Users\researcher\sample.json",
        "gh" + "p_abcdefghijklmnopqrstuvwxyz123456",
    ],
)
def test_private_paths_and_credentials_are_rejected(private_value: str) -> None:
    with pytest.raises(GraceLoopError, match="forbidden path or credential material"):
        reject_private_material(private_value)


@pytest.mark.parametrize(
    "sequence_value",
    [
        "acgt" * 20,
        "acdefghiklmnpqrstvwy" * 4,
        ["acdefghiklmnpqrstvwy" * 2, "acdefghiklmnpqrstvwy" * 2],
        ["acgt" * 10, "acgt" * 10],
    ],
    ids=["lowercase-dna", "lowercase-protein", "chunked-protein", "chunked-dna"],
)
def test_raw_sequence_material_is_rejected_even_when_lowercase_or_chunked(
    sequence_value: str | list[str],
) -> None:
    with pytest.raises(GraceLoopError, match="sequence-like material"):
        reject_private_material(sequence_value)


def test_sequence_field_is_rejected_even_when_too_short_for_heuristic() -> None:
    with pytest.raises(GraceLoopError, match="forbidden sequence field"):
        reject_private_material({"protein_sequence": "MKT"})


def _top_level_extra(receipt: dict[str, Any]) -> None:
    receipt["unexpected"] = True


def _top_level_missing(receipt: dict[str, Any]) -> None:
    del receipt["attestations"]


def _core_extra(receipt: dict[str, Any]) -> None:
    receipt["core"]["unexpected"] = True


def _core_missing(receipt: dict[str, Any]) -> None:
    del receipt["core"]["lineage"]


def _producer_extra(receipt: dict[str, Any]) -> None:
    receipt["core"]["producer"]["unexpected"] = True


def _execution_missing(receipt: dict[str, Any]) -> None:
    del receipt["core"]["execution"]["coverage"]


def _coverage_extra(receipt: dict[str, Any]) -> None:
    receipt["core"]["execution"]["coverage"]["unexpected"] = 0


def _calibration_extra(receipt: dict[str, Any]) -> None:
    receipt["core"]["calibration"]["unexpected"] = "NONE"


def _descriptor_extra(receipt: dict[str, Any]) -> None:
    receipt["core"]["execution"]["outputs"][0]["unexpected"] = True


@pytest.mark.parametrize(
    "mutator",
    [
        _top_level_extra,
        _top_level_missing,
        _core_extra,
        _core_missing,
        _producer_extra,
        _execution_missing,
        _coverage_extra,
        _calibration_extra,
        _descriptor_extra,
    ],
    ids=[
        "top-extra",
        "top-missing",
        "core-extra",
        "core-missing",
        "producer-extra",
        "execution-missing",
        "coverage-extra",
        "calibration-extra",
        "descriptor-extra",
    ],
)
def test_receipt_objects_use_exact_schemas(
    ckx_case: GraceLoopCase,
    mutator: Callable[[dict[str, Any]], None],
) -> None:
    receipt = deepcopy(ckx_case.receipts[MODEL_RECEIPT_ID])
    mutator(receipt)

    with pytest.raises(GraceLoopError):
        validate_receipt(receipt)


def test_receipt_descriptor_rejects_boolean_as_integer(ckx_case: GraceLoopCase) -> None:
    receipt = deepcopy(ckx_case.receipts[MODEL_RECEIPT_ID])
    receipt["core"]["execution"]["outputs"][0]["bytes"] = False

    with pytest.raises(GraceLoopError, match="bytes must be a nonnegative integer"):
        validate_receipt(receipt)


def test_receipt_payload_rejects_float_after_hash_rebuild(ckx_case: GraceLoopCase) -> None:
    core = deepcopy(ckx_case.receipts[MODEL_RECEIPT_ID]["core"])
    core["payload"]["decimal_measurement"] = 0.5

    with pytest.raises(GraceLoopError, match="decimals as strings"):
        build_receipt(MODEL_RECEIPT_ID, core)


def test_failed_receipt_cannot_retain_result_capabilities(ckx_case: GraceLoopCase) -> None:
    core = deepcopy(ckx_case.receipts[MODEL_RECEIPT_ID]["core"])
    core["kind"] = "SOURCE_SNAPSHOT"
    core["execution"]["state"] = "FAILED"
    core["execution"]["coverage"] = {
        "mode": "NOT_APPLICABLE",
        "requested": 0,
        "examined": 0,
        "skipped": 0,
        "failed": 0,
        "reason_codes": ["TOOL_EXECUTION_FAILED"],
    }
    core["calibration"] = {
        "state": "NOT_APPLICABLE",
        "certificate_receipt_id": "NONE",
        "domain_digest": "NONE",
    }
    core["capabilities"] = ["QUERY_EXECUTION_METADATA", "IDENTIFIER_METADATA"]
    core["payload"] = {"failure_code": "TOOL_PROCESS_OR_RESPONSE_FAILURE"}

    with pytest.raises(GraceLoopError, match="failed/not-run.*metadata only"):
        build_receipt("R_FAILED_WITH_RESULT_CAPABILITY", core)
