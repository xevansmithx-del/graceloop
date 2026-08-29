"""Generate the deterministic CKX declaration, live-capture configs, and study lock."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from graceloop.canonical import canonical_bytes, read_json, sha256_bytes, write_canonical
from graceloop.models import fixed_boundary, frame_id_for

MODEL_RECEIPT_ID = "R_CKX_DECLARED_MODEL"
GRACEGRAPH_RECEIPT_ID = "R_GRACEGRAPH_BASE"
PHYTOPERTURB_RECEIPT_ID = "R_PHYTOPERTURB_CKX"
GRACEGRAPH_RUN_ID = "c013a2fb3f845e82"
GRACEGRAPH_MANIFEST_SHA256 = "190dc097e057f15883b9f38edf7b18ffa20db27e8e485cf0d2f824259ae1772f"
NCBI_FAMILY = "NCBI_CANNABIS_REFSEQ_20260828"


def _digest(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def _frame(kind: str, accession: str, convention: str) -> dict[str, Any]:
    core = {
        "kind": kind,
        "content_binding": {
            "mode": "UNAVAILABLE",
            "sha256": None,
            "accession_version": accession,
        },
        "coordinate_convention": convention,
        "feature_set_sha256": None,
        "comparator_sha256": None,
        "assayed_space_sha256": None,
        "transform_receipt_id": None,
    }
    return {"id": frame_id_for(core), **core}


def frames() -> dict[str, dict[str, Any]]:
    values = {
        "pink_pepper": _frame("GENOMIC", "GCF_029168945.1", "ONE_BASED_CLOSED"),
        "cs10": _frame("GENOMIC", "GCF_900626175.2_SUPPRESSED", "ONE_BASED_CLOSED"),
        "ckx_panel": _frame("PROTEIN", "CKX_SIX_REFSEQ_LABEL_SET_20260828", "NOT_APPLICABLE"),
        "founder_genome": _frame("GENOMIC", "ACTUAL_STOCK_GENOME_UNRESOLVED", "ONE_BASED_CLOSED"),
        "founder_transcripts": _frame(
            "TRANSCRIPT",
            "ACTUAL_STOCK_CKX_TRANSCRIPT_DENOMINATOR_UNRESOLVED",
            "NOT_APPLICABLE",
        ),
        "assay": _frame("ASSAY", "ALL_SIX_IDENTITY_EXPRESSION_UNQUALIFIED", "NOT_APPLICABLE"),
        "comparative": _frame("GENOMIC", "COMPARATIVE_CKX_PANEL_UNLOCKED", "ONE_BASED_CLOSED"),
    }
    return values


def decision() -> dict[str, Any]:
    return {
        "id": "D_STAGE1_CKX_DISPOSITION",
        "question": "Which CKX Stage-1 qualification disposition would remain eligible for later named human review?",
        "defer_option_id": "D_DEFER",
        "options": [
            {"id": "D_CKX2_ONLY_RETAIN", "label": "Retain CKX2-only for later review"},
            {"id": "D_CKX3_ONLY_RETAIN", "label": "Retain CKX3-only for later review"},
            {"id": "D_COMBINED_RETAIN", "label": "Retain combined or redundant model"},
            {"id": "D_OTHER_RETAIN", "label": "Retain neither or other and redesign"},
            {"id": "D_DEFER", "label": "Defer every substantive disposition"},
        ],
    }


def worlds() -> list[dict[str, Any]]:
    return [
        {
            "id": "W_CKX2_ONLY",
            "label": "Only the CKX2 disposition satisfies the frozen Stage-1 rule",
            "open_world_residual": False,
            "admissible_options": ["D_CKX2_ONLY_RETAIN", "D_DEFER"],
            "source_receipt_ids": [],
        },
        {
            "id": "W_CKX3_ONLY",
            "label": "Only the CKX3 disposition satisfies the frozen Stage-1 rule",
            "open_world_residual": False,
            "admissible_options": ["D_CKX3_ONLY_RETAIN", "D_DEFER"],
            "source_receipt_ids": [],
        },
        {
            "id": "W_COMBINED",
            "label": "The combined or redundancy disposition satisfies the frozen Stage-1 rule",
            "open_world_residual": False,
            "admissible_options": ["D_COMBINED_RETAIN", "D_DEFER"],
            "source_receipt_ids": [],
        },
        {
            "id": "W_OTHER",
            "label": "Neither declared lead model is adequate or another mechanism dominates",
            "open_world_residual": True,
            "admissible_options": ["D_OTHER_RETAIN", "D_DEFER"],
            "source_receipt_ids": [],
        },
    ]


def gates() -> list[dict[str, Any]]:
    rows = [
        ("G_P0_AUTHORITY_SCOPE", "Program authority and scope approved", "OWNER"),
        ("G_ACTUAL_STOCK_AUTHENTICATED", "Actual experimental stock authenticated", "BIOLOGICAL"),
        (
            "G_FOUNDER_DENOMINATOR_LOCK",
            "Founder CKX identity and copy denominator locked",
            "BIOLOGICAL",
        ),
        ("G_TISSUE_STAGE_PLAN_LOCK", "Tissue and developmental-stage plan locked", "BIOLOGICAL"),
        ("G_ASSAY_QUALIFIED", "All-six identity and expression assay qualified", "BIOLOGICAL"),
        ("G_EXPRESSION_RUNTIME_LOCK", "Expression-analysis runtime locked", "SOFTWARE"),
        ("G_PREREGISTERED_QUALIFICATION_RULE", "Stage-1 qualification rule preregistered", "HUMAN"),
        ("G_POWER_JUSTIFICATION", "Sampling and power justification accepted", "DATA"),
        ("G_QUALIFIED_CKX_REVIEW", "Named CKX review completed", "HUMAN"),
        ("G_COMPARATOR_PANEL_LOCK", "Comparative-genome panel and comparator locked", "DATA"),
        (
            "G_DELIVERY_TRANSFORMATION",
            "Delivery and transformation readiness established",
            "BIOLOGICAL",
        ),
        ("G_RIGHTS_AND_TRANSPORT", "Rights and transport authority established", "LEGAL"),
    ]
    return [
        {"id": identity, "label": label, "state": "OPEN", "authority_scope": authority}
        for identity, label, authority in rows
    ]


def _outcomes() -> list[dict[str, str]]:
    return [
        {
            "id": "O_POSITIVE",
            "label": "Operational positive classification",
            "class": "INFORMATIVE_POSITIVE",
        },
        {
            "id": "O_NEGATIVE",
            "label": "Operational negative classification",
            "class": "INFORMATIVE_NEGATIVE",
        },
        {
            "id": "O_ALTERNATIVE",
            "label": "Operational alternative classification",
            "class": "INFORMATIVE_ALTERNATIVE",
        },
        {"id": "O_OTHER", "label": "Qualified other or neither classification", "class": "OTHER"},
        {"id": "O_NO_CALL", "label": "No valid classification", "class": "NO_CALL"},
        {"id": "O_QC_FAILED", "label": "Quality-control failure", "class": "QC_FAILED"},
        {
            "id": "O_CONTRADICTORY",
            "label": "Contradictory qualified outputs",
            "class": "CONTRADICTORY",
        },
        {
            "id": "O_UNEXPECTED",
            "label": "Output outside the frozen classifier",
            "class": "UNEXPECTED",
        },
    ]


def _predictions(matrix: dict[str, list[str]]) -> list[dict[str, str]]:
    world_ids = ["W_CKX2_ONLY", "W_CKX3_ONLY", "W_COMBINED", "W_OTHER"]
    rows: list[dict[str, str]] = []
    for outcome in _outcomes():
        relations = matrix.get(outcome["id"], ["UNKNOWN"] * len(world_ids))
        rows.extend(
            {
                "world_id": world_id,
                "outcome_id": outcome["id"],
                "relation": relations[index],
            }
            for index, world_id in enumerate(world_ids)
        )
    return rows


def _protocol(
    identity: str,
    execution_class: str,
    purpose: str,
    frame_ids: list[str],
    required_gates: list[str],
    resources: dict[str, Any],
) -> dict[str, Any]:
    ckx_members = [
        {"label": "CKX1", "gene_id": "115710080", "protein": "XP_030494262.2"},
        {"label": "CKX2", "gene_id": "115705068", "protein": "XP_030488167.2"},
        {"label": "CKX3", "gene_id": "115704143", "protein": "XP_030487220.2"},
        {"label": "CKX5", "gene_id": "115703213", "protein": "XP_030486587.2"},
        {"label": "CKX6", "gene_id": "115711707", "protein": "XP_030495954.2"},
        {"label": "CKX7", "gene_id": "115706237", "protein": "XP_030489681.2"},
    ]
    input_denominator = {
        "operation_id": identity,
        "reference_frame_ids": sorted(frame_ids),
        "denominator_status": "FROZEN_DECLARED_METADATA_ONLY",
        "actual_stock_status": "UNAUTHENTICATED",
        "members": ckx_members if identity == "E_ALL_SIX_IDENTITY_EXPRESSION" else [],
    }
    comparator = {
        "operation_id": identity,
        "declared_world_ids": [
            "W_CKX2_ONLY",
            "W_CKX3_ONLY",
            "W_COMBINED",
            "W_OTHER",
        ],
        "comparison_status": "DECLARED_COUNTERFACTUAL_NOT_EMPIRICALLY_CALIBRATED",
    }
    if identity == "E_ALL_SIX_IDENTITY_EXPRESSION":
        outcome_rules = {
            "O_POSITIVE": "ONLY_CKX2_SATISFIES_FROZEN_STAGE1_RULE",
            "O_NEGATIVE": "ONLY_CKX3_SATISFIES_FROZEN_STAGE1_RULE",
            "O_ALTERNATIVE": "FROZEN_COMBINED_OR_REDUNDANCY_RULE_SATISFIED",
            "O_OTHER": "QUALIFIED_RESULT_MAPS_TO_RESIDUAL_NEITHER_OR_OTHER",
            "O_NO_CALL": "NO_VALID_CLASSIFICATION",
            "O_QC_FAILED": "ONE_OR_MORE_PREREGISTERED_QC_RULES_FAIL",
            "O_CONTRADICTORY": "QUALIFIED_OUTPUTS_SUPPORT_INCOMPATIBLE_CLASSES",
            "O_UNEXPECTED": "OUTPUT_OUTSIDE_FROZEN_CLASSIFIER",
        }
        threshold_status = "UNDEFINED_PENDING_PREREGISTRATION_AND_ASSAY_QUALIFICATION"
    else:
        outcome_rules = {
            outcome["id"]: "DECLARED_CLASS_ONLY_NO_OPERATIONAL_THRESHOLD" for outcome in _outcomes()
        }
        threshold_status = "NOT_OPERATIONALLY_SPECIFIED"
    outcome_classifier = {
        "operation_id": identity,
        "outcome_rules": outcome_rules,
        "threshold_status": threshold_status,
        "human_review_required": True,
    }
    qc_rules = {
        "operation_id": identity,
        "failure_classes": ["NO_CALL", "QC_FAILED", "CONTRADICTORY", "UNEXPECTED"],
        "rule_status": "PENDING_PREREGISTRATION",
        "failure_action": "PRESERVE_ALL_ACTIVE_WORLDS_NO_UPDATE",
    }
    resource_basis = {
        "operation_id": identity,
        "declared_resources": resources,
        "calibration_status": "UNAUTHENTICATED_UNCALIBRATED",
    }
    return {
        "schema_version": "graceloop.protocol-lock.v1",
        "operation_id": identity,
        "execution_class": execution_class,
        "purpose_code": purpose,
        "input_denominator_sha256": _digest(input_denominator),
        "comparator_sha256": _digest(comparator),
        "outcome_classifier_sha256": _digest(outcome_classifier),
        "qc_rules_sha256": _digest(qc_rules),
        "reference_frame_ids": frame_ids,
        "requires_gates": required_gates,
        "resource_basis_sha256": _digest(resource_basis),
        "component_declarations": {
            "input_denominator": input_denominator,
            "comparator": comparator,
            "outcome_classifier": outcome_classifier,
            "qc_rules": qc_rules,
            "resource_basis": resource_basis,
        },
    }


def _experiment(
    identity: str,
    label: str,
    execution_class: str,
    frame_ids: list[str],
    required_gates: list[str],
    resources: dict[str, Any],
    matrix: dict[str, list[str]],
    rationale: str,
) -> dict[str, Any]:
    return {
        "id": identity,
        "label": label,
        "execution_class": execution_class,
        "reference_frame_ids": frame_ids,
        "requires_gates": required_gates,
        "outcomes": _outcomes(),
        "predictions": _predictions(matrix),
        "resources": resources,
        "rationale_code": rationale,
        "protocol_lock": _protocol(
            identity, execution_class, rationale, frame_ids, required_gates, resources
        ),
    }


def declaration() -> dict[str, Any]:
    frame = frames()
    all_permit = {
        outcome: ["PERMITS"] * 4
        for outcome in ("O_POSITIVE", "O_NEGATIVE", "O_ALTERNATIVE", "O_OTHER")
    }
    corrected_tree = {
        "O_POSITIVE": ["PERMITS", "UNKNOWN", "PERMITS", "UNKNOWN"],
        "O_NEGATIVE": ["UNKNOWN", "PERMITS", "PERMITS", "UNKNOWN"],
        "O_ALTERNATIVE": ["PERMITS", "PERMITS", "PERMITS", "PERMITS"],
        "O_OTHER": ["UNKNOWN", "UNKNOWN", "UNKNOWN", "PERMITS"],
    }
    microsynteny = {
        "O_POSITIVE": ["PERMITS", "UNKNOWN", "PERMITS", "UNKNOWN"],
        "O_NEGATIVE": ["UNKNOWN", "PERMITS", "PERMITS", "UNKNOWN"],
        "O_ALTERNATIVE": ["PERMITS", "PERMITS", "PERMITS", "UNKNOWN"],
        "O_OTHER": ["UNKNOWN", "UNKNOWN", "UNKNOWN", "PERMITS"],
    }
    decisive = {
        "O_POSITIVE": ["PERMITS", "EXCLUDES", "EXCLUDES", "EXCLUDES"],
        "O_NEGATIVE": ["EXCLUDES", "PERMITS", "EXCLUDES", "EXCLUDES"],
        "O_ALTERNATIVE": ["EXCLUDES", "EXCLUDES", "PERMITS", "EXCLUDES"],
        "O_OTHER": ["EXCLUDES", "EXCLUDES", "EXCLUDES", "PERMITS"],
    }
    premature_single = {
        "O_POSITIVE": ["UNKNOWN", "PERMITS", "PERMITS", "UNKNOWN"],
        "O_NEGATIVE": ["PERMITS", "UNKNOWN", "PERMITS", "UNKNOWN"],
        "O_ALTERNATIVE": ["UNKNOWN", "UNKNOWN", "PERMITS", "UNKNOWN"],
        "O_OTHER": ["UNKNOWN", "UNKNOWN", "UNKNOWN", "PERMITS"],
    }
    pair_screen = {
        "O_POSITIVE": ["PERMITS", "UNKNOWN", "PERMITS", "UNKNOWN"],
        "O_NEGATIVE": ["UNKNOWN", "PERMITS", "PERMITS", "UNKNOWN"],
        "O_ALTERNATIVE": ["UNKNOWN", "UNKNOWN", "PERMITS", "UNKNOWN"],
        "O_OTHER": ["UNKNOWN", "UNKNOWN", "UNKNOWN", "PERMITS"],
    }
    all_six_frames = [
        frame["founder_genome"]["id"],
        frame["founder_transcripts"]["id"],
        frame["assay"]["id"],
        frame["ckx_panel"]["id"],
    ]
    qualification_gates = [
        "G_P0_AUTHORITY_SCOPE",
        "G_ACTUAL_STOCK_AUTHENTICATED",
        "G_FOUNDER_DENOMINATOR_LOCK",
        "G_TISSUE_STAGE_PLAN_LOCK",
        "G_ASSAY_QUALIFIED",
        "G_EXPRESSION_RUNTIME_LOCK",
        "G_PREREGISTERED_QUALIFICATION_RULE",
        "G_POWER_JUSTIFICATION",
        "G_QUALIFIED_CKX_REVIEW",
        "G_RIGHTS_AND_TRANSPORT",
    ]
    material_gates = qualification_gates + [
        "G_DELIVERY_TRANSFORMATION",
    ]
    experiments = [
        _experiment(
            "E_PUBLIC_REFERENCE_REFRESH",
            "Refresh public Cannabis assembly and annotation metadata",
            "READ_ONLY_COMPUTATION",
            [frame["pink_pepper"]["id"], frame["cs10"]["id"]],
            [],
            {
                "duration_days": 1,
                "sample_units": 0,
                "relative_cost": 1,
                "material_risk": 0,
                "irreversibility": 0,
            },
            all_permit,
            "PUBLIC_METADATA_REFRESH",
        ),
        _experiment(
            "E_REPEAT_CORRECTED_TREE",
            "Repeat the corrected six-member phylogeny without target narrowing",
            "READ_ONLY_COMPUTATION",
            [frame["pink_pepper"]["id"], frame["ckx_panel"]["id"]],
            ["G_COMPARATOR_PANEL_LOCK"],
            {
                "duration_days": 3,
                "sample_units": 0,
                "relative_cost": 2,
                "material_risk": 0,
                "irreversibility": 0,
            },
            corrected_tree,
            "CORRECTED_TREE_REPLAY",
        ),
        _experiment(
            "E_CROSS_SPECIES_MICROSYNTENY",
            "Run a reference-bound comparative microsynteny analysis",
            "READ_ONLY_COMPUTATION",
            [frame["comparative"]["id"], frame["ckx_panel"]["id"]],
            ["G_COMPARATOR_PANEL_LOCK"],
            {
                "duration_days": 7,
                "sample_units": 0,
                "relative_cost": 3,
                "material_risk": 0,
                "irreversibility": 0,
            },
            microsynteny,
            "MICROSYNTENY_DISCRIMINATION",
        ),
        _experiment(
            "E_ALL_SIX_IDENTITY_EXPRESSION",
            "Qualify all-six actual-stock identity plus tissue and stage expression",
            "NONINTERVENTIONAL_MEASUREMENT",
            all_six_frames,
            qualification_gates,
            {
                "duration_days": "UNKNOWN",
                "sample_units": "UNKNOWN",
                "relative_cost": 4,
                "material_risk": 1,
                "irreversibility": 0,
            },
            decisive,
            "ALL_SIX_STAGE1_DISCRIMINATOR",
        ),
        _experiment(
            "E_PREMATURE_SINGLE_CKX3",
            "Premature single-member CKX3 perturbation",
            "MATERIAL_PERTURBATION",
            all_six_frames,
            material_gates,
            {
                "duration_days": "UNKNOWN",
                "sample_units": "UNKNOWN",
                "relative_cost": 8,
                "material_risk": 8,
                "irreversibility": 6,
            },
            premature_single,
            "PREMATURE_SINGLE_MEMBER_PERTURBATION",
        ),
        _experiment(
            "E_CONDITIONAL_CKX2_CKX3_PAIR_SCREEN",
            "Conditional paired CKX2 and CKX3 perturbation screen",
            "MATERIAL_PERTURBATION",
            all_six_frames,
            material_gates,
            {
                "duration_days": "UNKNOWN",
                "sample_units": "UNKNOWN",
                "relative_cost": 9,
                "material_risk": 9,
                "irreversibility": 7,
            },
            pair_screen,
            "CONDITIONAL_PAIR_PERTURBATION",
        ),
    ]
    return {
        "schema_version": "graceloop.declared-model.v1",
        "decision": decision(),
        "worlds": worlds(),
        "gates": gates(),
        "experiments": experiments,
    }


def capture_configs() -> dict[str, dict[str, Any]]:
    frame = frames()
    current_frame = frame["pink_pepper"]["id"]
    cs10_frame = frame["cs10"]["id"]
    base = {
        "schema_version": "graceloop.capture-tooluniverse.v1",
        "evidence_family": NCBI_FAMILY,
        "subject_alias": None,
        "reference_frame_id": None,
    }
    configs: dict[str, dict[str, Any]] = {
        "R_NCBI_CANNABIS_ASSEMBLIES": {
            **base,
            "receipt_id": "R_NCBI_CANNABIS_ASSEMBLIES",
            "tool_name": "NCBIDatasets_list_genomes_by_taxon",
            "arguments": {"taxon": "Cannabis sativa", "limit": 100, "reference_only": False},
        },
        "R_NCBI_PINK_PEPPER": {
            **base,
            "receipt_id": "R_NCBI_PINK_PEPPER",
            "tool_name": "NCBIDatasets_get_genome_assembly",
            "arguments": {"accession": "GCF_029168945.1"},
            "subject_alias": {
                "namespace": "NCBI_Assembly",
                "namespace_version": "20260828",
                "alias": "GCF_029168945.1",
                "kind": "OTHER",
            },
            "reference_frame_id": current_frame,
        },
        "R_NCBI_CS10_SUPPRESSED": {
            **base,
            "receipt_id": "R_NCBI_CS10_SUPPRESSED",
            "tool_name": "NCBIDatasets_get_genome_assembly",
            "arguments": {"accession": "GCF_900626175.2"},
            "subject_alias": {
                "namespace": "NCBI_Assembly",
                "namespace_version": "20260828",
                "alias": "GCF_900626175.2",
                "kind": "OTHER",
            },
            "reference_frame_id": cs10_frame,
        },
        "R_PUBMED_CKX3_CKX5": {
            "schema_version": "graceloop.capture-tooluniverse.v1",
            "receipt_id": "R_PUBMED_CKX3_CKX5",
            "tool_name": "PubMed_search_articles",
            "arguments": {"query": "21224426[PMID]", "limit": 3, "include_abstract": False},
            "evidence_family": "PUBMED_CKX_PRIMARY_INDEX_20260828",
            "subject_alias": {
                "namespace": "PubMed",
                "namespace_version": "20260828",
                "alias": "21224426",
                "kind": "OTHER",
            },
            "reference_frame_id": None,
        },
        "R_PLANT_REACTOME_CYTOKININ": {
            "schema_version": "graceloop.capture-tooluniverse.v1",
            "receipt_id": "R_PLANT_REACTOME_CYTOKININ",
            "tool_name": "PlantReactome_search_pathways",
            "arguments": {"query": "cytokinin dehydrogenase"},
            "evidence_family": "PLANT_REACTOME_CYTOKININ_20260828",
            "subject_alias": None,
            "reference_frame_id": None,
        },
        "R_PLANT_REACTOME_CANNABIS": {
            "schema_version": "graceloop.capture-tooluniverse.v1",
            "receipt_id": "R_PLANT_REACTOME_CANNABIS",
            "tool_name": "PlantReactome_search_pathways",
            "arguments": {"query": "cytokinin dehydrogenase", "species": "Cannabis sativa"},
            "evidence_family": "PLANT_REACTOME_CYTOKININ_20260828",
            "subject_alias": None,
            "reference_frame_id": None,
        },
        "R_OMA_CKX2": {
            "schema_version": "graceloop.capture-tooluniverse.v1",
            "receipt_id": "R_OMA_CKX2",
            "tool_name": "OMA_resolve_xref",
            "arguments": {"search": "XP_030488167.2", "limit": 25},
            "evidence_family": "OMA_CANNABIS_CKX_MAPPING_20260828",
            "subject_alias": {
                "namespace": "RefSeq_Protein",
                "namespace_version": "20260828",
                "alias": "XP_030488167.2",
                "kind": "PROTEIN",
            },
            "reference_frame_id": None,
        },
        "R_OMA_CKX3": {
            "schema_version": "graceloop.capture-tooluniverse.v1",
            "receipt_id": "R_OMA_CKX3",
            "tool_name": "OMA_resolve_xref",
            "arguments": {"search": "XP_030487220.2", "limit": 25},
            "evidence_family": "OMA_CANNABIS_CKX_MAPPING_20260828",
            "subject_alias": {
                "namespace": "RefSeq_Protein",
                "namespace_version": "20260828",
                "alias": "XP_030487220.2",
                "kind": "PROTEIN",
            },
            "reference_frame_id": None,
        },
    }
    genes = {
        "R_NCBI_CKX1": "115710080",
        "R_NCBI_CKX2": "115705068",
        "R_NCBI_CKX3": "115704143",
        "R_NCBI_CKX5": "115703213",
        "R_NCBI_CKX6": "115711707",
        "R_NCBI_CKX7": "115706237",
    }
    for receipt_id, gene_id in genes.items():
        configs[receipt_id] = {
            **base,
            "receipt_id": receipt_id,
            "tool_name": "NCBIDatasets_get_gene",
            "arguments": {"gene_id": gene_id},
            "subject_alias": {
                "namespace": "NCBI_Gene",
                "namespace_version": "20260828",
                "alias": gene_id,
                "kind": "LOCUS",
            },
            "reference_frame_id": current_frame,
        }
    return configs


def build_study(model_receipt: dict[str, Any]) -> dict[str, Any]:
    payload = model_receipt["core"]["payload"]
    tool_receipts = sorted(capture_configs())
    receipt_ids = [
        GRACEGRAPH_RECEIPT_ID,
        PHYTOPERTURB_RECEIPT_ID,
        MODEL_RECEIPT_ID,
        *tool_receipts,
    ]
    return {
        "schema_version": "graceloop.study.v1",
        "study_id": "CKX_STAGE1_FRONTIER_20260828",
        "title": "CKX Stage-1 counterfactual experiment frontier",
        "semantics": "EXCLUSIVE_DECLARED_WORLDS_OPEN_WORLD",
        "boundary": fixed_boundary(),
        "base_capsule": {
            "run_id": GRACEGRAPH_RUN_ID,
            "manifest_sha256": GRACEGRAPH_MANIFEST_SHA256,
            "receipt_id": GRACEGRAPH_RECEIPT_ID,
        },
        "receipt_files": [f"receipts/{identity}.json" for identity in sorted(receipt_ids)],
        "context_receipt_ids": sorted(receipt_ids),
        "reference_frames": sorted(frames().values(), key=lambda item: item["id"]),
        "decision": payload["decision"],
        "worlds": payload["worlds"],
        "gates": payload["gates"],
        "experiments": payload["compiled_experiments"],
        "nonclaims": [
            "No CKX target is selected and no experiment, material work, or release is authorized.",
            "The declared matrices and resources are synthetic, uncalibrated, unauthenticated model inputs.",
            "Public database snapshots establish metadata and conflicts, not Cannabis function or causality.",
            "Stable identifiers do not establish coordinate equivalence between Pink Pepper, suppressed cs10, and the actual stock.",
            "The absence of a CKX4 label is not a biological absence claim.",
            "Empirical N, experiments performed, biological gates closed, and results present all remain zero.",
        ],
    }


def _write_new(path: Path, value: Any) -> None:
    if path.exists() or path.is_symlink():
        raise SystemExit(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_canonical(path, value)


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("destination", type=Path)
    study = commands.add_parser("study")
    study.add_argument("model_receipt", type=Path)
    study.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        destination = args.destination
        _write_new(destination / "declared_model.json", declaration())
        for identity, config in sorted(capture_configs().items()):
            _write_new(destination / "capture_configs" / f"{identity}.json", config)
        _write_new(
            destination / "fixture_metadata.json",
            {
                "schema_version": "graceloop.ckx-fixture-metadata.v1",
                "model_receipt_id": MODEL_RECEIPT_ID,
                "gracegraph_receipt_id": GRACEGRAPH_RECEIPT_ID,
                "phytoperturb_receipt_id": PHYTOPERTURB_RECEIPT_ID,
                "reference_frame_ids": {
                    key: value["id"] for key, value in sorted(frames().items())
                },
            },
        )
    else:
        _write_new(args.output, build_study(read_json(args.model_receipt)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
