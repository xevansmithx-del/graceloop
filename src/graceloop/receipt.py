"""Typed scientific-receipt validation with capability, lineage, and calibration ceilings."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .canonical import (
    GraceLoopError,
    canonical_bytes,
    reject_floats,
    reject_private_material,
    require_alias,
    require_id,
    require_only_keys,
    require_sha256,
    require_string,
    require_string_list,
    sha256_bytes,
)

RECEIPT_SCHEMA = "graceloop.scientific-receipt.v1"
RECEIPT_KINDS = {
    "SOURCE_SNAPSHOT",
    "OBSERVATION",
    "CALIBRATION",
    "MODEL_PREDICTION",
    "FRAME_TRANSFORM",
    "ALIAS_EQUIVALENCE",
}
EXECUTION_STATES = {"COMPLETE", "PARTIAL", "FAILED", "NOT_RUN"}
COVERAGE_MODES = {"CENSUS", "QUERY_SLICE", "NOT_APPLICABLE"}
CALIBRATION_STATES = {
    "NOT_APPLICABLE",
    "NOT_RUN",
    "SYNTHETIC_ONLY",
    "UNCALIBRATED",
    "OUT_OF_DOMAIN",
    "CALIBRATED",
}
SUBJECT_KINDS = {"LOCUS", "PROTEIN", "FOUNDER", "SAMPLE", "EVENT", "OTHER"}
CAPABILITIES = {
    "QUERY_EXECUTION_METADATA",
    "IDENTIFIER_METADATA",
    "REFERENCE_LABEL",
    "LITERATURE_INDEX_METADATA",
    "PATHWAY_PROJECTION_METADATA",
    "DOMAIN_ANNOTATION",
    "ORTHOLOGY_PROJECTION",
    "FUNCTION_ANNOTATION",
    "DESIGN_STRUCTURE",
    "MODEL_PREDICTION",
    "OBSERVED_OUTCOME",
    "CALIBRATION_CERTIFICATE",
    "FRAME_TRANSFORM",
    "ALIAS_EQUIVALENCE",
}
KIND_ALLOWED_CAPABILITIES = {
    "SOURCE_SNAPSHOT": {
        "QUERY_EXECUTION_METADATA",
        "IDENTIFIER_METADATA",
        "REFERENCE_LABEL",
        "LITERATURE_INDEX_METADATA",
        "PATHWAY_PROJECTION_METADATA",
        "DOMAIN_ANNOTATION",
        "ORTHOLOGY_PROJECTION",
        "FUNCTION_ANNOTATION",
        "DESIGN_STRUCTURE",
    },
    "OBSERVATION": {"OBSERVED_OUTCOME"},
    "CALIBRATION": {"CALIBRATION_CERTIFICATE"},
    "MODEL_PREDICTION": {"DESIGN_STRUCTURE", "MODEL_PREDICTION"},
    "FRAME_TRANSFORM": {"FRAME_TRANSFORM"},
    "ALIAS_EQUIVALENCE": {"ALIAS_EQUIVALENCE"},
}
KIND_REQUIRED_CAPABILITY = {
    "OBSERVATION": "OBSERVED_OUTCOME",
    "CALIBRATION": "CALIBRATION_CERTIFICATE",
    "MODEL_PREDICTION": "MODEL_PREDICTION",
    "FRAME_TRANSFORM": "FRAME_TRANSFORM",
    "ALIAS_EQUIVALENCE": "ALIAS_EQUIVALENCE",
}
PROHIBITIONS = {
    "NO_BIOLOGICAL_CAUSALITY",
    "NO_TARGET_SELECTION",
    "NO_EXPERIMENT_AUTHORITY",
    "NO_ABSENCE_CLAIM",
    "NO_INDEPENDENCE_CLAIM",
    "NO_COORDINATE_EQUIVALENCE",
    "NO_FUNCTION_TRANSFER",
    "NO_EMPIRICAL_PERFORMANCE",
}
LINEAGE_FIELDS = {
    "biological_unit_cluster",
    "event_origin_cluster",
    "material_cluster",
    "library_cluster",
    "instrument_run_cluster",
    "raw_observation_root",
    "analysis_pipeline_family",
    "adjudication_family",
}
FORBIDDEN_PROBABILISTIC_KEYS = {
    "prior",
    "priors",
    "prior_odds",
    "probability",
    "probabilities",
    "likelihood",
    "likelihoods",
    "likelihood_ratio",
    "posterior",
    "posteriors",
    "bayes_factor",
    "weight",
    "weights",
    "utility",
    "utilities",
    "score",
    "scores",
    "confidence",
    "expected_value",
    "voi",
}


def _reject_probabilistic_payload(value: Any, field: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in FORBIDDEN_PROBABILISTIC_KEYS:
                raise GraceLoopError(f"{field}.{key} is forbidden in a prior-free v1 receipt")
            _reject_probabilistic_payload(item, f"{field}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_probabilistic_payload(item, f"{field}[{index}]")


def _validate_file_descriptors(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise GraceLoopError(f"{field} must be a list of objects")
    result = []
    for index, item in enumerate(value):
        label = f"{field}[{index}]"
        require_only_keys(item, {"role", "sha256", "bytes"}, label)
        role = require_id(item.get("role"), f"{label}.role")
        digest = require_sha256(item.get("sha256"), f"{label}.sha256")
        size = item.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise GraceLoopError(f"{label}.bytes must be a nonnegative integer")
        result.append({"role": role, "sha256": digest, "bytes": size})
    return sorted(result, key=lambda item: (item["role"], item["sha256"], item["bytes"]))


def validate_receipt(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise GraceLoopError("receipt must be an object")
    receipt = deepcopy(receipt)
    require_only_keys(
        receipt,
        {"schema_version", "receipt_id", "core", "core_sha256", "attestations"},
        "receipt",
    )
    if set(receipt) != {
        "schema_version",
        "receipt_id",
        "core",
        "core_sha256",
        "attestations",
    }:
        raise GraceLoopError("receipt must declare every top-level field")
    if receipt.get("schema_version") != RECEIPT_SCHEMA:
        raise GraceLoopError(f"receipt.schema_version must be {RECEIPT_SCHEMA}")
    receipt_id = require_id(receipt.get("receipt_id"), "receipt.receipt_id")
    core = receipt.get("core")
    if not isinstance(core, dict):
        raise GraceLoopError("receipt.core must be an object")
    core_keys = {
        "kind",
        "producer",
        "execution",
        "subject_alias",
        "reference_frame_id",
        "evidence_family",
        "lineage",
        "calibration",
        "capabilities",
        "prohibitions",
        "payload",
    }
    require_only_keys(core, core_keys, "receipt.core")
    if set(core) != core_keys:
        raise GraceLoopError("receipt.core must declare every field")
    if core.get("kind") not in RECEIPT_KINDS:
        raise GraceLoopError("receipt.core.kind is not registered")

    producer = core.get("producer")
    if not isinstance(producer, dict):
        raise GraceLoopError("receipt.core.producer must be an object")
    producer_keys = {
        "tool",
        "version",
        "source_sha256",
        "environment_sha256",
        "adapter_id",
        "adapter_version",
        "adapter_sha256",
    }
    require_only_keys(producer, producer_keys, "receipt.core.producer")
    if set(producer) != producer_keys:
        raise GraceLoopError("receipt producer must declare every field")
    producer["tool"] = require_string(producer.get("tool"), "producer.tool", max_length=200)
    producer["version"] = require_string(
        producer.get("version"), "producer.version", max_length=100
    )
    producer["adapter_id"] = require_id(producer.get("adapter_id"), "producer.adapter_id")
    producer["adapter_version"] = require_string(
        producer.get("adapter_version"), "producer.adapter_version", max_length=100
    )
    for field in ("source_sha256", "environment_sha256", "adapter_sha256"):
        producer[field] = require_sha256(producer.get(field), f"producer.{field}")

    execution = core.get("execution")
    if not isinstance(execution, dict):
        raise GraceLoopError("receipt.core.execution must be an object")
    execution_keys = {"state", "parameter_lock_sha256", "inputs", "outputs", "coverage"}
    require_only_keys(execution, execution_keys, "receipt.core.execution")
    if set(execution) != execution_keys:
        raise GraceLoopError("receipt execution must declare every field")
    if execution.get("state") not in EXECUTION_STATES:
        raise GraceLoopError("execution.state is not registered")
    execution["parameter_lock_sha256"] = require_sha256(
        execution.get("parameter_lock_sha256"), "execution.parameter_lock_sha256"
    )
    execution["inputs"] = _validate_file_descriptors(execution.get("inputs"), "execution.inputs")
    execution["outputs"] = _validate_file_descriptors(execution.get("outputs"), "execution.outputs")
    if execution["state"] in {"COMPLETE", "PARTIAL"} and not execution["outputs"]:
        raise GraceLoopError("complete/partial receipts must bind at least one output")
    if execution["state"] == "NOT_RUN" and execution["outputs"]:
        raise GraceLoopError("not-run receipts cannot bind outputs")
    coverage = execution.get("coverage")
    if not isinstance(coverage, dict):
        raise GraceLoopError("execution.coverage must be an object")
    coverage_keys = {"mode", "requested", "examined", "skipped", "failed", "reason_codes"}
    require_only_keys(coverage, coverage_keys, "execution.coverage")
    if set(coverage) != coverage_keys:
        raise GraceLoopError("receipt coverage must declare every field")
    if coverage.get("mode") not in COVERAGE_MODES:
        raise GraceLoopError("coverage.mode is not registered")
    for field in ("requested", "examined", "skipped", "failed"):
        value = coverage.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise GraceLoopError(f"coverage.{field} must be a nonnegative integer")
    if coverage["requested"] != coverage["examined"] + coverage["skipped"] + coverage["failed"]:
        raise GraceLoopError("coverage arithmetic does not balance")
    coverage["reason_codes"] = sorted(
        require_string_list(coverage.get("reason_codes"), "coverage.reason_codes")
    )
    if coverage["mode"] == "NOT_APPLICABLE" and any(
        coverage[field] for field in ("requested", "examined", "skipped", "failed")
    ):
        raise GraceLoopError("NOT_APPLICABLE coverage must use zero counts")
    if (coverage["skipped"] or coverage["failed"]) and execution["state"] == "COMPLETE":
        raise GraceLoopError("incomplete coverage cannot declare COMPLETE execution")

    subject = core.get("subject_alias")
    if subject is not None:
        if not isinstance(subject, dict):
            raise GraceLoopError("subject_alias must be null or an object")
        require_only_keys(subject, {"namespace", "namespace_version", "alias", "kind"}, "subject")
        if set(subject) != {"namespace", "namespace_version", "alias", "kind"}:
            raise GraceLoopError("subject_alias must declare every field")
        subject["namespace"] = require_id(subject.get("namespace"), "subject.namespace")
        subject["namespace_version"] = require_string(
            subject.get("namespace_version"), "subject.namespace_version", max_length=100
        )
        subject["alias"] = require_alias(subject.get("alias"), "subject.alias")
        if subject.get("kind") not in SUBJECT_KINDS:
            raise GraceLoopError("subject.kind is not registered")

    reference_frame_id = core.get("reference_frame_id")
    if reference_frame_id is not None:
        require_string(reference_frame_id, "reference_frame_id", max_length=80)
        if not reference_frame_id.startswith("frame:") or len(reference_frame_id) != 70:
            raise GraceLoopError("reference_frame_id must be frame:<sha256>")
        require_sha256(reference_frame_id[6:], "reference_frame_id digest")
    core["evidence_family"] = require_id(core.get("evidence_family"), "evidence_family")

    lineage = core.get("lineage")
    if not isinstance(lineage, dict):
        raise GraceLoopError("lineage must be an object")
    require_only_keys(lineage, LINEAGE_FIELDS, "lineage")
    if set(lineage) != LINEAGE_FIELDS:
        raise GraceLoopError("lineage must declare every correlation field")
    for field in sorted(LINEAGE_FIELDS):
        lineage[field] = require_string(lineage.get(field), f"lineage.{field}", max_length=200)

    calibration = core.get("calibration")
    if not isinstance(calibration, dict):
        raise GraceLoopError("calibration must be an object")
    require_only_keys(
        calibration, {"state", "certificate_receipt_id", "domain_digest"}, "calibration"
    )
    if set(calibration) != {"state", "certificate_receipt_id", "domain_digest"}:
        raise GraceLoopError("calibration must declare every field")
    if calibration.get("state") not in CALIBRATION_STATES:
        raise GraceLoopError("calibration.state is not registered")
    certificate = calibration.get("certificate_receipt_id")
    domain_digest = calibration.get("domain_digest")
    if calibration["state"] == "CALIBRATED":
        require_id(certificate, "calibration.certificate_receipt_id")
        require_sha256(domain_digest, "calibration.domain_digest")
    elif certificate != "NONE" or domain_digest != "NONE":
        raise GraceLoopError("non-calibrated receipts must use NONE certificate and domain")

    capabilities = require_string_list(core.get("capabilities"), "capabilities", allow_empty=False)
    if any(value not in CAPABILITIES for value in capabilities):
        raise GraceLoopError("receipt contains an unregistered capability")
    allowed_capabilities = KIND_ALLOWED_CAPABILITIES[core["kind"]]
    if not set(capabilities) <= allowed_capabilities:
        raise GraceLoopError(
            f"receipt kind {core['kind']} cannot carry one or more declared capabilities"
        )
    required_capability = KIND_REQUIRED_CAPABILITY.get(core["kind"])
    if required_capability is not None and required_capability not in capabilities:
        raise GraceLoopError(
            f"receipt kind {core['kind']} requires capability {required_capability}"
        )
    core["capabilities"] = sorted(capabilities)
    prohibitions = require_string_list(core.get("prohibitions"), "prohibitions", allow_empty=False)
    if any(value not in PROHIBITIONS for value in prohibitions):
        raise GraceLoopError("receipt contains an unregistered prohibition")
    core["prohibitions"] = sorted(prohibitions)
    if not isinstance(core.get("payload"), dict):
        raise GraceLoopError("receipt.core.payload must be an object")
    if core["kind"] == "FRAME_TRANSFORM":
        payload = core["payload"]
        require_only_keys(
            payload,
            {
                "source_frame_id",
                "target_frame_id",
                "transform_sha256",
                "scope_sha256",
                "ambiguity",
            },
            "frame transform payload",
        )
        for field in ("source_frame_id", "target_frame_id"):
            value = require_string(payload.get(field), f"frame transform {field}", max_length=70)
            if not value.startswith("frame:") or len(value) != 70:
                raise GraceLoopError(f"frame transform {field} must be frame:<sha256>")
            require_sha256(value[6:], f"frame transform {field} digest")
        for field in ("transform_sha256", "scope_sha256"):
            payload[field] = require_sha256(payload.get(field), f"frame transform {field}")
        if payload.get("ambiguity") != "UNAMBIGUOUS":
            raise GraceLoopError("v1 frame transforms must be machine-declared UNAMBIGUOUS")
    if core["kind"] == "CALIBRATION":
        payload = core["payload"]
        require_only_keys(
            payload,
            {"domain_digest", "certificate_sha256", "scope_sha256"},
            "calibration payload",
        )
        for field in ("domain_digest", "certificate_sha256", "scope_sha256"):
            payload[field] = require_sha256(payload.get(field), f"calibration payload {field}")
        if calibration["state"] != "NOT_APPLICABLE":
            raise GraceLoopError("calibration certificates cannot certify themselves")
        output_digests = {descriptor["sha256"] for descriptor in execution["outputs"]}
        if not {payload["certificate_sha256"], payload["scope_sha256"]} <= output_digests:
            raise GraceLoopError("calibration certificate artifacts are not output-bound")

    if core["kind"] == "SOURCE_SNAPSHOT" and calibration["state"] == "CALIBRATED":
        raise GraceLoopError("source snapshots cannot self-declare calibrated")
    if core["kind"] == "MODEL_PREDICTION" and calibration["state"] not in {
        "SYNTHETIC_ONLY",
        "UNCALIBRATED",
    }:
        raise GraceLoopError("model predictions must remain synthetic-only or uncalibrated")
    if core["kind"] == "MODEL_PREDICTION":
        _reject_probabilistic_payload(core["payload"])
    if execution["state"] in {"FAILED", "NOT_RUN"}:
        if core["kind"] != "SOURCE_SNAPSHOT":
            raise GraceLoopError("failed/not-run receipts cannot carry a result-bearing kind")
        if capabilities != ["QUERY_EXECUTION_METADATA"]:
            raise GraceLoopError(
                "failed/not-run source snapshots retain query-execution metadata only"
            )

    attestations = receipt.get("attestations")
    if attestations != []:
        raise GraceLoopError("v1 accepts no attestations; receipts are unauthenticated")
    expected = sha256_bytes(canonical_bytes(core))
    if receipt.get("core_sha256") != expected:
        raise GraceLoopError("receipt core_sha256 mismatch")
    reject_floats(receipt, "receipt")
    reject_private_material(receipt, "receipt")
    return {
        "schema_version": RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "core": core,
        "core_sha256": expected,
        "attestations": [],
    }


def build_receipt(receipt_id: str, core: dict[str, Any]) -> dict[str, Any]:
    core = deepcopy(core)
    execution = core.get("execution")
    if isinstance(execution, dict):
        for field in ("inputs", "outputs"):
            descriptors = execution.get(field)
            if isinstance(descriptors, list):
                execution[field] = sorted(
                    descriptors,
                    key=lambda item: (
                        item.get("role", "") if isinstance(item, dict) else "",
                        item.get("sha256", "") if isinstance(item, dict) else "",
                        item.get("bytes", -1) if isinstance(item, dict) else -1,
                    ),
                )
        coverage = execution.get("coverage")
        if isinstance(coverage, dict) and isinstance(coverage.get("reason_codes"), list):
            coverage["reason_codes"] = sorted(coverage["reason_codes"])
    for field in ("capabilities", "prohibitions"):
        if isinstance(core.get(field), list):
            core[field] = sorted(core[field])
    candidate = {
        "schema_version": RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "core": core,
        "core_sha256": sha256_bytes(canonical_bytes(core)),
        "attestations": [],
    }
    return validate_receipt(candidate)


def receipt_authentication_status(receipt: dict[str, Any]) -> str:
    validated = validate_receipt(receipt)
    if validated["attestations"]:
        raise GraceLoopError("unreachable v1 attestation state")
    return "SELF_CONSISTENT_UNAUTHENTICATED"
