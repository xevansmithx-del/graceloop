"""Registered, sequence-free ToolUniverse and PhytoPerturb receipt adapters."""

from __future__ import annotations

import math
import os
import platform
import re
import selectors
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .canonical import (
    GraceLoopError,
    canonical_bytes,
    read_json_bytes,
    reject_floats,
    reject_private_material,
    require_alias,
    require_id,
    require_only_keys,
    require_relative,
    require_string,
    sha256_bytes,
    sha256_file,
)
from .models import (
    COMPILER_VERSION,
    _validate_decision,
    _validate_experiments,
    _validate_gates,
    _validate_worlds,
    prediction_model_core,
    validate_protocol_lock,
)
from .receipt import SUBJECT_KINDS, build_receipt

CAPTURE_CONFIG_SCHEMA = "graceloop.capture-tooluniverse.v1"
MAX_TOOL_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_TOOL_ERROR_BYTES = 1024 * 1024
PINNED_PHYTOPERTURB_VERIFIER_SHA256 = (
    "7f5cda3ae79fffe34fb99073d766419583a15ca7d805468fa6ff20fc74d3b4ea"
)
PINNED_PHYTORESOLVE_HEAD = "9d1aa27edd9cb355c4de0ad1dee97c6af7b840c861c0307c7e9d120783ffbbab"
PINNED_PHYTOPERTURB_PROOF_SHA256 = (
    "57d3e5702a00de2c1a7cc0207dbd0ddaa73c3774ed6a18a2fd4a4662ddd8b6ee"
)
PINNED_GRACEGRAPH_SOURCE_MANIFEST_SHA256 = (
    "3c838068b20f00c6fd13c0d59bfa83a642e577de76304eb951a2195fcd84cb50"
)


SAFE_GENERIC_KEYS = {
    "accession",
    "accession_version",
    "aliases",
    "annotation_name",
    "annotation_provider",
    "article_type",
    "assembly",
    "assembly_level",
    "assembly_name",
    "assembly_status",
    "authors",
    "begin",
    "bioproject_accession",
    "canonical_id",
    "category",
    "chromosome",
    "chromosomes",
    "common_name",
    "compartment_names",
    "contig_n50",
    "count",
    "data_source",
    "description",
    "doi",
    "doi_url",
    "end",
    "entry_id",
    "evidence",
    "evidence_code",
    "exact_type",
    "feature_type",
    "gene_id",
    "gene_name",
    "gene_names",
    "genomic_locations",
    "gc_percent",
    "go_id",
    "go_name",
    "go_term",
    "id",
    "idlist",
    "inference_type",
    "isInferred",
    "is_open_access",
    "journal",
    "journal_title",
    "length",
    "map_position",
    "mapping_status",
    "metadata",
    "name",
    "nomenclature_authority",
    "number_of_chromosomes",
    "number_of_contigs",
    "oma_group",
    "omaid",
    "operation",
    "organism",
    "organism_name",
    "orientation",
    "paired_accession",
    "pmcid",
    "pmid",
    "protein_name",
    "pub_date",
    "pub_year",
    "publication_year",
    "query",
    "query_gene_id",
    "query_taxon",
    "querytranslation",
    "refseq_category",
    "rel_type",
    "release_date",
    "returned",
    "results",
    "scaffold_n50",
    "source",
    "source_database",
    "species",
    "stId",
    "strain",
    "submitter",
    "symbol",
    "synonyms",
    "tax_id",
    "taxname",
    "title",
    "total",
    "total_available",
    "total_results",
    "total_sequence_length",
    "type",
    "uniprot_accession",
    "url",
    "xref",
    "swiss_prot_accessions",
    "ensembl_gene_ids",
    "omim_ids",
    "page_size",
    "author_count",
    "authors_truncated",
    "pmc_url",
    "entries",
    "domains",
    "interpro",
    "pfam",
    "start",
    "stop",
    "term",
    "hitCount",
}


def _decimal_string(value: float) -> str:
    if not math.isfinite(value):
        raise GraceLoopError("tool result contains a non-finite number")
    return format(value, ".17g")


def _safe_projection(
    value: Any, *, depth: int = 0, projection_stats: dict[str, int] | None = None
) -> Any:
    if projection_stats is None:
        projection_stats = {"omitted_fields": 0}
    if depth > 8:
        raise GraceLoopError("tool result exceeds projection depth")
    if value is None or isinstance(value, bool | int | str):
        if isinstance(value, str):
            if len(value) > 3000:
                projection_stats["omitted_fields"] += 1
                return value[:3000] + "[TRUNCATED]"
            reject_private_material(value, "tool projection")
        return value
    if isinstance(value, float):
        return _decimal_string(value)
    if isinstance(value, list):
        return [
            _safe_projection(item, depth=depth + 1, projection_stats=projection_stats)
            for item in value
        ]
    if isinstance(value, dict):
        projected = {}
        for key in sorted(value):
            if key in SAFE_GENERIC_KEYS:
                projected[key] = _safe_projection(
                    value[key], depth=depth + 1, projection_stats=projection_stats
                )
            else:
                projection_stats["omitted_fields"] += 1
        return projected
    raise GraceLoopError("tool result contains an unsupported projected value")


def _require_arguments(
    arguments: Any,
    *,
    allowed: set[str],
    required: set[str],
    field_validators: dict[str, Callable[[Any], bool]],
) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise GraceLoopError("capture arguments must be an object")
    require_only_keys(arguments, allowed, "capture.arguments")
    missing = sorted(required - set(arguments))
    if missing:
        raise GraceLoopError(f"capture arguments missing: {missing}")
    for key, value in arguments.items():
        validator = field_validators.get(key)
        if validator is None or not validator(value):
            raise GraceLoopError(f"capture argument {key} is invalid")
    reject_floats(arguments, "capture.arguments")
    reject_private_material(arguments, "capture.arguments")
    return arguments


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 1000


def _positive_int(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and 1 <= value <= 1000


def _boolean(value: Any) -> bool:
    return isinstance(value, bool)


def _gene_id(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[1-9][0-9]*", value))


def _accession(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_.-]{2,80}", value))


def _pubmed_abstract_off(value: Any) -> bool:
    return value is False


def _sort_value(value: Any) -> bool:
    return isinstance(value, str) and value in {"relevance", "pub_date", "first_author", "journal"}


TOOL_ADAPTERS: dict[str, dict[str, Any]] = {
    "NCBIDatasets_get_gene": {
        "adapter_id": "TU.NCBI_DATASETS_GENE.V1",
        "allowed": {"gene_id"},
        "required": {"gene_id"},
        "validators": {"gene_id": _gene_id},
        "capabilities": ["IDENTIFIER_METADATA", "REFERENCE_LABEL"],
        "source": "NCBI Datasets",
        "search": False,
    },
    "NCBIDatasets_list_genomes_by_taxon": {
        "adapter_id": "TU.NCBI_DATASETS_ASSEMBLIES.V1",
        "allowed": {"taxon", "limit", "reference_only"},
        "required": {"taxon"},
        "validators": {"taxon": _nonempty, "limit": _positive_int, "reference_only": _boolean},
        "capabilities": ["IDENTIFIER_METADATA", "REFERENCE_LABEL"],
        "source": "NCBI Datasets",
        "search": True,
    },
    "NCBIDatasets_get_genome_assembly": {
        "adapter_id": "TU.NCBI_DATASETS_ASSEMBLY.V1",
        "allowed": {"accession"},
        "required": {"accession"},
        "validators": {"accession": _accession},
        "capabilities": ["IDENTIFIER_METADATA", "REFERENCE_LABEL"],
        "source": "NCBI Datasets",
        "search": False,
    },
    "NCBIGene_search": {
        "adapter_id": "TU.NCBI_GENE_SEARCH.V1",
        "allowed": {"term", "retmax"},
        "required": {"term"},
        "validators": {"term": _nonempty, "retmax": _positive_int},
        "capabilities": ["IDENTIFIER_METADATA"],
        "source": "NCBI Gene",
        "search": True,
    },
    "NCBIProtein_get_summary": {
        "adapter_id": "TU.NCBI_PROTEIN_SUMMARY.V1",
        "allowed": {"id"},
        "required": {"id"},
        "validators": {"id": _accession},
        "capabilities": ["IDENTIFIER_METADATA", "REFERENCE_LABEL"],
        "source": "NCBI Protein",
        "search": False,
    },
    "PubMed_search_articles": {
        "adapter_id": "TU.PUBMED_SEARCH.V1",
        "allowed": {"query", "limit", "include_abstract", "sort", "mindate", "maxdate", "datetype"},
        "required": {"query", "include_abstract"},
        "validators": {
            "query": _nonempty,
            "limit": _positive_int,
            "include_abstract": _pubmed_abstract_off,
            "sort": _sort_value,
            "mindate": _nonempty,
            "maxdate": _nonempty,
            "datetype": _nonempty,
        },
        "capabilities": ["LITERATURE_INDEX_METADATA"],
        "source": "PubMed",
        "search": True,
    },
    "EuropePMC_search_articles": {
        "adapter_id": "TU.EUROPE_PMC_SEARCH.V1",
        "allowed": {"query", "limit", "require_has_ft", "enrich_missing_abstract"},
        "required": {"query"},
        "validators": {
            "query": _nonempty,
            "limit": _positive_int,
            "require_has_ft": _boolean,
            "enrich_missing_abstract": lambda value: value is False,
        },
        "capabilities": ["LITERATURE_INDEX_METADATA"],
        "source": "Europe PMC",
        "search": True,
    },
    "PlantReactome_search_pathways": {
        "adapter_id": "TU.PLANT_REACTOME_SEARCH.V1",
        "allowed": {"query", "species"},
        "required": {"query"},
        "validators": {"query": _nonempty, "species": _nonempty},
        "capabilities": ["PATHWAY_PROJECTION_METADATA"],
        "source": "Plant Reactome",
        "search": True,
    },
    "PlantReactome_get_pathway": {
        "adapter_id": "TU.PLANT_REACTOME_PATHWAY.V1",
        "allowed": {"pathway_id"},
        "required": {"pathway_id"},
        "validators": {"pathway_id": _accession},
        "capabilities": ["PATHWAY_PROJECTION_METADATA", "FUNCTION_ANNOTATION"],
        "source": "Plant Reactome",
        "search": False,
    },
    "PlantReactome_get_pathway_participants": {
        "adapter_id": "TU.PLANT_REACTOME_PARTICIPANTS.V1",
        "allowed": {"pathway_id"},
        "required": {"pathway_id"},
        "validators": {"pathway_id": _accession},
        "capabilities": ["PATHWAY_PROJECTION_METADATA", "FUNCTION_ANNOTATION"],
        "source": "Plant Reactome",
        "search": True,
    },
    "OMA_resolve_xref": {
        "adapter_id": "TU.OMA_XREF.V1",
        "allowed": {"search", "limit"},
        "required": {"search"},
        "validators": {"search": _accession, "limit": _positive_int},
        "capabilities": ["IDENTIFIER_METADATA", "ORTHOLOGY_PROJECTION", "REFERENCE_LABEL"],
        "source": "OMA",
        "search": True,
    },
    "OMA_get_protein_go": {
        "adapter_id": "TU.OMA_GO.V1",
        "allowed": {"protein_id"},
        "required": {"protein_id"},
        "validators": {"protein_id": _accession},
        "capabilities": ["FUNCTION_ANNOTATION"],
        "source": "OMA",
        "search": True,
    },
    "InterPro_get_protein_domain_architecture": {
        "adapter_id": "TU.INTERPRO_DOMAIN_ARCH.V1",
        "allowed": {"accession"},
        "required": {"accession"},
        "validators": {"accession": _accession},
        "capabilities": ["DOMAIN_ANNOTATION"],
        "source": "InterPro",
        "search": True,
    },
}


def _validate_capture_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise GraceLoopError("capture config must be an object")
    require_only_keys(
        config,
        {
            "schema_version",
            "receipt_id",
            "tool_name",
            "arguments",
            "evidence_family",
            "subject_alias",
            "reference_frame_id",
        },
        "capture config",
    )
    if config.get("schema_version") != CAPTURE_CONFIG_SCHEMA:
        raise GraceLoopError(f"capture config schema must be {CAPTURE_CONFIG_SCHEMA}")
    config["receipt_id"] = require_id(config.get("receipt_id"), "capture.receipt_id")
    tool_name = require_string(config.get("tool_name"), "capture.tool_name", max_length=100)
    if tool_name not in TOOL_ADAPTERS:
        raise GraceLoopError(f"unregistered ToolUniverse adapter: {tool_name}")
    adapter = TOOL_ADAPTERS[tool_name]
    config["arguments"] = _require_arguments(
        config.get("arguments"),
        allowed=adapter["allowed"],
        required=adapter["required"],
        field_validators=adapter["validators"],
    )
    config["evidence_family"] = require_id(config.get("evidence_family"), "capture.evidence_family")
    subject = config.get("subject_alias")
    if subject is not None:
        if not isinstance(subject, dict):
            raise GraceLoopError("capture.subject_alias must be null or an object")
        require_only_keys(subject, {"namespace", "namespace_version", "alias", "kind"}, "subject")
        subject["namespace"] = require_id(subject.get("namespace"), "subject.namespace")
        subject["namespace_version"] = require_string(
            subject.get("namespace_version"), "subject.namespace_version", max_length=100
        )
        subject["alias"] = require_alias(subject.get("alias"), "subject.alias")
        if subject.get("kind") not in SUBJECT_KINDS:
            raise GraceLoopError("subject.kind is not registered")
    reference = config.get("reference_frame_id")
    if reference is not None and (
        not isinstance(reference, str) or not re.fullmatch(r"frame:[0-9a-f]{64}", reference)
    ):
        raise GraceLoopError("capture.reference_frame_id must be frame:<sha256> or null")
    reject_private_material(config, "capture config")
    return config


def _tool_version(tu_path: str) -> str:
    result = _run_bounded_command(
        [tu_path, "--version"], timeout=15, stdout_limit=4096, stderr_limit=4096
    )
    if result.returncode != 0:
        raise GraceLoopError("cannot determine ToolUniverse version")
    return result.stdout.decode("utf-8", errors="strict").strip()


def _run_bounded_command(
    command: list[str],
    *,
    timeout: int,
    stdout_limit: int,
    stderr_limit: int,
    environment: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run without allowing stdout/stderr to grow beyond fixed in-memory bounds."""

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        cwd=cwd,
        start_new_session=True,
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        raise GraceLoopError("bounded subprocess did not expose pipes")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": stdout_limit, "stderr": stderr_limit}
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                os.killpg(process.pid, 9)
                process.wait()
                raise subprocess.TimeoutExpired(
                    command,
                    timeout,
                    output=bytes(buffers["stdout"]),
                    stderr=bytes(buffers["stderr"]),
                )
            events = selector.select(min(0.25, remaining))
            for key, _mask in events:
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                name = key.data
                buffers[name].extend(chunk)
                if len(buffers[name]) > limits[name]:
                    os.killpg(process.pid, 9)
                    process.wait()
                    raise GraceLoopError(f"subprocess {name} exceeds the capture limit")
        returncode = process.wait()
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
        if process.poll() is None:
            os.killpg(process.pid, 9)
            process.wait()
    return subprocess.CompletedProcess(
        command, returncode, bytes(buffers["stdout"]), bytes(buffers["stderr"])
    )


def _extract_data(raw: Any) -> tuple[str, Any, dict[str, Any]]:
    if not isinstance(raw, dict):
        return "FAILED", None, {"reason": "TOOL_RESPONSE_NOT_OBJECT"}
    status = raw.get("status")
    if status != "success":
        return "FAILED", None, {"reason": "TOOL_REPORTED_FAILURE"}
    data = raw.get("data")
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    if not metadata and isinstance(data, dict) and isinstance(data.get("metadata"), dict):
        metadata = data["metadata"]
    return "COMPLETE", data, metadata


def _projection_for(
    tool_name: str, data: Any, metadata: dict[str, Any]
) -> tuple[dict[str, Any], int]:
    stats = {"omitted_fields": 0}
    if tool_name == "NCBIGene_search":
        result = data.get("esearchresult", {}) if isinstance(data, dict) else {}
        if isinstance(data, dict):
            stats["omitted_fields"] += len(set(data) - {"esearchresult"})
        if isinstance(result, dict):
            stats["omitted_fields"] += len(set(result) - {"count", "idlist", "querytranslation"})
        projection = {
            "count": result.get("count"),
            "idlist": result.get("idlist", []),
            "querytranslation": result.get("querytranslation"),
        }
        return (
            _safe_projection(projection, projection_stats=stats),
            stats["omitted_fields"],
        )
    if tool_name == "PubMed_search_articles" and isinstance(data, list):
        projection = {
            "records": [_safe_projection(row, projection_stats=stats) for row in data],
            "metadata": _safe_projection(metadata, projection_stats=stats),
        }
        return projection, stats["omitted_fields"]
    projection = {
        "data": _safe_projection(data, projection_stats=stats),
        "metadata": _safe_projection(metadata, projection_stats=stats),
    }
    return projection, stats["omitted_fields"]


def _coverage_for(
    adapter: dict[str, Any], data: Any, metadata: dict[str, Any], state: str
) -> tuple[str, dict[str, Any]]:
    if state == "FAILED":
        return state, {
            "mode": "NOT_APPLICABLE",
            "requested": 0,
            "examined": 0,
            "skipped": 0,
            "failed": 0,
            "reason_codes": ["TOOL_EXECUTION_FAILED"],
        }
    if not adapter["search"]:
        return state, {
            "mode": "NOT_APPLICABLE",
            "requested": 0,
            "examined": 0,
            "skipped": 0,
            "failed": 0,
            "reason_codes": [],
        }
    if isinstance(data, list):
        examined = len(data)
    elif isinstance(data, dict) and isinstance(data.get("esearchresult"), dict):
        examined = len(data["esearchresult"].get("idlist", []))
    elif isinstance(data, dict) and isinstance(data.get("records"), list):
        examined = len(data["records"])
    else:
        examined = 1 if data else 0
    total = None
    nested_search = (
        data.get("esearchresult", {})
        if isinstance(data, dict) and isinstance(data.get("esearchresult"), dict)
        else {}
    )
    for source in (metadata, data if isinstance(data, dict) else {}, nested_search):
        for key in ("total_available", "total_results", "total", "count", "hitCount"):
            candidate = source.get(key) if isinstance(source, dict) else None
            if isinstance(candidate, str) and candidate.isdigit():
                candidate = int(candidate)
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                total = max(examined, candidate)
                break
        if total is not None:
            break
    total_unknown = total is None
    if total_unknown:
        total = examined
    skipped = max(0, total - examined)
    reason_codes = []
    if skipped:
        reason_codes.append("PAGINATED_SOURCE_NOT_EXHAUSTED")
    if total_unknown:
        reason_codes.append("SOURCE_TOTAL_UNKNOWN")
    return ("PARTIAL" if skipped or total_unknown else state), {
        "mode": "QUERY_SLICE" if skipped or total_unknown else "CENSUS",
        "requested": total,
        "examined": examined,
        "skipped": skipped,
        "failed": 0,
        "reason_codes": reason_codes,
    }


def _unknown_lineage(pipeline: str, raw_root: str) -> dict[str, str]:
    return {
        "biological_unit_cluster": "UNKNOWN",
        "event_origin_cluster": "UNKNOWN",
        "material_cluster": "UNKNOWN",
        "library_cluster": "UNKNOWN",
        "instrument_run_cluster": "UNKNOWN",
        "raw_observation_root": raw_root,
        "analysis_pipeline_family": pipeline,
        "adjudication_family": "UNKNOWN",
    }


def _contains_nonempty_key(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            (key in keys and item not in (None, "", [], {})) or _contains_nonempty_key(item, keys)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_nonempty_key(item, keys) for item in value)
    return False


def capture_tooluniverse(config: dict[str, Any]) -> dict[str, Any]:
    config = _validate_capture_config(config)
    tool_name = config["tool_name"]
    adapter = TOOL_ADAPTERS[tool_name]
    tu_path = shutil.which("tu")
    if tu_path is None:
        raise GraceLoopError("ToolUniverse CLI 'tu' is not available")
    version = _tool_version(tu_path)
    argument_bytes = canonical_bytes(config["arguments"])
    try:
        result = _run_bounded_command(
            [tu_path, "run", "--raw", tool_name, argument_bytes.decode("utf-8")],
            timeout=60,
            stdout_limit=MAX_TOOL_OUTPUT_BYTES,
            stderr_limit=MAX_TOOL_ERROR_BYTES,
            environment=os.environ.copy(),
        )
        raw_stdout = result.stdout
        process_failure = result.returncode != 0
    except subprocess.TimeoutExpired as exc:
        raw_stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
        process_failure = True
    if len(raw_stdout) > MAX_TOOL_OUTPUT_BYTES:
        raise GraceLoopError("ToolUniverse response exceeds the capture limit")
    response_sha = sha256_bytes(raw_stdout)
    parsed: Any = None
    if not process_failure:
        try:
            parsed = read_json_bytes(raw_stdout, f"{tool_name} response")
        except GraceLoopError:
            process_failure = True
    if process_failure:
        state = "FAILED"
        data = None
        metadata: dict[str, Any] = {}
        projection = {"failure_code": "TOOL_PROCESS_OR_RESPONSE_FAILURE"}
        omitted_fields = 0
    else:
        state, data, metadata = _extract_data(parsed)
        projection, omitted_fields = (
            _projection_for(tool_name, data, metadata)
            if state != "FAILED"
            else ({"failure_code": "TOOL_REPORTED_FAILURE"}, 0)
        )
    no_result = state != "FAILED" and data in (None, {}, [])
    projection_empty = (
        state != "FAILED"
        and bool(data)
        and isinstance(projection, dict)
        and projection.get("data", projection) in ({}, [])
    )
    state, coverage = _coverage_for(adapter, data, metadata, state)
    if no_result:
        state = "PARTIAL"
        coverage["reason_codes"] = sorted(set(coverage["reason_codes"]) | {"NO_RESULT_IN_RESPONSE"})
    if projection_empty:
        state = "PARTIAL"
        coverage["reason_codes"] = sorted(
            set(coverage["reason_codes"]) | {"PROJECTION_EMPTY_UNREGISTERED_SCHEMA"}
        )
    if omitted_fields:
        state = "PARTIAL"
        coverage["reason_codes"] = sorted(
            set(coverage["reason_codes"]) | {"PROJECTION_SCHEMA_FIELDS_DROPPED"}
        )
    captured_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    capture_source = Path(__file__).resolve(strict=True)
    environment_sha = sha256_bytes(
        canonical_bytes(
            {
                "python": platform.python_version(),
                "tooluniverse": version,
                "system": platform.system(),
                "machine": platform.machine(),
            }
        )
    )
    parameter_lock = sha256_bytes(
        canonical_bytes({"tool_name": tool_name, "arguments": config["arguments"]})
    )
    capabilities = sorted(set(adapter["capabilities"]) | {"QUERY_EXECUTION_METADATA"})
    result_disposition = "TOOL_RESULT_CAPTURED"
    if state == "FAILED":
        capabilities = ["QUERY_EXECUTION_METADATA"]
        result_disposition = "TOOL_EXECUTION_FAILED_NO_RESULT_CAPABILITY"
    elif no_result:
        capabilities = ["QUERY_EXECUTION_METADATA"]
        result_disposition = "NO_RESULT_IN_RESPONSE_NOT_AN_ABSENCE_CLAIM"
    if (
        not no_result
        and state != "FAILED"
        and tool_name == "OMA_resolve_xref"
        and not _contains_nonempty_key(
            projection, {"omaid", "oma_group", "canonical_id", "uniprot_accession"}
        )
    ):
        capabilities = [item for item in capabilities if item != "ORTHOLOGY_PROJECTION"]
        result_disposition = "NO_MAPPING_IN_RETURNED_SLICE_NOT_AN_ABSENCE_CLAIM"
    if (
        not no_result
        and state != "FAILED"
        and tool_name == "InterPro_get_protein_domain_architecture"
        and not _contains_nonempty_key(projection, {"entries", "domains", "interpro", "pfam"})
    ):
        capabilities = [item for item in capabilities if item != "DOMAIN_ANNOTATION"]
        result_disposition = "NO_DOMAIN_MAPPING_IN_RETURNED_SLICE_NOT_AN_ABSENCE_CLAIM"
    prohibitions = [
        "NO_ABSENCE_CLAIM",
        "NO_BIOLOGICAL_CAUSALITY",
        "NO_COORDINATE_EQUIVALENCE",
        "NO_EMPIRICAL_PERFORMANCE",
        "NO_EXPERIMENT_AUTHORITY",
        "NO_FUNCTION_TRANSFER",
        "NO_INDEPENDENCE_CLAIM",
        "NO_TARGET_SELECTION",
    ]
    core = {
        "kind": "SOURCE_SNAPSHOT",
        "producer": {
            "tool": tool_name,
            "version": version,
            "source_sha256": sha256_file(Path(tu_path).resolve(strict=True)),
            "environment_sha256": environment_sha,
            "adapter_id": adapter["adapter_id"],
            "adapter_version": COMPILER_VERSION,
            "adapter_sha256": sha256_file(capture_source),
        },
        "execution": {
            "state": state,
            "parameter_lock_sha256": parameter_lock,
            "inputs": [],
            "outputs": [
                {"role": "tool-response", "sha256": response_sha, "bytes": len(raw_stdout)}
            ],
            "coverage": coverage,
        },
        "subject_alias": config.get("subject_alias"),
        "reference_frame_id": config.get("reference_frame_id"),
        "evidence_family": config["evidence_family"],
        "lineage": _unknown_lineage(f"ToolUniverse-{tool_name}", response_sha),
        "calibration": {
            "state": "NOT_APPLICABLE",
            "certificate_receipt_id": "NONE",
            "domain_digest": "NONE",
        },
        "capabilities": capabilities,
        "prohibitions": prohibitions,
        "payload": {
            "captured_at_utc": captured_at,
            "source": adapter["source"],
            "query": config["arguments"],
            "projection": projection,
            "projection_omitted_field_count": omitted_fields,
            "raw_response_retained": False,
            "raw_response_sha256": response_sha,
            "network_snapshot_reproducible": False,
            "result_disposition": result_disposition,
        },
    }
    return build_receipt(config["receipt_id"], core)


def _read_regular_snapshot(path: Path, label: str) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise GraceLoopError(f"cannot open {label} as a regular snapshot: {exc}") from exc
    try:
        information = os.fstat(descriptor)
        if not stat.S_ISREG(information.st_mode) or information.st_nlink != 1:
            raise GraceLoopError(f"{label} must be a single-link regular file")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_TOOL_OUTPUT_BYTES:
                raise GraceLoopError(f"{label} exceeds the snapshot limit")
            chunks.append(chunk)
        return b"".join(chunks), information
    finally:
        os.close(descriptor)


def _verify_source_manifest(source_root: Path) -> tuple[str, int, dict[str, bytes]]:
    if source_root.is_symlink() or not source_root.is_dir():
        raise GraceLoopError("GraceGraph source root must be a regular directory")
    manifest_path = source_root / "SOURCE_SHA256SUMS.txt"
    raw, _information = _read_regular_snapshot(manifest_path, "GraceGraph source manifest")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise GraceLoopError("GraceGraph source manifest is not UTF-8") from exc
    seen: set[str] = set()
    snapshots: dict[str, bytes] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\r\n]+)", line)
        if match is None:
            raise GraceLoopError("GraceGraph source manifest contains a malformed row")
        expected, locator = match.groups()
        relative = require_relative(locator, "GraceGraph source manifest locator")
        if locator in seen:
            raise GraceLoopError("GraceGraph source manifest contains a duplicate member")
        seen.add(locator)
        candidate = source_root / relative
        try:
            candidate.resolve(strict=True).relative_to(source_root.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise GraceLoopError("GraceGraph source manifest member escapes its root") from exc
        if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_nlink != 1:
            raise GraceLoopError("GraceGraph source manifest member is not a regular file")
        member_raw, _member_information = _read_regular_snapshot(
            candidate, "GraceGraph source member"
        )
        if sha256_bytes(member_raw) != expected:
            raise GraceLoopError("GraceGraph source manifest member checksum mismatch")
        snapshots[locator] = member_raw
    if not seen:
        raise GraceLoopError("GraceGraph source manifest is empty")
    manifest_sha = sha256_bytes(raw)
    if manifest_sha != PINNED_GRACEGRAPH_SOURCE_MANIFEST_SHA256:
        raise GraceLoopError("GraceGraph source manifest is not the registered release")
    actual_source_members: set[str] = set()
    for candidate in source_root.rglob("*"):
        if candidate.is_symlink():
            raise GraceLoopError("GraceGraph source tree contains a symlink")
        if not candidate.is_file():
            continue
        relative_name = candidate.relative_to(source_root).as_posix()
        if relative_name == "SOURCE_SHA256SUMS.txt":
            continue
        if (
            relative_name.startswith(
                (
                    ".git/",
                    ".pytest_cache/",
                    ".ruff_cache/",
                    ".venv/",
                    "build/",
                    "dist/",
                    "src/gracegraph.egg-info/",
                )
            )
            or "/__pycache__/" in f"/{relative_name}"
        ):
            continue
        actual_source_members.add(relative_name)
    if actual_source_members != seen:
        raise GraceLoopError(
            "GraceGraph source tree inventory differs from its registered manifest"
        )
    return manifest_sha, len(raw), snapshots


def _run_json_command(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
    timeout: int = 60,
    cwd: Path | None = None,
) -> tuple[dict[str, Any], bytes]:
    try:
        result = _run_bounded_command(
            command,
            timeout=timeout,
            stdout_limit=MAX_TOOL_OUTPUT_BYTES,
            stderr_limit=MAX_TOOL_ERROR_BYTES,
            environment=environment,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        raise GraceLoopError("registered verifier timed out") from exc
    if result.returncode != 0:
        raise GraceLoopError("registered verifier failed closed")
    if len(result.stdout) > MAX_TOOL_OUTPUT_BYTES:
        raise GraceLoopError("registered verifier output exceeds the limit")
    parsed = read_json_bytes(result.stdout, "registered verifier output")
    if not isinstance(parsed, dict):
        raise GraceLoopError("registered verifier output must be an object")
    return parsed, result.stdout


def capture_gracegraph_capsule(
    capsule_path: Path,
    gracegraph_source_root: Path,
    receipt_id: str,
    evidence_family: str,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Capture a verified GraceGraph capsule without treating a hash as authentication."""

    receipt_id = require_id(receipt_id, "receipt_id")
    evidence_family = require_id(evidence_family, "evidence_family")
    if capsule_path.is_symlink() or not capsule_path.is_dir():
        raise GraceLoopError("GraceGraph capsule must be a regular directory")
    capsule_path = capsule_path.resolve(strict=True)
    gracegraph_source_root = gracegraph_source_root.resolve(strict=True)
    if project_root is not None:
        project_root = project_root.resolve(strict=True)
    source_manifest_sha, source_manifest_bytes, source_snapshots = _verify_source_manifest(
        gracegraph_source_root
    )
    manifest_raw, _ = _read_regular_snapshot(
        capsule_path / "manifest.json", "GraceGraph capsule manifest"
    )
    evaluation_raw, _ = _read_regular_snapshot(
        capsule_path / "evaluation.json", "GraceGraph capsule evaluation"
    )
    manifest = read_json_bytes(manifest_raw, "GraceGraph capsule manifest")
    evaluation = read_json_bytes(evaluation_raw, "GraceGraph capsule evaluation")
    if not isinstance(manifest, dict) or not isinstance(evaluation, dict):
        raise GraceLoopError("GraceGraph capsule metadata must be objects")
    if manifest.get("schema_version") != "gracegraph.manifest.v1":
        raise GraceLoopError("unregistered GraceGraph manifest schema")
    if evaluation.get("schema_version") != "gracegraph.evaluation.v1":
        raise GraceLoopError("unregistered GraceGraph evaluation schema")
    expected_boundary = {
        "biological_gate_closed": False,
        "empirical_n": 0,
        "experiment_authorized": False,
        "release_authorized": False,
        "target_selected": False,
    }
    if not isinstance(evaluation.get("claim_boundary"), dict) or canonical_bytes(
        evaluation["claim_boundary"]
    ) != canonical_bytes(expected_boundary):
        raise GraceLoopError("GraceGraph capsule exceeds the N=0 claim boundary")
    compiler = evaluation.get("compiler")
    if not isinstance(compiler, dict) or compiler.get("name") != "gracegraph":
        raise GraceLoopError("GraceGraph compiler identity is missing")
    version = require_string(compiler.get("version"), "GraceGraph version", max_length=50)
    run_id = evaluation.get("run_id")
    if (
        not isinstance(run_id, str)
        or not re.fullmatch(r"[0-9a-f]{16}", run_id)
        or manifest.get("run_id") != run_id
    ):
        raise GraceLoopError("GraceGraph run identity is incoherent")
    with tempfile.TemporaryDirectory(prefix="graceloop-gracegraph-source-") as stage_name:
        source_stage = Path(stage_name)
        for locator, member_raw in source_snapshots.items():
            destination = source_stage / locator
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(member_raw)
        launch_directory = source_stage / "launch"
        launch_directory.mkdir()
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(source_stage / "src"),
            "PYTHONNOUSERSITE": "1",
            "LANG": "C.UTF-8",
        }
        verification, verification_raw = _run_json_command(
            [sys.executable, "-S", "-m", "gracegraph.cli", "verify", str(capsule_path)],
            environment=environment,
            cwd=launch_directory,
        )
        live: dict[str, Any] | None = None
        if project_root is not None:
            try:
                live, _live_raw = _run_json_command(
                    [
                        sys.executable,
                        "-S",
                        "-m",
                        "gracegraph.cli",
                        "verify",
                        str(capsule_path),
                        "--project-root",
                        str(project_root),
                    ],
                    environment=environment,
                    cwd=launch_directory,
                )
            except GraceLoopError:
                live = None
    if (
        verification.get("status") != "PASS_SEALED_BYTES_ONLY"
        or verification.get("run_id") != run_id
    ):
        raise GraceLoopError("GraceGraph static replay disposition is unexpected")
    live_replay_status = "NOT_REQUESTED"
    verification_status = verification["status"]
    if project_root is not None:
        if (
            live is not None
            and live.get("status") == "PASS_LIVE_REPLAY"
            and live.get("run_id") == run_id
        ):
            live_replay_status = "PASS_DIAGNOSTIC_NOT_PROVENANCE_BOUND"
        elif live is None:
            live_replay_status = "FAILED_CLOSED_DRIFT_OR_UNAVAILABLE"
        else:
            live_replay_status = "FAILED_CLOSED_UNEXPECTED_DISPOSITION"
    manifest_raw_after, _ = _read_regular_snapshot(
        capsule_path / "manifest.json", "GraceGraph capsule manifest"
    )
    evaluation_raw_after, _ = _read_regular_snapshot(
        capsule_path / "evaluation.json", "GraceGraph capsule evaluation"
    )
    if manifest_raw_after != manifest_raw or evaluation_raw_after != evaluation_raw:
        raise GraceLoopError("GraceGraph capsule changed during verification")
    manifest_sha = sha256_bytes(manifest_raw)
    evaluation_sha = sha256_bytes(evaluation_raw)
    verification_sha = sha256_bytes(verification_raw)
    captured_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    adapter_sha = sha256_file(Path(__file__).resolve(strict=True))
    core = {
        "kind": "SOURCE_SNAPSHOT",
        "producer": {
            "tool": "GraceGraph",
            "version": version,
            "source_sha256": source_manifest_sha,
            "environment_sha256": sha256_bytes(
                canonical_bytes(
                    {
                        "python": platform.python_version(),
                        "source_manifest_sha256": source_manifest_sha,
                    }
                )
            ),
            "adapter_id": "LOCAL.GRACEGRAPH_CAPSULE.V1",
            "adapter_version": COMPILER_VERSION,
            "adapter_sha256": adapter_sha,
        },
        "execution": {
            "state": "COMPLETE",
            "parameter_lock_sha256": sha256_bytes(
                canonical_bytes(
                    {
                        "capsule_manifest_sha256": manifest_sha,
                        "source_manifest_sha256": source_manifest_sha,
                        "static_verification_required": True,
                    }
                )
            ),
            "inputs": [
                {
                    "role": "source-manifest",
                    "sha256": source_manifest_sha,
                    "bytes": source_manifest_bytes,
                }
            ],
            "outputs": [
                {"role": "capsule-manifest", "sha256": manifest_sha, "bytes": len(manifest_raw)},
                {"role": "evaluation", "sha256": evaluation_sha, "bytes": len(evaluation_raw)},
                {
                    "role": "static-verification",
                    "sha256": verification_sha,
                    "bytes": len(verification_raw),
                },
            ],
            "coverage": {
                "mode": "NOT_APPLICABLE",
                "requested": 0,
                "examined": 0,
                "skipped": 0,
                "failed": 0,
                "reason_codes": [],
            },
        },
        "subject_alias": {
            "namespace": "GraceGraph",
            "namespace_version": version,
            "alias": run_id,
            "kind": "OTHER",
        },
        "reference_frame_id": None,
        "evidence_family": evidence_family,
        "lineage": _unknown_lineage("GraceGraph-static-replay", manifest_sha),
        "calibration": {
            "state": "NOT_APPLICABLE",
            "certificate_receipt_id": "NONE",
            "domain_digest": "NONE",
        },
        "capabilities": ["DESIGN_STRUCTURE"],
        "prohibitions": [
            "NO_BIOLOGICAL_CAUSALITY",
            "NO_EMPIRICAL_PERFORMANCE",
            "NO_EXPERIMENT_AUTHORITY",
            "NO_INDEPENDENCE_CLAIM",
            "NO_TARGET_SELECTION",
        ],
        "payload": {
            "captured_at_utc": captured_at,
            "capsule_run_id": run_id,
            "capsule_manifest_sha256": manifest_sha,
            "evaluation_sha256": evaluation_sha,
            "verification_status": verification_status,
            "static_verification_status": verification["status"],
            "static_verification_sha256": verification_sha,
            "static_verification_bytes": len(verification_raw),
            "live_replay_status": live_replay_status,
            "claim_boundary": expected_boundary,
            "source_capsule_embedded": False,
        },
    }
    return build_receipt(receipt_id, core)


def _capture_declared_model(
    declaration_path: Path,
    receipt_id: str,
    evidence_family: str,
    *,
    captured_at_utc: str | None = None,
) -> dict[str, Any]:
    """Embed exact qualitative matrices and inspectable protocol locks as a synthetic receipt."""

    receipt_id = require_id(receipt_id, "receipt_id")
    evidence_family = require_id(evidence_family, "evidence_family")
    raw, _ = _read_regular_snapshot(declaration_path, "declared model")
    declaration = read_json_bytes(raw, "declared model")
    if canonical_bytes(declaration) + b"\n" != raw:
        raise GraceLoopError("declared model must be canonical JSON")
    if not isinstance(declaration, dict):
        raise GraceLoopError("declared model must be an object")
    require_only_keys(
        declaration,
        {"schema_version", "decision", "worlds", "gates", "experiments"},
        "declared model",
    )
    if declaration.get("schema_version") != "graceloop.declared-model.v1":
        raise GraceLoopError("unregistered declared-model schema")
    decision = declaration.get("decision")
    worlds = declaration.get("worlds")
    gates = declaration.get("gates")
    experiments = declaration.get("experiments")
    if not isinstance(decision, dict):
        raise GraceLoopError("declared model decision must be an object")
    if not isinstance(worlds, list) or any(not isinstance(item, dict) for item in worlds):
        raise GraceLoopError("declared model worlds must be objects")
    if not isinstance(gates, list) or any(not isinstance(item, dict) for item in gates):
        raise GraceLoopError("declared model gates must be objects")
    if not isinstance(experiments, list) or any(not isinstance(item, dict) for item in experiments):
        raise GraceLoopError("declared model experiments must be objects")
    decision = _validate_decision(decision)
    if any(world.get("source_receipt_ids") not in ([],) for world in worlds):
        raise GraceLoopError("declared-model worlds must remain source-free alternatives")
    worlds = _validate_worlds(worlds, decision, set())
    gates = _validate_gates(gates)
    compiled_experiments: list[dict[str, Any]] = []
    stored_declarations: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    output_descriptors: list[dict[str, Any]] = []
    seen: set[str] = set()
    input_experiment_keys = {
        "id",
        "label",
        "execution_class",
        "reference_frame_ids",
        "requires_gates",
        "outcomes",
        "predictions",
        "resources",
        "rationale_code",
        "protocol_lock",
    }
    for item in experiments:
        require_only_keys(item, input_experiment_keys, "declared model experiment")
        if set(item) != input_experiment_keys:
            raise GraceLoopError("declared model experiment must declare every field")
        experiment_id = require_id(item.get("id"), "declared model experiment.id")
        if experiment_id in seen:
            raise GraceLoopError("declared model contains duplicate experiment ids")
        seen.add(experiment_id)
        protocol_lock = item.get("protocol_lock")
        if not isinstance(protocol_lock, dict):
            raise GraceLoopError("declared model protocol_lock must be an object")
        protocol_bytes = canonical_bytes(protocol_lock)
        protocol_sha = sha256_bytes(protocol_bytes)
        outcomes = item.get("outcomes")
        predictions = item.get("predictions")
        if not isinstance(outcomes, list) or any(not isinstance(row, dict) for row in outcomes):
            raise GraceLoopError("declared model outcomes must be objects")
        if not isinstance(predictions, list) or any(
            not isinstance(row, dict) for row in predictions
        ):
            raise GraceLoopError("declared model predictions must be objects")
        outcomes = sorted(outcomes, key=lambda row: row.get("id", ""))
        class_by_outcome = {
            row.get("id"): row.get("class") for row in outcomes if isinstance(row.get("id"), str)
        }
        compiled_predictions: list[dict[str, Any]] = []
        for row in predictions:
            require_only_keys(
                row, {"world_id", "outcome_id", "relation"}, "declared model prediction"
            )
            if set(row) != {"world_id", "outcome_id", "relation"}:
                raise GraceLoopError("declared model prediction schema is not exact")
            relation = row.get("relation")
            outcome_class = class_by_outcome.get(row.get("outcome_id"))
            sources = (
                [receipt_id]
                if relation in {"PERMITS", "EXCLUDES"}
                and outcome_class
                in {
                    "INFORMATIVE_POSITIVE",
                    "INFORMATIVE_NEGATIVE",
                    "INFORMATIVE_ALTERNATIVE",
                    "OTHER",
                }
                else []
            )
            compiled_predictions.append({**row, "source_receipt_ids": sources})
        compiled_predictions = sorted(
            compiled_predictions,
            key=lambda row: (row.get("outcome_id", ""), row.get("world_id", "")),
        )
        compiled = {
            "id": experiment_id,
            "label": item.get("label"),
            "execution_class": item.get("execution_class"),
            "protocol_sha256": protocol_sha,
            "reference_frame_ids": sorted(item.get("reference_frame_ids", [])),
            "requires_gates": sorted(item.get("requires_gates", [])),
            "outcomes": outcomes,
            "predictions": compiled_predictions,
            "resources": item.get("resources"),
            "rationale_code": item.get("rationale_code"),
        }
        protocol_lock = validate_protocol_lock(protocol_lock, compiled)
        protocol_bytes = canonical_bytes(protocol_lock)
        protocol_sha = sha256_bytes(protocol_bytes)
        compiled["protocol_sha256"] = protocol_sha
        model_bytes = canonical_bytes(prediction_model_core(decision, worlds, gates, compiled))
        model_sha = sha256_bytes(model_bytes)
        compiled["prediction_model_sha256"] = model_sha
        compiled_experiments.append(compiled)
        stored_declarations.append({**compiled, "protocol_lock": protocol_lock})
        bindings.append(
            {
                "experiment_id": experiment_id,
                "protocol_sha256": protocol_sha,
                "prediction_model_sha256": model_sha,
                "reference_frame_ids": compiled["reference_frame_ids"],
            }
        )
        output_descriptors.extend(
            [
                {"role": "protocol-lock", "sha256": protocol_sha, "bytes": len(protocol_bytes)},
                {"role": "prediction-model", "sha256": model_sha, "bytes": len(model_bytes)},
            ]
        )
    if not compiled_experiments:
        raise GraceLoopError("declared model must contain at least one experiment")
    compiled_experiments = sorted(compiled_experiments, key=lambda item: item["id"])
    stored_declarations = sorted(stored_declarations, key=lambda item: item["id"])
    bindings = sorted(bindings, key=lambda item: item["experiment_id"])
    declaration_sha = sha256_bytes(raw)
    adapter_sha = sha256_file(Path(__file__).resolve(strict=True))
    if captured_at_utc is None:
        captured_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", captured_at_utc):
        try:
            datetime.strptime(captured_at_utc, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as exc:
            raise GraceLoopError("captured_at_utc must be a whole-second UTC timestamp") from exc
        captured_at = captured_at_utc
    else:
        raise GraceLoopError("captured_at_utc must be a whole-second UTC timestamp")
    payload = {
        "captured_at_utc": captured_at,
        "source_schema": declaration["schema_version"],
        "source_declaration_sha256": declaration_sha,
        "source_declaration_bytes": len(raw),
        "status": "DECLARED_SYNTHETIC_UNCALIBRATED_UNAUTHENTICATED",
        "decision": decision,
        "worlds": worlds,
        "gates": gates,
        "declared_experiments": stored_declarations,
        "compiled_experiments": compiled_experiments,
        "experiment_bindings": bindings,
    }
    payload_bytes = canonical_bytes(payload)
    output_descriptors.append(
        {
            "role": "compiled-declaration",
            "sha256": sha256_bytes(payload_bytes),
            "bytes": len(payload_bytes),
        }
    )
    core = {
        "kind": "MODEL_PREDICTION",
        "producer": {
            "tool": "GraceLoop declared-model adapter",
            "version": COMPILER_VERSION,
            "source_sha256": adapter_sha,
            "environment_sha256": sha256_bytes(
                canonical_bytes(
                    {"python": platform.python_version(), "schema": declaration["schema_version"]}
                )
            ),
            "adapter_id": "LOCAL.GRACELOOP_DECLARED_MODEL.V1",
            "adapter_version": COMPILER_VERSION,
            "adapter_sha256": adapter_sha,
        },
        "execution": {
            "state": "COMPLETE",
            "parameter_lock_sha256": declaration_sha,
            "inputs": [{"role": "model-declaration", "sha256": declaration_sha, "bytes": len(raw)}],
            "outputs": output_descriptors,
            "coverage": {
                "mode": "NOT_APPLICABLE",
                "requested": 0,
                "examined": 0,
                "skipped": 0,
                "failed": 0,
                "reason_codes": [],
            },
        },
        "subject_alias": {
            "namespace": "GraceLoop",
            "namespace_version": COMPILER_VERSION,
            "alias": receipt_id,
            "kind": "OTHER",
        },
        "reference_frame_id": None,
        "evidence_family": evidence_family,
        "lineage": _unknown_lineage("GraceLoop-declared-model", declaration_sha),
        "calibration": {
            "state": "SYNTHETIC_ONLY",
            "certificate_receipt_id": "NONE",
            "domain_digest": "NONE",
        },
        "capabilities": ["DESIGN_STRUCTURE", "MODEL_PREDICTION"],
        "prohibitions": [
            "NO_BIOLOGICAL_CAUSALITY",
            "NO_EMPIRICAL_PERFORMANCE",
            "NO_EXPERIMENT_AUTHORITY",
            "NO_INDEPENDENCE_CLAIM",
            "NO_TARGET_SELECTION",
        ],
        "payload": payload,
    }
    receipt = build_receipt(receipt_id, core)
    declared_frame_ids = sorted(
        {
            frame_id
            for experiment in compiled_experiments
            for frame_id in experiment["reference_frame_ids"]
        }
    )
    if any(not re.fullmatch(r"frame:[0-9a-f]{64}", item) for item in declared_frame_ids):
        raise GraceLoopError("declared model contains an invalid reference frame id")
    _validate_experiments(
        compiled_experiments,
        decision,
        worlds,
        gates,
        [{"id": item} for item in declared_frame_ids],
        {receipt_id: receipt},
    )
    return receipt


def capture_declared_model(
    declaration_path: Path,
    receipt_id: str,
    evidence_family: str,
    *,
    captured_at_utc: str | None = None,
) -> dict[str, Any]:
    try:
        return _capture_declared_model(
            declaration_path,
            receipt_id,
            evidence_family,
            captured_at_utc=captured_at_utc,
        )
    except GraceLoopError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise GraceLoopError(f"declared model is structurally invalid: {exc}") from exc


def capture_phytoperturb_proof(
    proof_path: Path,
    receipt_id: str,
    evidence_family: str,
    *,
    verifier_path: Path | None = None,
) -> dict[str, Any]:
    receipt_id = require_id(receipt_id, "receipt_id")
    evidence_family = require_id(evidence_family, "evidence_family")
    raw, _proof_information = _read_regular_snapshot(proof_path, "PhytoPerturb proof")
    proof_sha = sha256_bytes(raw)
    if proof_sha != PINNED_PHYTOPERTURB_PROOF_SHA256:
        raise GraceLoopError("PhytoPerturb proof does not match the registered artifact digest")
    proof = read_json_bytes(raw, "PhytoPerturb proof")
    if not isinstance(proof, dict):
        raise GraceLoopError("PhytoPerturb proof must be an object")
    if canonical_bytes(proof) + b"\n" != raw:
        raise GraceLoopError("PhytoPerturb proof must be canonical JSON")
    if proof.get("schema_version") != "phytoperturb.application-proof.v1":
        raise GraceLoopError("unregistered PhytoPerturb proof schema")
    if proof.get("tool_version") != "0.1.0":
        raise GraceLoopError("unregistered PhytoPerturb tool version")
    if proof.get("overall") != "PASS" or proof.get("scientific_disposition") != "NO_RELEASE":
        raise GraceLoopError("PhytoPerturb proof is not a bounded PASS/NO_RELEASE artifact")
    expected_head = require_string(
        proof.get("pinned_phytoresolve_head"), "pinned PhytoResolve head", max_length=64
    )
    if not re.fullmatch(r"[0-9a-f]{64}", expected_head):
        raise GraceLoopError("PhytoPerturb proof has an invalid pinned memory head")
    if expected_head != PINNED_PHYTORESOLVE_HEAD:
        raise GraceLoopError("PhytoPerturb proof is not bound to the registered memory head")
    if verifier_path is None:
        verifier_path = proof_path.parent / "verify_proof.py"
    verifier_raw, _verifier_information = _read_regular_snapshot(
        verifier_path, "PhytoPerturb verifier"
    )
    verifier_sha = sha256_bytes(verifier_raw)
    if verifier_sha != PINNED_PHYTOPERTURB_VERIFIER_SHA256:
        raise GraceLoopError("PhytoPerturb verifier does not match the registered source digest")
    descriptor, snapshot_name = tempfile.mkstemp(prefix="graceloop-phytoperturb-", suffix=".json")
    snapshot = Path(snapshot_name)
    verifier_descriptor, verifier_snapshot_name = tempfile.mkstemp(
        prefix="graceloop-phytoperturb-verifier-", suffix=".py"
    )
    verifier_snapshot = Path(verifier_snapshot_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.fchmod(verifier_descriptor, 0o700)
        with os.fdopen(verifier_descriptor, "wb", closefd=True) as handle:
            handle.write(verifier_raw)
            handle.flush()
            os.fsync(handle.fileno())
        verifier_result, verifier_output_raw = _run_json_command(
            [
                sys.executable,
                "-I",
                "-S",
                str(verifier_snapshot),
                str(snapshot),
                "--expected-head",
                expected_head,
            ]
        )
    finally:
        if snapshot.exists() and snapshot.parent == Path(tempfile.gettempdir()):
            snapshot.unlink()
        if verifier_snapshot.exists() and verifier_snapshot.parent == Path(tempfile.gettempdir()):
            verifier_snapshot.unlink()
    if verifier_result != {
        "valid": True,
        "proof_sha256": proof_sha,
        "pinned_phytoresolve_head": expected_head,
        "scientific_disposition": "NO_RELEASE",
    }:
        raise GraceLoopError("PhytoPerturb verifier result is not exact")
    applications = proof.get("applications")
    if not isinstance(applications, dict) or not isinstance(applications.get("CKX"), dict):
        raise GraceLoopError("PhytoPerturb proof lacks the CKX application")
    ckx = applications["CKX"]
    allowed_ckx = {
        "actionable_narrowing",
        "application",
        "boundary",
        "counts",
        "experiment_authorized",
        "holds",
        "narrowing_registration",
        "scientific_disposition",
        "status",
        "truth_checks",
    }
    projection = {key: ckx[key] for key in sorted(allowed_ckx) if key in ckx}
    if projection.get("experiment_authorized") is not False:
        raise GraceLoopError("PhytoPerturb CKX proof must preserve experiment_authorized=false")
    projection_bytes = canonical_bytes(projection)
    adapter_sha = sha256_file(Path(__file__).resolve(strict=True))
    captured_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    core = {
        "kind": "MODEL_PREDICTION",
        "producer": {
            "tool": "PhytoPerturb",
            "version": "0.1.0",
            "source_sha256": verifier_sha,
            "environment_sha256": sha256_bytes(
                canonical_bytes(
                    {
                        "proof_schema": proof["schema_version"],
                        "pinned_memory_head": proof.get("pinned_phytoresolve_head"),
                        "verifier_sha256": verifier_sha,
                    }
                )
            ),
            "adapter_id": "LOCAL.PHYTOPERTURB_PROOF.V1",
            "adapter_version": COMPILER_VERSION,
            "adapter_sha256": adapter_sha,
        },
        "execution": {
            "state": "COMPLETE",
            "parameter_lock_sha256": sha256_bytes(
                canonical_bytes(
                    {
                        "proof_sha256": proof_sha,
                        "verifier_sha256": verifier_sha,
                        "application": "CKX",
                    }
                )
            ),
            "inputs": [
                {"role": "proof-artifact", "sha256": proof_sha, "bytes": len(raw)},
                {
                    "role": "proof-verifier",
                    "sha256": verifier_sha,
                    "bytes": len(verifier_raw),
                },
            ],
            "outputs": [
                {
                    "role": "ckx-projection",
                    "sha256": sha256_bytes(projection_bytes),
                    "bytes": len(projection_bytes),
                },
                {
                    "role": "verifier-result",
                    "sha256": sha256_bytes(verifier_output_raw),
                    "bytes": len(verifier_output_raw),
                },
            ],
            "coverage": {
                "mode": "NOT_APPLICABLE",
                "requested": 0,
                "examined": 0,
                "skipped": 0,
                "failed": 0,
                "reason_codes": [],
            },
        },
        "subject_alias": {
            "namespace": "MLOG",
            "namespace_version": "v1",
            "alias": "CKX",
            "kind": "OTHER",
        },
        "reference_frame_id": None,
        "evidence_family": evidence_family,
        "lineage": _unknown_lineage("PhytoPerturb-0.1.0", proof_sha),
        "calibration": {
            "state": "SYNTHETIC_ONLY",
            "certificate_receipt_id": "NONE",
            "domain_digest": "NONE",
        },
        "capabilities": ["DESIGN_STRUCTURE", "MODEL_PREDICTION"],
        "prohibitions": [
            "NO_BIOLOGICAL_CAUSALITY",
            "NO_EMPIRICAL_PERFORMANCE",
            "NO_EXPERIMENT_AUTHORITY",
            "NO_INDEPENDENCE_CLAIM",
            "NO_TARGET_SELECTION",
        ],
        "payload": {
            "captured_at_utc": captured_at,
            "source_schema": proof["schema_version"],
            "source_artifact_sha256": proof_sha,
            "verifier_sha256": verifier_sha,
            "verifier_result": verifier_result,
            "projection": projection,
        },
    }
    return build_receipt(receipt_id, core)
