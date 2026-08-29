"""Mutation tests for empirical boundaries and semantic receipt bindings."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

import pytest
from conftest import MODEL_RECEIPT_ID, GraceLoopCase

from graceloop import models
from graceloop.canonical import GraceLoopError
from graceloop.frontier import analyze_study
from graceloop.models import fixed_boundary, validate_study
from graceloop.receipt import build_receipt

ALL_SIX = "E_ALL_SIX_IDENTITY_EXPRESSION"


def _all_six(study: dict[str, Any]) -> dict[str, Any]:
    return next(item for item in study["experiments"] if item["id"] == ALL_SIX)


def _rebuild_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    return build_receipt(receipt["receipt_id"], receipt["core"])


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("empirical_n", False),
        ("experiments_performed", False),
        ("biological_gates_closed", False),
        ("results_present", 0),
        ("target_selected", 0),
        ("experiment_authorized", 0),
    ],
)
def test_boundary_rejects_bool_int_substitution(
    ckx_case: GraceLoopCase,
    field: str,
    replacement: bool | int,
) -> None:
    study = deepcopy(ckx_case.study)
    study["boundary"][field] = replacement

    with pytest.raises(GraceLoopError, match="exact empirical-N=0 alpha state"):
        validate_study(study, ckx_case.receipts)


def test_exported_boundary_mutation_cannot_poison_validation_authority(
    ckx_case: GraceLoopCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(models.BOUNDARY, "empirical_n", 999)
    monkeypatch.setitem(models.BOUNDARY, "target_selected", True)

    analysis = analyze_study(ckx_case.study, ckx_case.receipts)

    assert analysis["boundary"] == fixed_boundary()
    assert analysis["boundary"]["empirical_n"] == 0
    assert analysis["boundary"]["target_selected"] is False


def test_observation_receipt_is_rejected_at_empirical_n_zero(ckx_case: GraceLoopCase) -> None:
    observation_core = deepcopy(ckx_case.receipts[MODEL_RECEIPT_ID]["core"])
    observation_core["kind"] = "OBSERVATION"
    observation_core["capabilities"] = ["OBSERVED_OUTCOME"]
    observation = build_receipt("R_FORBIDDEN_OBSERVATION", observation_core)
    receipts = {**ckx_case.receipts, observation["receipt_id"]: observation}
    study = deepcopy(ckx_case.study)
    study["receipt_files"].append("receipts/R_FORBIDDEN_OBSERVATION.json")
    study["context_receipt_ids"].append(observation["receipt_id"])

    with pytest.raises(GraceLoopError, match="empirical but the v1 study boundary is N=0"):
        validate_study(study, receipts)


def _mutate_decision(study: dict[str, Any]) -> None:
    study["decision"]["question"] += " Altered after receipt compilation."


def _mutate_world(study: dict[str, Any]) -> None:
    study["worlds"][0]["label"] += " Altered after receipt compilation."


def _mutate_gate(study: dict[str, Any]) -> None:
    study["gates"][0]["label"] += " Altered after receipt compilation."


def _mutate_outcome(study: dict[str, Any]) -> None:
    _all_six(study)["outcomes"][0]["label"] += " Altered after receipt compilation."


def _mutate_prediction(study: dict[str, Any]) -> None:
    experiment = _all_six(study)
    prediction = next(
        item
        for item in experiment["predictions"]
        if item["world_id"] == "W_CKX2_ONLY" and item["outcome_id"] == "O_POSITIVE"
    )
    prediction["relation"] = "UNKNOWN"


def _mutate_resource(study: dict[str, Any]) -> None:
    _all_six(study)["resources"]["relative_cost"] += 1


@pytest.mark.parametrize(
    "mutator",
    [
        _mutate_decision,
        _mutate_world,
        _mutate_gate,
        _mutate_outcome,
        _mutate_prediction,
        _mutate_resource,
    ],
    ids=["decision", "world", "gate", "outcome", "prediction", "resource"],
)
def test_any_semantic_mutation_breaks_prediction_or_protocol_binding(
    ckx_case: GraceLoopCase,
    mutator: Callable[[dict[str, Any]], None],
) -> None:
    study = deepcopy(ckx_case.study)
    mutator(study)

    with pytest.raises(GraceLoopError):
        validate_study(study, ckx_case.receipts)


def test_mutating_embedded_protocol_lock_breaks_receipt_binding(
    ckx_case: GraceLoopCase,
) -> None:
    receipt = deepcopy(ckx_case.receipts[MODEL_RECEIPT_ID])
    declaration = next(
        item for item in receipt["core"]["payload"]["declared_experiments"] if item["id"] == ALL_SIX
    )
    declaration["protocol_lock"]["purpose_code"] = "ALTERED_PURPOSE"
    altered = _rebuild_receipt(receipt)

    with pytest.raises(
        GraceLoopError,
        match=(
            "binding digest is inconsistent|lacks a receipt-bound protocol and model matrix|"
            "protocol lock purpose does not match"
        ),
    ):
        validate_study(ckx_case.study, {MODEL_RECEIPT_ID: altered})


def test_mutating_embedded_compiled_matrix_breaks_receipt_binding(
    ckx_case: GraceLoopCase,
) -> None:
    receipt = deepcopy(ckx_case.receipts[MODEL_RECEIPT_ID])
    compiled = next(
        item for item in receipt["core"]["payload"]["compiled_experiments"] if item["id"] == ALL_SIX
    )
    prediction = next(
        item
        for item in compiled["predictions"]
        if item["world_id"] == "W_CKX2_ONLY" and item["outcome_id"] == "O_POSITIVE"
    )
    prediction["relation"] = "UNKNOWN"
    altered = _rebuild_receipt(receipt)

    with pytest.raises(
        GraceLoopError,
        match="(binding digest is inconsistent|lacks a receipt-bound protocol and model matrix)",
    ):
        validate_study(ckx_case.study, {MODEL_RECEIPT_ID: altered})


@pytest.mark.parametrize("payload_field", ["decision", "worlds", "gates"])
def test_declared_receipt_context_must_equal_study_context(
    ckx_case: GraceLoopCase,
    payload_field: str,
) -> None:
    receipt = deepcopy(ckx_case.receipts[MODEL_RECEIPT_ID])
    value = receipt["core"]["payload"][payload_field]
    if payload_field == "decision":
        value["question"] += " Contradictory receipt text."
    else:
        value[0]["label"] += " Contradictory receipt text."
    altered = _rebuild_receipt(receipt)

    with pytest.raises(GraceLoopError, match=f"receipt {payload_field} contradict"):
        validate_study(ckx_case.study, {MODEL_RECEIPT_ID: altered})


@pytest.mark.parametrize(
    "mutation",
    ["parameter", "input-role", "output-role", "output-bytes", "duplicate-binding"],
)
def test_declared_receipt_execution_and_binding_descriptors_are_exact(
    ckx_case: GraceLoopCase,
    mutation: str,
) -> None:
    receipt = deepcopy(ckx_case.receipts[MODEL_RECEIPT_ID])
    execution = receipt["core"]["execution"]
    payload = receipt["core"]["payload"]
    if mutation == "parameter":
        execution["parameter_lock_sha256"] = "0" * 64
    elif mutation == "input-role":
        execution["inputs"][0]["role"] = "wrong-model-declaration"
    elif mutation == "output-role":
        execution["outputs"][0]["role"] = "wrong-output-role"
    elif mutation == "output-bytes":
        execution["outputs"][0]["bytes"] += 1
    else:
        payload["experiment_bindings"].append(deepcopy(payload["experiment_bindings"][0]))
    altered = _rebuild_receipt(receipt)

    with pytest.raises(GraceLoopError):
        validate_study(ckx_case.study, {MODEL_RECEIPT_ID: altered})


def test_malformed_compiled_receipt_item_fails_with_domain_error(
    ckx_case: GraceLoopCase,
) -> None:
    receipt = deepcopy(ckx_case.receipts[MODEL_RECEIPT_ID])
    compiled = receipt["core"]["payload"]["compiled_experiments"][0]
    declared = receipt["core"]["payload"]["declared_experiments"][0]
    del compiled["execution_class"]
    del declared["execution_class"]
    altered = _rebuild_receipt(receipt)

    with pytest.raises(GraceLoopError, match="compiled experiment schema is not exact"):
        validate_study(ckx_case.study, {MODEL_RECEIPT_ID: altered})


def test_partial_model_receipt_cannot_support_decisive_cells(ckx_case: GraceLoopCase) -> None:
    receipt = deepcopy(ckx_case.receipts[MODEL_RECEIPT_ID])
    receipt["core"]["execution"]["state"] = "PARTIAL"
    partial = _rebuild_receipt(receipt)

    with pytest.raises(GraceLoopError, match="cannot rely on failed or not-run receipts"):
        validate_study(ckx_case.study, {MODEL_RECEIPT_ID: partial})


@pytest.mark.parametrize("residual_world_count", [0, 2])
def test_world_model_requires_exactly_one_open_residual(
    ckx_case: GraceLoopCase,
    residual_world_count: int,
) -> None:
    study = deepcopy(ckx_case.study)
    for world in study["worlds"]:
        world["open_world_residual"] = False
    for world in study["worlds"][:residual_world_count]:
        world["open_world_residual"] = True

    with pytest.raises(GraceLoopError, match="exactly one declared world"):
        validate_study(study, ckx_case.receipts)


def test_prediction_matrix_must_be_total(ckx_case: GraceLoopCase) -> None:
    study = deepcopy(ckx_case.study)
    _all_six(study)["predictions"].pop()

    with pytest.raises(GraceLoopError, match="prediction matrix is not total"):
        validate_study(study, ckx_case.receipts)


def test_failure_branch_cannot_encode_affirmative_update(ckx_case: GraceLoopCase) -> None:
    study = deepcopy(ckx_case.study)
    experiment = _all_six(study)
    failure = next(
        item
        for item in experiment["predictions"]
        if item["world_id"] == "W_CKX2_ONLY" and item["outcome_id"] == "O_QC_FAILED"
    )
    failure["relation"] = "PERMITS"

    with pytest.raises(GraceLoopError, match="failure branch .* must preserve"):
        validate_study(study, ckx_case.receipts)
