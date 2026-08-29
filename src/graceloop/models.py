"""Strict GraceLoop study, world-model, frame, gate, and outcome schemas."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .canonical import (
    GraceLoopError,
    canonical_bytes,
    contained_regular_file,
    read_json,
    reject_floats,
    reject_private_material,
    require_id,
    require_only_keys,
    require_relative,
    require_sha256,
    require_single_line,
    require_string,
    require_string_list,
    sha256_bytes,
    sha256_file,
)
from .receipt import validate_receipt

COMPILER_VERSION = "0.1.0a1"
PINNED_GRACEGRAPH_SOURCE_MANIFEST_SHA256 = (
    "3c838068b20f00c6fd13c0d59bfa83a642e577de76304eb951a2195fcd84cb50"
)
STUDY_SCHEMA = "graceloop.study.v1"
_BOUNDARY_ITEMS = (
    ("biological_gates_closed", 0),
    ("empirical_n", 0),
    ("experiment_authorized", False),
    ("experiments_performed", 0),
    ("material_work_started", False),
    ("release_authorized", False),
    ("results_present", False),
    ("target_selected", False),
)


def fixed_boundary() -> dict[str, int | bool]:
    """Return a fresh copy so a caller cannot mutate the validation authority."""

    return dict(_BOUNDARY_ITEMS)


# Compatibility export only. Internal validation always calls fixed_boundary().
BOUNDARY = fixed_boundary()
FRAME_KINDS = {"GENOMIC", "TRANSCRIPT", "PROTEIN", "PHENOTYPE", "ASSAY"}
CONTENT_BINDING_MODES = {"FULL_CONTENT_SHA256", "ASSEMBLY_MANIFEST_SHA256", "UNAVAILABLE"}
COORDINATE_CONVENTIONS = {
    "ZERO_BASED_HALF_OPEN",
    "ONE_BASED_CLOSED",
    "NOT_APPLICABLE",
}
GATE_STATES = {"OPEN", "NOT_APPLICABLE"}
AUTHORITY_SCOPES = {"SOFTWARE", "DATA", "BIOLOGICAL", "HUMAN", "OWNER", "LEGAL"}
EXECUTION_CLASSES = {
    "READ_ONLY_COMPUTATION",
    "NONINTERVENTIONAL_MEASUREMENT",
    "MATERIAL_PERTURBATION",
}
OUTCOME_CLASSES = {
    "INFORMATIVE_POSITIVE",
    "INFORMATIVE_NEGATIVE",
    "INFORMATIVE_ALTERNATIVE",
    "OTHER",
    "NO_CALL",
    "QC_FAILED",
    "CONTRADICTORY",
    "UNEXPECTED",
}
SCIENTIFIC_OUTCOME_CLASSES = {
    "INFORMATIVE_POSITIVE",
    "INFORMATIVE_NEGATIVE",
    "INFORMATIVE_ALTERNATIVE",
    "OTHER",
}
FAIL_CLOSED_OUTCOME_CLASSES = {"NO_CALL", "QC_FAILED", "CONTRADICTORY", "UNEXPECTED"}
PREDICTION_RELATIONS = {"PERMITS", "EXCLUDES", "UNKNOWN"}
FORBIDDEN_MODEL_KEYS = {
    "prior",
    "priors",
    "probability",
    "probabilities",
    "likelihood",
    "likelihoods",
    "posterior",
    "posteriors",
    "weight",
    "weights",
    "utility",
    "utilities",
    "score",
    "scores",
    "expected_value",
    "voi",
}


def _reject_forbidden_model_keys(value: Any, field: str = "study") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in FORBIDDEN_MODEL_KEYS:
                raise GraceLoopError(f"{field}.{key} is forbidden at empirical N=0")
            _reject_forbidden_model_keys(item, f"{field}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_forbidden_model_keys(item, f"{field}[{index}]")


def _unique_objects(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise GraceLoopError(f"{field} must be a list of objects")
    seen: set[str] = set()
    for index, item in enumerate(value):
        identity = require_id(item.get("id"), f"{field}[{index}].id")
        if identity in seen:
            raise GraceLoopError(f"duplicate {field} id: {identity}")
        seen.add(identity)
    return value


def frame_id_for(frame_without_id: dict[str, Any]) -> str:
    return "frame:" + sha256_bytes(canonical_bytes(frame_without_id))


def _validate_reference_frames(value: Any) -> list[dict[str, Any]]:
    frames = _unique_objects(value, "reference_frames")
    normalized = []
    for frame in frames:
        frame_keys = {
            "id",
            "kind",
            "content_binding",
            "coordinate_convention",
            "feature_set_sha256",
            "comparator_sha256",
            "assayed_space_sha256",
            "transform_receipt_id",
        }
        require_only_keys(
            frame,
            frame_keys,
            f"reference frame {frame['id']}",
        )
        if set(frame) != frame_keys:
            raise GraceLoopError(f"reference frame {frame['id']} must declare every field")
        if frame.get("kind") not in FRAME_KINDS:
            raise GraceLoopError(f"reference frame {frame['id']} has unknown kind")
        binding = frame.get("content_binding")
        if not isinstance(binding, dict):
            raise GraceLoopError(f"reference frame {frame['id']}.content_binding must be an object")
        require_only_keys(binding, {"mode", "sha256", "accession_version"}, "content_binding")
        if set(binding) != {"mode", "sha256", "accession_version"}:
            raise GraceLoopError("content_binding must declare mode, sha256, and accession_version")
        if binding.get("mode") not in CONTENT_BINDING_MODES:
            raise GraceLoopError(f"reference frame {frame['id']} has unknown binding mode")
        if binding["mode"] == "UNAVAILABLE":
            if binding.get("sha256") is not None:
                raise GraceLoopError("UNAVAILABLE content binding must use null sha256")
        else:
            binding["sha256"] = require_sha256(
                binding.get("sha256"), f"reference frame {frame['id']} content sha256"
            )
        accession = binding.get("accession_version")
        if accession is not None:
            binding["accession_version"] = require_single_line(
                accession, f"reference frame {frame['id']} accession", max_length=200
            )
        if frame.get("coordinate_convention") not in COORDINATE_CONVENTIONS:
            raise GraceLoopError(f"reference frame {frame['id']} has unknown coordinates")
        for field in ("feature_set_sha256", "comparator_sha256", "assayed_space_sha256"):
            item = frame.get(field)
            if item is not None:
                frame[field] = require_sha256(item, f"reference frame {frame['id']}.{field}")
        transform = frame.get("transform_receipt_id")
        if transform is not None:
            frame["transform_receipt_id"] = require_id(
                transform, f"reference frame {frame['id']}.transform_receipt_id"
            )
        core = {key: frame[key] for key in sorted(frame) if key != "id"}
        expected = frame_id_for(core)
        if frame["id"] != expected:
            raise GraceLoopError(f"reference frame id does not bind its content: {frame['id']}")
        normalized.append(frame)
    return sorted(normalized, key=lambda item: item["id"])


def _validate_decision(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GraceLoopError("decision must be an object")
    require_only_keys(value, {"id", "question", "defer_option_id", "options"}, "decision")
    value["id"] = require_id(value.get("id"), "decision.id")
    value["question"] = require_single_line(value.get("question"), "decision.question")
    options = _unique_objects(value.get("options"), "decision.options")
    if len(options) < 3:
        raise GraceLoopError("decision must declare at least two substantive options plus defer")
    for option in options:
        require_only_keys(option, {"id", "label"}, f"decision option {option['id']}")
        option["label"] = require_single_line(option.get("label"), f"option {option['id']}.label")
    option_ids = {item["id"] for item in options}
    defer = require_id(value.get("defer_option_id"), "decision.defer_option_id")
    if defer not in option_ids:
        raise GraceLoopError("decision.defer_option_id is not a declared option")
    value["options"] = sorted(options, key=lambda item: item["id"])
    return value


def _validate_worlds(
    value: Any, decision: dict[str, Any], receipt_ids: set[str]
) -> list[dict[str, Any]]:
    worlds = _unique_objects(value, "worlds")
    if not 2 <= len(worlds) <= 32:
        raise GraceLoopError("worlds must contain 2-32 explicitly enumerated models")
    options = {item["id"] for item in decision["options"]}
    residual_count = 0
    for world in worlds:
        require_only_keys(
            world,
            {"id", "label", "open_world_residual", "admissible_options", "source_receipt_ids"},
            f"world {world['id']}",
        )
        world["label"] = require_single_line(world.get("label"), f"world {world['id']}.label")
        if not isinstance(world.get("open_world_residual"), bool):
            raise GraceLoopError(f"world {world['id']}.open_world_residual must be boolean")
        residual_count += int(world["open_world_residual"])
        admissible = require_string_list(
            world.get("admissible_options"),
            f"world {world['id']}.admissible_options",
            allow_empty=False,
        )
        if not set(admissible) <= options:
            raise GraceLoopError(f"world {world['id']} references unknown decision options")
        if decision["defer_option_id"] not in admissible:
            raise GraceLoopError(f"world {world['id']} must retain the defer option")
        if len(set(admissible) - {decision["defer_option_id"]}) != 1:
            raise GraceLoopError(
                f"world {world['id']} must map to exactly one substantive decision option"
            )
        sources = require_string_list(
            world.get("source_receipt_ids"), f"world {world['id']}.source_receipt_ids"
        )
        if not set(sources) <= receipt_ids:
            raise GraceLoopError(f"world {world['id']} references unknown receipts")
        world["admissible_options"] = sorted(admissible)
        world["source_receipt_ids"] = sorted(sources)
    if residual_count != 1:
        raise GraceLoopError("exactly one declared world must be the open-world residual")
    substantive_options = options - {decision["defer_option_id"]}
    represented = {
        option
        for world in worlds
        for option in world["admissible_options"]
        if option != decision["defer_option_id"]
    }
    if represented != substantive_options:
        raise GraceLoopError("every substantive decision option must be represented by a world")
    residual = next(world for world in worlds if world["open_world_residual"])
    residual_option = next(
        option for option in residual["admissible_options"] if option != decision["defer_option_id"]
    )
    if any(
        residual_option in world["admissible_options"]
        for world in worlds
        if not world["open_world_residual"]
    ):
        raise GraceLoopError("the open-world residual must map to a distinct substantive option")
    return sorted(worlds, key=lambda item: item["id"])


def _validate_gates(value: Any) -> list[dict[str, Any]]:
    gates = _unique_objects(value, "gates")
    for gate in gates:
        require_only_keys(gate, {"id", "label", "state", "authority_scope"}, f"gate {gate['id']}")
        gate["label"] = require_single_line(gate.get("label"), f"gate {gate['id']}.label")
        if gate.get("state") not in GATE_STATES:
            raise GraceLoopError("v1 cannot claim that a biological/authority gate is closed")
        if gate.get("authority_scope") not in AUTHORITY_SCOPES:
            raise GraceLoopError(f"gate {gate['id']} has unknown authority scope")
    return sorted(gates, key=lambda item: item["id"])


def _validate_resource(value: Any, field: str) -> int | str:
    if value == "UNKNOWN":
        return value
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GraceLoopError(f"{field} must be a nonnegative integer or UNKNOWN")
    return value


def prediction_model_core(
    decision: dict[str, Any],
    worlds: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    experiment: dict[str, Any],
) -> dict[str, Any]:
    """Canonical semantic context bound by a declared-model receipt."""

    experiment_core = {
        key: experiment[key] for key in sorted(experiment) if key != "prediction_model_sha256"
    }
    return {
        "decision": decision,
        "worlds": worlds,
        "gates": gates,
        "experiment": experiment_core,
    }


def validate_protocol_lock(value: Any, experiment: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GraceLoopError("protocol lock must be an object")
    required = {
        "schema_version",
        "operation_id",
        "execution_class",
        "purpose_code",
        "input_denominator_sha256",
        "comparator_sha256",
        "outcome_classifier_sha256",
        "qc_rules_sha256",
        "reference_frame_ids",
        "requires_gates",
        "resource_basis_sha256",
        "component_declarations",
    }
    require_only_keys(value, required, "protocol lock")
    if set(value) != required:
        raise GraceLoopError("protocol lock must declare every required field")
    if value.get("schema_version") != "graceloop.protocol-lock.v1":
        raise GraceLoopError("unregistered protocol-lock schema")
    value["operation_id"] = require_id(value.get("operation_id"), "protocol operation_id")
    value["purpose_code"] = require_id(value.get("purpose_code"), "protocol purpose_code")
    if value["operation_id"] != experiment["id"]:
        raise GraceLoopError("protocol lock operation id does not match the experiment")
    if value["purpose_code"] != experiment["rationale_code"]:
        raise GraceLoopError("protocol lock purpose does not match the experiment rationale")
    if value.get("execution_class") != experiment["execution_class"]:
        raise GraceLoopError("protocol lock execution class does not match the experiment")
    for field in (
        "input_denominator_sha256",
        "comparator_sha256",
        "outcome_classifier_sha256",
        "qc_rules_sha256",
        "resource_basis_sha256",
    ):
        value[field] = require_sha256(value.get(field), f"protocol lock {field}")
    components = value.get("component_declarations")
    component_fields = {
        "input_denominator": "input_denominator_sha256",
        "comparator": "comparator_sha256",
        "outcome_classifier": "outcome_classifier_sha256",
        "qc_rules": "qc_rules_sha256",
        "resource_basis": "resource_basis_sha256",
    }
    if not isinstance(components, dict) or set(components) != set(component_fields):
        raise GraceLoopError(
            "protocol component declarations must exactly cover every hashed component"
        )
    for component_name, digest_field in component_fields.items():
        declaration = components[component_name]
        if not isinstance(declaration, dict) or not declaration:
            raise GraceLoopError(
                f"protocol component {component_name} must be a nonempty inspectable object"
            )
        reject_floats(declaration, f"protocol component {component_name}")
        reject_private_material(declaration, f"protocol component {component_name}")
        _reject_forbidden_model_keys(declaration, f"protocol component {component_name}")
        if sha256_bytes(canonical_bytes(declaration)) != value[digest_field]:
            raise GraceLoopError(f"protocol component {component_name} does not match its digest")
        if declaration.get("operation_id") != experiment["id"]:
            raise GraceLoopError(
                f"protocol component {component_name} does not bind the experiment id"
            )
    references = sorted(
        require_string_list(value.get("reference_frame_ids"), "protocol reference_frame_ids")
    )
    requirements = sorted(
        require_string_list(value.get("requires_gates"), "protocol requires_gates")
    )
    if references != experiment["reference_frame_ids"]:
        raise GraceLoopError("protocol lock reference frames do not match the experiment")
    if requirements != experiment["requires_gates"]:
        raise GraceLoopError("protocol lock gates do not match the experiment")
    value["reference_frame_ids"] = references
    value["requires_gates"] = requirements
    denominator_frames = components["input_denominator"].get("reference_frame_ids")
    if denominator_frames != experiment["reference_frame_ids"]:
        raise GraceLoopError("protocol input denominator frames do not match the experiment")
    if canonical_bytes(components["resource_basis"].get("declared_resources")) != canonical_bytes(
        experiment["resources"]
    ):
        raise GraceLoopError("protocol lock resource basis does not match the experiment")
    return value


def _validate_declared_model_binding_receipt(
    receipt: dict[str, Any],
    decision: dict[str, Any],
    worlds: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    experiment_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """Validate the complete inspectable contract of the local declared-model adapter."""

    core = receipt["core"]
    execution = core["execution"]
    payload = core["payload"]
    payload_keys = {
        "captured_at_utc",
        "source_schema",
        "source_declaration_sha256",
        "source_declaration_bytes",
        "status",
        "decision",
        "worlds",
        "gates",
        "declared_experiments",
        "compiled_experiments",
        "experiment_bindings",
    }
    require_only_keys(payload, payload_keys, "declared-model payload")
    if set(payload) != payload_keys:
        raise GraceLoopError("declared-model payload must declare every field")
    require_single_line(
        payload.get("captured_at_utc"), "declared-model captured_at_utc", max_length=40
    )
    if payload.get("source_schema") != "graceloop.declared-model.v1":
        raise GraceLoopError("declared-model source schema is not registered")
    declaration_sha = require_sha256(
        payload.get("source_declaration_sha256"),
        "declared-model source_declaration_sha256",
    )
    declaration_bytes = payload.get("source_declaration_bytes")
    if (
        isinstance(declaration_bytes, bool)
        or not isinstance(declaration_bytes, int)
        or not 0 < declaration_bytes <= 8 * 1024 * 1024
    ):
        raise GraceLoopError("declared-model source byte count is invalid")
    if payload.get("status") != "DECLARED_SYNTHETIC_UNCALIBRATED_UNAUTHENTICATED":
        raise GraceLoopError("declared-model status is not conservative")
    if canonical_bytes(payload.get("decision")) != canonical_bytes(decision):
        raise GraceLoopError("declared-model receipt decision contradicts the study")
    if canonical_bytes(payload.get("worlds")) != canonical_bytes(worlds):
        raise GraceLoopError("declared-model receipt worlds contradict the study")
    if canonical_bytes(payload.get("gates")) != canonical_bytes(gates):
        raise GraceLoopError("declared-model receipt gates contradict the study")
    if (
        core["calibration"]
        != {
            "state": "SYNTHETIC_ONLY",
            "certificate_receipt_id": "NONE",
            "domain_digest": "NONE",
        }
        or core["reference_frame_id"] is not None
        or core["capabilities"] != ["DESIGN_STRUCTURE", "MODEL_PREDICTION"]
    ):
        raise GraceLoopError("declared-model receipt authority boundary is not exact")
    expected_prohibitions = {
        "NO_BIOLOGICAL_CAUSALITY",
        "NO_EMPIRICAL_PERFORMANCE",
        "NO_EXPERIMENT_AUTHORITY",
        "NO_INDEPENDENCE_CLAIM",
        "NO_TARGET_SELECTION",
    }
    if set(core["prohibitions"]) != expected_prohibitions:
        raise GraceLoopError("declared-model receipt prohibitions are not exact")
    producer = core["producer"]
    if (
        producer["tool"] != "GraceLoop declared-model adapter"
        or producer["version"] != COMPILER_VERSION
        or producer["adapter_id"] != "LOCAL.GRACELOOP_DECLARED_MODEL.V1"
        or producer["adapter_version"] != COMPILER_VERSION
        or producer["source_sha256"] != producer["adapter_sha256"]
    ):
        raise GraceLoopError("declared-model producer contract is not exact")
    expected_coverage = {
        "mode": "NOT_APPLICABLE",
        "requested": 0,
        "examined": 0,
        "skipped": 0,
        "failed": 0,
        "reason_codes": [],
    }
    expected_inputs = [
        {
            "role": "model-declaration",
            "sha256": declaration_sha,
            "bytes": declaration_bytes,
        }
    ]
    if (
        execution["state"] != "COMPLETE"
        or execution["parameter_lock_sha256"] != declaration_sha
        or execution["inputs"] != expected_inputs
        or execution["coverage"] != expected_coverage
    ):
        raise GraceLoopError("declared-model execution contract is not exact")

    def keyed(items: Any, field: str) -> dict[str, dict[str, Any]]:
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise GraceLoopError(f"declared-model {field} must be a list of objects")
        result: dict[str, dict[str, Any]] = {}
        for item in items:
            identity = require_id(
                item.get("id") if field != "experiment_bindings" else item.get("experiment_id"),
                field,
            )
            if identity in result:
                raise GraceLoopError(f"declared-model {field} contains duplicate ids")
            result[identity] = item
        if set(result) != experiment_ids:
            raise GraceLoopError(f"declared-model {field} inventory does not match the study")
        return result

    compiled = keyed(payload.get("compiled_experiments"), "compiled_experiments")
    declared = keyed(payload.get("declared_experiments"), "declared_experiments")
    bindings = keyed(payload.get("experiment_bindings"), "experiment_bindings")
    expected_outputs: list[dict[str, Any]] = []
    for identity in sorted(experiment_ids):
        compiled_item = compiled[identity]
        declared_item = declared[identity]
        binding = bindings[identity]
        compiled_keys = {
            "id",
            "label",
            "execution_class",
            "protocol_sha256",
            "prediction_model_sha256",
            "reference_frame_ids",
            "requires_gates",
            "outcomes",
            "predictions",
            "resources",
            "rationale_code",
        }
        require_only_keys(
            compiled_item, compiled_keys, f"declared-model compiled experiment {identity}"
        )
        if set(compiled_item) != compiled_keys:
            raise GraceLoopError("declared-model compiled experiment schema is not exact")
        require_only_keys(
            declared_item,
            compiled_keys | {"protocol_lock"},
            f"declared-model source experiment {identity}",
        )
        if set(declared_item) != compiled_keys | {"protocol_lock"}:
            raise GraceLoopError("declared-model source experiment schema is not exact")
        require_only_keys(
            binding,
            {
                "experiment_id",
                "protocol_sha256",
                "prediction_model_sha256",
                "reference_frame_ids",
            },
            f"declared-model binding {identity}",
        )
        if set(binding) != {
            "experiment_id",
            "protocol_sha256",
            "prediction_model_sha256",
            "reference_frame_ids",
        }:
            raise GraceLoopError("declared-model experiment binding is not exact")
        if not isinstance(declared_item.get("protocol_lock"), dict):
            raise GraceLoopError("declared-model protocol lock is missing")
        declared_experiment = {
            key: value for key, value in declared_item.items() if key != "protocol_lock"
        }
        if canonical_bytes(declared_experiment) != canonical_bytes(compiled_item):
            raise GraceLoopError("declared and compiled experiment payloads differ")
        protocol_lock = validate_protocol_lock(
            deepcopy(declared_item["protocol_lock"]), compiled_item
        )
        protocol_bytes = canonical_bytes(protocol_lock)
        protocol_sha = sha256_bytes(protocol_bytes)
        model_bytes = canonical_bytes(prediction_model_core(decision, worlds, gates, compiled_item))
        model_sha = sha256_bytes(model_bytes)
        expected_binding = {
            "experiment_id": identity,
            "protocol_sha256": protocol_sha,
            "prediction_model_sha256": model_sha,
            "reference_frame_ids": compiled_item.get("reference_frame_ids"),
        }
        if binding != expected_binding:
            raise GraceLoopError("declared-model experiment binding digest is inconsistent")
        if (
            compiled_item.get("protocol_sha256") != protocol_sha
            or compiled_item.get("prediction_model_sha256") != model_sha
        ):
            raise GraceLoopError("declared-model compiled experiment digest is inconsistent")
        expected_outputs.extend(
            [
                {"role": "protocol-lock", "sha256": protocol_sha, "bytes": len(protocol_bytes)},
                {"role": "prediction-model", "sha256": model_sha, "bytes": len(model_bytes)},
            ]
        )
    payload_bytes = canonical_bytes(payload)
    expected_outputs.append(
        {
            "role": "compiled-declaration",
            "sha256": sha256_bytes(payload_bytes),
            "bytes": len(payload_bytes),
        }
    )
    expected_outputs.sort(key=lambda item: (item["role"], item["sha256"], item["bytes"]))
    if execution["outputs"] != expected_outputs:
        raise GraceLoopError("declared-model output descriptors are not exact")
    return compiled


def _validate_experiments(
    value: Any,
    decision: dict[str, Any],
    worlds: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    receipts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    experiments = _unique_objects(value, "experiments")
    experiment_ids = {item["id"] for item in experiments}
    declared_receipt_cache: dict[str, dict[str, dict[str, Any]]] = {}
    world_ids = {item["id"] for item in worlds}
    gate_ids = {item["id"] for item in gates}
    frame_ids = {item["id"] for item in frames}
    receipt_ids = set(receipts)
    required_outcome_classes = {
        "INFORMATIVE_POSITIVE",
        "INFORMATIVE_NEGATIVE",
        "OTHER",
        *FAIL_CLOSED_OUTCOME_CLASSES,
    }
    for experiment in experiments:
        require_only_keys(
            experiment,
            {
                "id",
                "label",
                "execution_class",
                "protocol_sha256",
                "prediction_model_sha256",
                "reference_frame_ids",
                "requires_gates",
                "outcomes",
                "predictions",
                "resources",
                "rationale_code",
            },
            f"experiment {experiment['id']}",
        )
        experiment["label"] = require_single_line(
            experiment.get("label"), f"experiment {experiment['id']}.label"
        )
        if experiment.get("execution_class") not in EXECUTION_CLASSES:
            raise GraceLoopError(f"experiment {experiment['id']} has unknown execution class")
        experiment["protocol_sha256"] = require_sha256(
            experiment.get("protocol_sha256"), f"experiment {experiment['id']}.protocol_sha256"
        )
        experiment["prediction_model_sha256"] = require_sha256(
            experiment.get("prediction_model_sha256"),
            f"experiment {experiment['id']}.prediction_model_sha256",
        )
        references = require_string_list(
            experiment.get("reference_frame_ids"),
            f"experiment {experiment['id']}.reference_frame_ids",
        )
        if not set(references) <= frame_ids:
            raise GraceLoopError(f"experiment {experiment['id']} references unknown frames")
        requirements = require_string_list(
            experiment.get("requires_gates"), f"experiment {experiment['id']}.requires_gates"
        )
        if not set(requirements) <= gate_ids:
            raise GraceLoopError(f"experiment {experiment['id']} references unknown gates")
        experiment["reference_frame_ids"] = sorted(references)
        experiment["requires_gates"] = sorted(requirements)
        experiment["rationale_code"] = require_id(
            experiment.get("rationale_code"), f"experiment {experiment['id']}.rationale_code"
        )

        outcomes = _unique_objects(
            experiment.get("outcomes"), f"experiment {experiment['id']}.outcomes"
        )
        classes = [item.get("class") for item in outcomes]
        if any(item not in OUTCOME_CLASSES for item in classes):
            raise GraceLoopError(f"experiment {experiment['id']} has unknown outcome class")
        if not required_outcome_classes <= set(classes):
            missing = sorted(required_outcome_classes - set(classes))
            raise GraceLoopError(
                f"experiment {experiment['id']} omits fail-closed branches: {missing}"
            )
        for required_class in required_outcome_classes:
            if classes.count(required_class) != 1:
                raise GraceLoopError(
                    f"experiment {experiment['id']} must declare one {required_class} branch"
                )
        if classes.count("INFORMATIVE_ALTERNATIVE") > 1:
            raise GraceLoopError(
                f"experiment {experiment['id']} may declare at most one INFORMATIVE_ALTERNATIVE"
            )
        for outcome in outcomes:
            require_only_keys(outcome, {"id", "label", "class"}, f"outcome {outcome['id']}")
            outcome["label"] = require_single_line(
                outcome.get("label"), f"outcome {outcome['id']}.label"
            )
        outcome_ids = {item["id"] for item in outcomes}

        predictions = experiment.get("predictions")
        if not isinstance(predictions, list) or any(
            not isinstance(item, dict) for item in predictions
        ):
            raise GraceLoopError(f"experiment {experiment['id']}.predictions must be objects")
        matrix: dict[tuple[str, str], dict[str, Any]] = {}
        for index, prediction in enumerate(predictions):
            field = f"experiment {experiment['id']}.predictions[{index}]"
            require_only_keys(
                prediction,
                {"world_id", "outcome_id", "relation", "source_receipt_ids"},
                field,
            )
            world_id = require_id(prediction.get("world_id"), f"{field}.world_id")
            outcome_id = require_id(prediction.get("outcome_id"), f"{field}.outcome_id")
            if world_id not in world_ids or outcome_id not in outcome_ids:
                raise GraceLoopError(f"{field} references an unknown world or outcome")
            if prediction.get("relation") not in PREDICTION_RELATIONS:
                raise GraceLoopError(f"{field}.relation is not registered")
            sources = require_string_list(
                prediction.get("source_receipt_ids"), f"{field}.source_receipt_ids"
            )
            if not set(sources) <= receipt_ids:
                raise GraceLoopError(f"{field} references unknown receipts")
            outcome_class = next(item["class"] for item in outcomes if item["id"] == outcome_id)
            if outcome_class in SCIENTIFIC_OUTCOME_CLASSES and prediction["relation"] in {
                "PERMITS",
                "EXCLUDES",
            }:
                if not sources:
                    raise GraceLoopError(f"{field} must cite a declared model/design receipt")
                if any(
                    receipts[source]["core"]["execution"]["state"] != "COMPLETE"
                    for source in sources
                ):
                    raise GraceLoopError(f"{field} cannot rely on failed or not-run receipts")
                if not any(
                    "MODEL_PREDICTION" in receipts[source]["core"]["capabilities"]
                    for source in sources
                ):
                    raise GraceLoopError(f"{field} lacks a model/design-capable receipt")
                for source in sources:
                    source_frame = receipts[source]["core"]["reference_frame_id"]
                    if source_frame is not None and source_frame not in references:
                        raise GraceLoopError(
                            f"{field} cites a receipt from an incompatible reference frame"
                        )
            prediction["source_receipt_ids"] = sorted(sources)
            key = (world_id, outcome_id)
            if key in matrix:
                raise GraceLoopError(
                    f"experiment {experiment['id']} has duplicate matrix cell {key}"
                )
            matrix[key] = prediction
        expected_matrix = {(world, outcome) for world in world_ids for outcome in outcome_ids}
        if set(matrix) != expected_matrix:
            missing = sorted(expected_matrix - set(matrix))
            extra = sorted(set(matrix) - expected_matrix)
            raise GraceLoopError(
                f"experiment {experiment['id']} prediction matrix is not total: "
                f"missing={missing[:5]}; extra={extra[:5]}"
            )
        outcome_by_id = {item["id"]: item for item in outcomes}
        for (world_id, outcome_id), prediction in matrix.items():
            if outcome_by_id[outcome_id]["class"] in FAIL_CLOSED_OUTCOME_CLASSES:
                if prediction["relation"] != "UNKNOWN":
                    raise GraceLoopError(
                        f"{experiment['id']} failure branch {outcome_id} must preserve {world_id}"
                    )
                if prediction["source_receipt_ids"]:
                    raise GraceLoopError("fail-closed branches cannot cite affirmative evidence")
        for world_id in world_ids:
            permitted = [
                prediction
                for (candidate, outcome_id), prediction in matrix.items()
                if candidate == world_id
                and outcome_by_id[outcome_id]["class"] in SCIENTIFIC_OUTCOME_CLASSES
                and prediction["relation"] == "PERMITS"
            ]
            if not permitted:
                raise GraceLoopError(
                    f"experiment {experiment['id']} predicts no scientific outcome for {world_id}"
                )
        residual_world_id = next(world["id"] for world in worlds if world["open_world_residual"])
        other_outcome_id = next(
            outcome["id"] for outcome in outcomes if outcome["class"] == "OTHER"
        )
        if matrix[(residual_world_id, other_outcome_id)]["relation"] != "PERMITS":
            raise GraceLoopError(
                f"experiment {experiment['id']} must preserve the open residual on OTHER"
            )
        experiment["outcomes"] = sorted(outcomes, key=lambda item: item["id"])
        experiment["predictions"] = sorted(
            predictions, key=lambda item: (item["outcome_id"], item["world_id"])
        )
        resources = experiment.get("resources")
        if not isinstance(resources, dict):
            raise GraceLoopError(f"experiment {experiment['id']}.resources must be an object")
        resource_keys = {
            "duration_days",
            "sample_units",
            "relative_cost",
            "material_risk",
            "irreversibility",
        }
        require_only_keys(
            resources,
            resource_keys,
            f"experiment {experiment['id']}.resources",
        )
        if set(resources) != resource_keys:
            raise GraceLoopError(
                f"experiment {experiment['id']}.resources must declare every dimension"
            )
        for field in sorted(resources):
            resources[field] = _validate_resource(
                resources[field], f"experiment {experiment['id']}.resources.{field}"
            )
        if experiment["execution_class"] == "READ_ONLY_COMPUTATION" and any(
            resources[field] != 0 for field in ("sample_units", "material_risk", "irreversibility")
        ):
            raise GraceLoopError(
                f"read-only experiment {experiment['id']} must use zero samples/material risk/irreversibility"
            )
        if (
            experiment["execution_class"]
            in {
                "NONINTERVENTIONAL_MEASUREMENT",
                "MATERIAL_PERTURBATION",
            }
            and resources["sample_units"] == 0
        ):
            raise GraceLoopError(
                f"non-computational experiment {experiment['id']} cannot declare zero samples"
            )
        if (
            experiment["execution_class"] == "MATERIAL_PERTURBATION"
            and resources["material_risk"] == 0
        ):
            raise GraceLoopError(
                f"material perturbation {experiment['id']} cannot declare zero material risk"
            )
        expected_model_sha256 = sha256_bytes(
            canonical_bytes(prediction_model_core(decision, worlds, gates, experiment))
        )
        if experiment["prediction_model_sha256"] != expected_model_sha256:
            raise GraceLoopError(
                f"experiment {experiment['id']} prediction model digest does not bind its semantics"
            )
        decisive_predictions = [
            prediction
            for prediction in experiment["predictions"]
            if prediction["relation"] in {"PERMITS", "EXCLUDES"}
        ]
        decisive_sources = {
            source
            for prediction in decisive_predictions
            for source in prediction["source_receipt_ids"]
        }
        binding_sources: set[str] = set()
        for source in decisive_sources:
            receipt = receipts[source]
            core = receipt["core"]
            if (
                core["kind"] != "MODEL_PREDICTION"
                or "MODEL_PREDICTION" not in core["capabilities"]
                or core["execution"]["state"] != "COMPLETE"
                or core["producer"]["adapter_id"] != "LOCAL.GRACELOOP_DECLARED_MODEL.V1"
            ):
                continue
            if source not in declared_receipt_cache:
                declared_receipt_cache[source] = _validate_declared_model_binding_receipt(
                    receipt, decision, worlds, gates, experiment_ids
                )
            bindings = core["payload"].get("experiment_bindings")
            if not isinstance(bindings, list):
                continue
            matching_bindings = [
                binding
                for binding in bindings
                if isinstance(binding, dict) and binding.get("experiment_id") == experiment["id"]
            ]
            compiled_items = core["payload"].get("compiled_experiments")
            declared_items = core["payload"].get("declared_experiments")
            if not isinstance(compiled_items, list) or not isinstance(declared_items, list):
                continue
            matching_compiled = [
                item
                for item in compiled_items
                if isinstance(item, dict) and item.get("id") == experiment["id"]
            ]
            matching_declared = [
                item
                for item in declared_items
                if isinstance(item, dict) and item.get("id") == experiment["id"]
            ]
            if (
                len(matching_bindings) != 1
                or len(matching_compiled) != 1
                or len(matching_declared) != 1
                or canonical_bytes(matching_compiled[0]) != canonical_bytes(experiment)
            ):
                continue
            declared_protocol_lock = matching_declared[0].get("protocol_lock")
            declared_experiment = {
                key: value for key, value in matching_declared[0].items() if key != "protocol_lock"
            }
            if (
                not isinstance(declared_protocol_lock, dict)
                or sha256_bytes(
                    canonical_bytes(validate_protocol_lock(declared_protocol_lock, experiment))
                )
                != experiment["protocol_sha256"]
                or canonical_bytes(declared_experiment) != canonical_bytes(experiment)
            ):
                continue
            output_digests = {descriptor["sha256"] for descriptor in core["execution"]["outputs"]}
            binding = matching_bindings[0]
            if (
                binding.get("protocol_sha256") == experiment["protocol_sha256"]
                and binding.get("prediction_model_sha256") == experiment["prediction_model_sha256"]
                and binding.get("reference_frame_ids") == experiment["reference_frame_ids"]
                and experiment["protocol_sha256"] in output_digests
                and experiment["prediction_model_sha256"] in output_digests
            ):
                binding_sources.add(source)
        if not binding_sources:
            raise GraceLoopError(
                f"experiment {experiment['id']} lacks a receipt-bound protocol and model matrix"
            )
        common_binding_sources = set(binding_sources)
        for prediction in decisive_predictions:
            common_binding_sources &= set(prediction["source_receipt_ids"])
        if not common_binding_sources:
            raise GraceLoopError(
                f"experiment {experiment['id']} lacks one common receipt across all decisive cells"
            )
    return sorted(experiments, key=lambda item: item["id"])


def validate_study(spec: Any, receipts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise GraceLoopError("study must be a JSON object")
    if not isinstance(receipts, dict):
        raise GraceLoopError("receipts must be an id-keyed object")
    normalized_receipts: dict[str, dict[str, Any]] = {}
    for key, candidate in receipts.items():
        if not isinstance(key, str):
            raise GraceLoopError("receipt map keys must be strings")
        receipt = validate_receipt(candidate)
        if key != receipt["receipt_id"]:
            raise GraceLoopError("receipt map key does not match receipt_id")
        normalized_receipts[key] = receipt
    receipts = normalized_receipts
    spec = deepcopy(spec)
    require_only_keys(
        spec,
        {
            "schema_version",
            "study_id",
            "title",
            "semantics",
            "boundary",
            "base_capsule",
            "receipt_files",
            "context_receipt_ids",
            "reference_frames",
            "decision",
            "worlds",
            "gates",
            "experiments",
            "nonclaims",
        },
        "study",
    )
    if spec.get("schema_version") != STUDY_SCHEMA:
        raise GraceLoopError(f"study.schema_version must be {STUDY_SCHEMA}")
    spec["study_id"] = require_id(spec.get("study_id"), "study.study_id")
    spec["title"] = require_single_line(spec.get("title"), "study.title")
    if spec.get("semantics") != "EXCLUSIVE_DECLARED_WORLDS_OPEN_WORLD":
        raise GraceLoopError(
            "study must explicitly enumerate exclusive worlds plus an open residual"
        )
    if not isinstance(spec.get("boundary"), dict) or canonical_bytes(
        spec["boundary"]
    ) != canonical_bytes(fixed_boundary()):
        raise GraceLoopError("study boundary must preserve the exact empirical-N=0 alpha state")
    for receipt_id, receipt in receipts.items():
        core = receipt["core"]
        if core["kind"] == "OBSERVATION" or "OBSERVED_OUTCOME" in core["capabilities"]:
            raise GraceLoopError(
                f"receipt {receipt_id} is empirical but the v1 study boundary is N=0"
            )
        calibration = core["calibration"]
        if calibration["state"] == "CALIBRATED":
            certificate_id = calibration["certificate_receipt_id"]
            if certificate_id == receipt_id:
                raise GraceLoopError(f"receipt {receipt_id} cannot self-certify")
            certificate = receipts.get(certificate_id)
            if certificate is None:
                raise GraceLoopError(
                    f"receipt {receipt_id} references a missing calibration certificate"
                )
            certificate_core = certificate["core"]
            if (
                certificate_core["kind"] != "CALIBRATION"
                or "CALIBRATION_CERTIFICATE" not in certificate_core["capabilities"]
                or certificate_core["execution"]["state"] != "COMPLETE"
                or certificate_core["calibration"]["state"] != "NOT_APPLICABLE"
                or certificate_core["payload"].get("domain_digest") != calibration["domain_digest"]
            ):
                raise GraceLoopError(
                    f"receipt {receipt_id} has an unusable calibration certificate"
                )
    base = spec.get("base_capsule")
    if base is not None:
        if not isinstance(base, dict):
            raise GraceLoopError("base_capsule must be null or an object")
        require_only_keys(base, {"run_id", "manifest_sha256", "receipt_id"}, "base_capsule")
        base["run_id"] = require_string(base.get("run_id"), "base_capsule.run_id", max_length=64)
        if len(base["run_id"]) != 16 or any(
            character not in "0123456789abcdef" for character in base["run_id"]
        ):
            raise GraceLoopError("base_capsule.run_id must be a 16-character hex digest")
        base["manifest_sha256"] = require_sha256(
            base.get("manifest_sha256"), "base_capsule.manifest_sha256"
        )
        base["receipt_id"] = require_id(base.get("receipt_id"), "base_capsule.receipt_id")
        base_receipt = receipts.get(base["receipt_id"])
        if base_receipt is None:
            raise GraceLoopError("base_capsule references an unknown receipt")
        base_core = base_receipt["core"]
        base_payload = base_core["payload"]
        base_payload_keys = {
            "captured_at_utc",
            "capsule_run_id",
            "capsule_manifest_sha256",
            "evaluation_sha256",
            "verification_status",
            "static_verification_status",
            "static_verification_sha256",
            "static_verification_bytes",
            "live_replay_status",
            "claim_boundary",
            "source_capsule_embedded",
        }
        require_only_keys(base_payload, base_payload_keys, "base capsule receipt payload")
        if set(base_payload) != base_payload_keys:
            raise GraceLoopError("base capsule receipt payload must declare every field")
        require_single_line(
            base_payload.get("captured_at_utc"),
            "base capsule captured_at_utc",
            max_length=40,
        )
        require_sha256(base_payload.get("evaluation_sha256"), "base capsule evaluation_sha256")
        static_verification_sha = require_sha256(
            base_payload.get("static_verification_sha256"),
            "base capsule static_verification_sha256",
        )
        static_verification_bytes = base_payload.get("static_verification_bytes")
        if (
            isinstance(static_verification_bytes, bool)
            or not isinstance(static_verification_bytes, int)
            or static_verification_bytes <= 0
        ):
            raise GraceLoopError("base capsule static verification byte count is invalid")
        if base_payload.get("static_verification_status") != "PASS_SEALED_BYTES_ONLY":
            raise GraceLoopError("base capsule static verification status is invalid")
        if base_payload.get("live_replay_status") not in {
            "NOT_REQUESTED",
            "PASS_DIAGNOSTIC_NOT_PROVENANCE_BOUND",
            "FAILED_CLOSED_DRIFT_OR_UNAVAILABLE",
            "FAILED_CLOSED_UNEXPECTED_DISPOSITION",
        }:
            raise GraceLoopError("base capsule live replay diagnostic is invalid")
        if base_payload.get("source_capsule_embedded") is not False:
            raise GraceLoopError("base capsule source embedding status is invalid")
        expected_base_boundary = {
            "biological_gate_closed": False,
            "empirical_n": 0,
            "experiment_authorized": False,
            "release_authorized": False,
            "target_selected": False,
        }
        if canonical_bytes(base_payload.get("claim_boundary")) != canonical_bytes(
            expected_base_boundary
        ):
            raise GraceLoopError("base capsule claim boundary is invalid")
        expected_base_prohibitions = {
            "NO_BIOLOGICAL_CAUSALITY",
            "NO_EMPIRICAL_PERFORMANCE",
            "NO_EXPERIMENT_AUTHORITY",
            "NO_INDEPENDENCE_CLAIM",
            "NO_TARGET_SELECTION",
        }
        expected_base_calibration = {
            "state": "NOT_APPLICABLE",
            "certificate_receipt_id": "NONE",
            "domain_digest": "NONE",
        }
        current_capture_sha = sha256_file(
            Path(__file__).resolve(strict=True).with_name("capture.py")
        )
        producer = base_core["producer"]
        execution = base_core["execution"]
        input_descriptors = execution["inputs"]
        output_descriptors = execution["outputs"]
        if len(input_descriptors) != 1 or input_descriptors[0]["role"] != "source-manifest":
            raise GraceLoopError("base capsule source-manifest input is not exact")
        source_input = input_descriptors[0]
        outputs_by_role = {item["role"]: item for item in output_descriptors}
        if len(outputs_by_role) != len(output_descriptors) or set(outputs_by_role) != {
            "capsule-manifest",
            "evaluation",
            "static-verification",
        }:
            raise GraceLoopError("base capsule output descriptor inventory is not exact")
        expected_parameter_lock = sha256_bytes(
            canonical_bytes(
                {
                    "capsule_manifest_sha256": base_payload["capsule_manifest_sha256"],
                    "source_manifest_sha256": PINNED_GRACEGRAPH_SOURCE_MANIFEST_SHA256,
                    "static_verification_required": True,
                }
            )
        )
        expected_coverage = {
            "mode": "NOT_APPLICABLE",
            "requested": 0,
            "examined": 0,
            "skipped": 0,
            "failed": 0,
            "reason_codes": [],
        }
        expected_lineage = {
            "biological_unit_cluster": "UNKNOWN",
            "event_origin_cluster": "UNKNOWN",
            "material_cluster": "UNKNOWN",
            "library_cluster": "UNKNOWN",
            "instrument_run_cluster": "UNKNOWN",
            "raw_observation_root": base_payload["capsule_manifest_sha256"],
            "analysis_pipeline_family": "GraceGraph-static-replay",
            "adjudication_family": "UNKNOWN",
        }
        expected_subject = {
            "namespace": "GraceGraph",
            "namespace_version": "0.1.0a1",
            "alias": base["run_id"],
            "kind": "OTHER",
        }
        if (
            producer["tool"] != "GraceGraph"
            or producer["version"] != "0.1.0a1"
            or producer["source_sha256"] != PINNED_GRACEGRAPH_SOURCE_MANIFEST_SHA256
            or producer["adapter_id"] != "LOCAL.GRACEGRAPH_CAPSULE.V1"
            or producer["adapter_version"] != COMPILER_VERSION
            or producer["adapter_sha256"] != current_capture_sha
            or source_input["sha256"] != PINNED_GRACEGRAPH_SOURCE_MANIFEST_SHA256
            or source_input["bytes"] <= 0
            or execution["parameter_lock_sha256"] != expected_parameter_lock
            or execution["coverage"] != expected_coverage
            or outputs_by_role["capsule-manifest"]["sha256"]
            != base_payload["capsule_manifest_sha256"]
            or outputs_by_role["evaluation"]["sha256"] != base_payload["evaluation_sha256"]
            or outputs_by_role["static-verification"]["sha256"] != static_verification_sha
            or outputs_by_role["static-verification"]["bytes"] != static_verification_bytes
            or base_core["calibration"] != expected_base_calibration
            or base_core["capabilities"] != ["DESIGN_STRUCTURE"]
            or set(base_core["prohibitions"]) != expected_base_prohibitions
            or base_core["reference_frame_id"] is not None
            or base_core["subject_alias"] != expected_subject
            or base_core["lineage"] != expected_lineage
        ):
            raise GraceLoopError("base capsule receipt internal bindings are not exact")
        if (
            base_core["producer"]["adapter_id"] != "LOCAL.GRACEGRAPH_CAPSULE.V1"
            or base_core["kind"] != "SOURCE_SNAPSHOT"
            or "DESIGN_STRUCTURE" not in base_core["capabilities"]
            or base_core["execution"]["state"] != "COMPLETE"
            or base_payload.get("capsule_run_id") != base["run_id"]
            or base_payload.get("capsule_manifest_sha256") != base["manifest_sha256"]
            or base_payload.get("verification_status") != "PASS_SEALED_BYTES_ONLY"
        ):
            raise GraceLoopError("base_capsule receipt does not prove the declared structural base")
    receipt_files = require_string_list(
        spec.get("receipt_files"), "study.receipt_files", allow_empty=False
    )
    for index, value in enumerate(receipt_files):
        require_relative(value, f"study.receipt_files[{index}]")
    if len(receipt_files) != len(receipts):
        raise GraceLoopError("receipt file inventory and loaded receipt inventory differ")
    receipt_ids = set(receipts)
    context = require_string_list(spec.get("context_receipt_ids"), "context_receipt_ids")
    if not set(context) <= receipt_ids:
        raise GraceLoopError("context_receipt_ids references unknown receipts")
    spec["context_receipt_ids"] = sorted(context)
    frames = _validate_reference_frames(spec.get("reference_frames"))
    frame_ids = {frame["id"] for frame in frames}
    for receipt_id, receipt in receipts.items():
        receipt_frame = receipt["core"]["reference_frame_id"]
        if receipt_frame is not None and receipt_frame not in frame_ids:
            raise GraceLoopError(f"receipt {receipt_id} references an undeclared reference frame")
    for frame in frames:
        transform_id = frame["transform_receipt_id"]
        if transform_id is None:
            continue
        transform = receipts.get(transform_id)
        if transform is None:
            raise GraceLoopError(f"frame {frame['id']} references a missing transform receipt")
        transform_core = transform["core"]
        if (
            transform_core["kind"] != "FRAME_TRANSFORM"
            or "FRAME_TRANSFORM" not in transform_core["capabilities"]
            or transform_core["execution"]["state"] != "COMPLETE"
            or transform_core["calibration"]["state"] not in {"NOT_APPLICABLE", "CALIBRATED"}
            or "NO_COORDINATE_EQUIVALENCE" in transform_core["prohibitions"]
        ):
            raise GraceLoopError(f"frame {frame['id']} transform receipt is unusable")
        payload = transform_core["payload"]
        if (
            payload["target_frame_id"] != frame["id"]
            or payload["source_frame_id"] not in frame_ids
            or payload["source_frame_id"] == payload["target_frame_id"]
            or transform_core["reference_frame_id"] != frame["id"]
        ):
            raise GraceLoopError(f"frame {frame['id']} transform endpoints are not bound")
        transform_outputs = {
            descriptor["sha256"] for descriptor in transform_core["execution"]["outputs"]
        }
        if not {payload["transform_sha256"], payload["scope_sha256"]} <= transform_outputs:
            raise GraceLoopError(f"frame {frame['id']} transform artifacts are not output-bound")
    decision = _validate_decision(spec.get("decision"))
    worlds = _validate_worlds(spec.get("worlds"), decision, receipt_ids)
    gates = _validate_gates(spec.get("gates"))
    experiments = _validate_experiments(
        spec.get("experiments"), decision, worlds, gates, frames, receipts
    )
    nonclaims = require_string_list(spec.get("nonclaims"), "nonclaims", allow_empty=False)
    nonclaims = [
        require_single_line(item, f"nonclaims[{index}]", max_length=1000)
        for index, item in enumerate(nonclaims)
    ]
    spec["receipt_files"] = sorted(receipt_files)
    spec["reference_frames"] = frames
    spec["decision"] = decision
    spec["worlds"] = worlds
    spec["gates"] = gates
    spec["experiments"] = experiments
    spec["nonclaims"] = sorted(nonclaims)
    _reject_forbidden_model_keys(spec)
    reject_floats(spec, "study")
    reject_private_material(spec, "study")
    return spec


def load_receipts(root: Path, receipt_files: list[str]) -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    for index, locator in enumerate(receipt_files):
        path = contained_regular_file(root, locator, f"receipt_files[{index}]")
        receipt = validate_receipt(read_json(path))
        identity = receipt["receipt_id"]
        if identity in receipts:
            raise GraceLoopError(f"duplicate receipt id: {identity}")
        receipts[identity] = receipt
    return receipts


def load_study(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    raw = read_json(path)
    if not isinstance(raw, dict):
        raise GraceLoopError("study must be an object")
    receipt_files = raw.get("receipt_files")
    if not isinstance(receipt_files, list) or any(
        not isinstance(item, str) for item in receipt_files
    ):
        raise GraceLoopError("study.receipt_files must be a list of paths")
    receipts = load_receipts(path.parent, receipt_files)
    return validate_study(raw, receipts), receipts
