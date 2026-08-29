"""Prior-free counterfactual replay and qualitative Pareto/minimax frontiers."""

from __future__ import annotations

from itertools import combinations
from typing import Any

from .canonical import GraceLoopError, canonical_bytes, sha256_bytes
from .models import (
    COMPILER_VERSION,
    FAIL_CLOSED_OUTCOME_CLASSES,
    SCIENTIFIC_OUTCOME_CLASSES,
    fixed_boundary,
    validate_study,
)
from .receipt import validate_receipt


def _substantive_options(world: dict[str, Any], defer_id: str) -> set[str]:
    return set(world["admissible_options"]) - {defer_id}


def _decision_relevant_pairs(worlds: list[dict[str, Any]], defer_id: str) -> list[tuple[str, str]]:
    result = []
    for left, right in combinations(worlds, 2):
        if _substantive_options(left, defer_id) != _substantive_options(right, defer_id):
            result.append((left["id"], right["id"]))
    return sorted(result)


def _outcome_analysis(
    experiment: dict[str, Any],
    outcome: dict[str, Any],
    active_worlds: list[dict[str, Any]],
    relevant_pairs: list[tuple[str, str]],
    defer_id: str,
) -> dict[str, Any]:
    prediction_map = {
        (item["world_id"], item["outcome_id"]): item for item in experiment["predictions"]
    }
    relations = {
        world["id"]: prediction_map[(world["id"], outcome["id"])]["relation"]
        for world in active_worlds
    }
    predicted_survivors = sorted(
        world_id for world_id, relation in relations.items() if relation != "EXCLUDES"
    )
    model_misspecification = not predicted_survivors
    is_failure = outcome["class"] in FAIL_CLOSED_OUTCOME_CLASSES
    if model_misspecification or is_failure:
        effective_survivors = sorted(world["id"] for world in active_worlds)
    else:
        effective_survivors = predicted_survivors
    world_map = {world["id"]: world for world in active_worlds}
    surviving_worlds = [world_map[identity] for identity in effective_survivors]
    admissible_sets = [set(world["admissible_options"]) for world in surviving_worlds]
    safe_options = sorted(set.intersection(*admissible_sets)) if admissible_sets else [defer_id]
    possible_options = sorted(set.union(*admissible_sets)) if admissible_sets else [defer_id]
    safe_substantive = sorted(set(safe_options) - {defer_id})
    possible_substantive = sorted(set(possible_options) - {defer_id})
    unknown_survivors = sorted(
        identity for identity in effective_survivors if relations.get(identity) == "UNKNOWN"
    )
    if is_failure:
        resolution = "FAIL_CLOSED_NO_UPDATE"
    elif model_misspecification:
        resolution = "MODEL_MISSPECIFICATION_NO_UPDATE"
    elif unknown_survivors:
        resolution = "UNRESOLVED_UNKNOWN_RELATION"
    elif len(safe_substantive) == 1:
        resolution = "RESOLVES_DECLARED_DECISION_CONDITIONALLY"
    else:
        resolution = "UNRESOLVED_MULTIPLE_OPTIONS"

    separated_pairs = []
    for left, right in relevant_pairs:
        relation_pair = {relations[left], relations[right]}
        if relation_pair == {"PERMITS", "EXCLUDES"}:
            separated_pairs.append([left, right])
    sources = sorted(
        {
            source
            for world in active_worlds
            for source in prediction_map[(world["id"], outcome["id"])]["source_receipt_ids"]
        }
    )
    return {
        "id": outcome["id"],
        "label": outcome["label"],
        "class": outcome["class"],
        "relations": relations,
        "predicted_surviving_worlds": predicted_survivors,
        "effective_surviving_worlds": effective_survivors,
        "unknown_surviving_worlds": unknown_survivors,
        "model_misspecification": model_misspecification,
        "safe_options": safe_options,
        "possible_options": possible_options,
        "safe_substantive_options": safe_substantive,
        "possible_substantive_options": possible_substantive,
        "remaining_substantive_option_count": len(possible_substantive),
        "resolution": resolution,
        "separated_decision_pairs": separated_pairs,
        "source_receipt_ids": sources,
    }


def _experiment_analysis(
    experiment: dict[str, Any],
    study: dict[str, Any],
    receipts: dict[str, dict[str, Any]],
    active_worlds: list[dict[str, Any]],
    relevant_pairs: list[tuple[str, str]],
) -> dict[str, Any]:
    decision = study["decision"]
    defer_id = decision["defer_option_id"]
    outcomes = [
        _outcome_analysis(experiment, outcome, active_worlds, relevant_pairs, defer_id)
        for outcome in experiment["outcomes"]
    ]
    scientific = [item for item in outcomes if item["class"] in SCIENTIFIC_OUTCOME_CLASSES]
    failure = [item for item in outcomes if item["class"] in FAIL_CLOSED_OUTCOME_CLASSES]
    baseline_options = sorted(
        {option for world in active_worlds for option in _substantive_options(world, defer_id)}
    )
    worst_remaining = max(
        [item["remaining_substantive_option_count"] for item in scientific]
        or [len(baseline_options)]
    )
    conditional_gain = max(0, len(baseline_options) - worst_remaining)
    possible_pairs = {
        tuple(pair) for outcome in scientific for pair in outcome["separated_decision_pairs"]
    }
    guaranteed_pairs: set[tuple[str, str]] = set(relevant_pairs)
    for outcome in scientific:
        guaranteed_pairs &= {tuple(pair) for pair in outcome["separated_decision_pairs"]}
    all_resolve = bool(scientific) and all(
        item["resolution"] == "RESOLVES_DECLARED_DECISION_CONDITIONALLY" for item in scientific
    )
    model_misspecification_outcomes = sorted(
        item["id"] for item in scientific if item["model_misspecification"]
    )
    gate_map = {gate["id"]: gate for gate in study["gates"]}
    frame_map = {frame["id"]: frame for frame in study["reference_frames"]}
    blockers = [
        f"OPEN_GATE:{gate_id}"
        for gate_id in experiment["requires_gates"]
        if gate_map[gate_id]["state"] == "OPEN"
    ]
    if experiment["execution_class"] != "READ_ONLY_COMPUTATION":
        blockers.append("ALPHA_EXPERIMENT_AUTHORIZATION_FALSE")
    for frame_id in experiment["reference_frame_ids"]:
        if frame_map[frame_id]["content_binding"]["mode"] == "UNAVAILABLE":
            blockers.append(f"REFERENCE_FRAME_CONTENT_UNBOUND:{frame_id}")
    cited_receipts = sorted(
        {source for outcome in scientific for source in outcome["source_receipt_ids"]}
    )
    if experiment["reference_frame_ids"]:
        blockers.extend(
            f"PREDICTION_RECEIPT_FRAME_UNBOUND:{identity}"
            for identity in cited_receipts
            if receipts[identity]["core"]["reference_frame_id"] is None
        )
    blockers.extend(
        f"PREDICTION_RECEIPT_PARTIAL:{identity}"
        for identity in cited_receipts
        if receipts[identity]["core"]["execution"]["state"] == "PARTIAL"
    )
    blockers = sorted(set(blockers))
    status = "READY_READ_ONLY" if not blockers else "BLOCKED"
    cited_families = sorted(
        {receipts[identity]["core"]["evidence_family"] for identity in cited_receipts}
    )
    cited_execution_states = {
        state: sum(
            receipts[identity]["core"]["execution"]["state"] == state for identity in cited_receipts
        )
        for state in ("COMPLETE", "PARTIAL", "FAILED", "NOT_RUN")
    }
    return {
        "id": experiment["id"],
        "label": experiment["label"],
        "execution_class": experiment["execution_class"],
        "rationale_code": experiment["rationale_code"],
        "protocol_sha256": experiment["protocol_sha256"],
        "prediction_model_sha256": experiment["prediction_model_sha256"],
        "reference_frame_ids": experiment["reference_frame_ids"],
        "requires_gates": experiment["requires_gates"],
        "resources": experiment["resources"],
        "current_status": status,
        "blocked_reasons": blockers,
        "baseline_substantive_options": baseline_options,
        "baseline_substantive_option_count": len(baseline_options),
        "conditional_worst_remaining_option_count": worst_remaining,
        "conditional_minimax_option_gain": conditional_gain,
        "decision_relevant_pair_count": len(relevant_pairs),
        "conditional_guaranteed_pairs": [list(item) for item in sorted(guaranteed_pairs)],
        "conditional_guaranteed_pair_count": len(guaranteed_pairs),
        "conditional_possible_pairs": [list(item) for item in sorted(possible_pairs)],
        "conditional_possible_pair_count": len(possible_pairs),
        "all_declared_informative_outcomes_resolve": all_resolve,
        "model_misspecification_outcomes": model_misspecification_outcomes,
        "decision_separating": bool(conditional_gain or possible_pairs),
        "failure_branches_preserve_all_active_worlds": all(
            item["effective_surviving_worlds"] == sorted(world["id"] for world in active_worlds)
            and item["resolution"] == "FAIL_CLOSED_NO_UPDATE"
            for item in failure
        ),
        "prediction_basis": {
            "status": "DECLARED_COUNTERFACTUAL_MODEL_NOT_EMPIRICAL_EVIDENCE",
            "receipt_ids": cited_receipts,
            "receipt_count": len(cited_receipts),
            "evidence_families": cited_families,
            "evidence_family_count": len(cited_families),
            "execution_states": cited_execution_states,
            "independence_claimed": False,
        },
        "outcomes": outcomes,
    }


def _known_resource_tuple(item: dict[str, Any]) -> tuple[int, ...] | None:
    fields = ("duration_days", "sample_units", "relative_cost", "material_risk", "irreversibility")
    values = tuple(item["resources"][field] for field in fields)
    if any(value == "UNKNOWN" for value in values):
        return None
    return values  # type: ignore[return-value]


def _dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_resources = _known_resource_tuple(left)
    right_resources = _known_resource_tuple(right)
    if left_resources is None or right_resources is None:
        return False
    left_max = (
        left["conditional_minimax_option_gain"],
        int(left["all_declared_informative_outcomes_resolve"]),
        left["conditional_guaranteed_pair_count"],
        left["conditional_possible_pair_count"],
    )
    right_max = (
        right["conditional_minimax_option_gain"],
        int(right["all_declared_informative_outcomes_resolve"]),
        right["conditional_guaranteed_pair_count"],
        right["conditional_possible_pair_count"],
    )
    left_min = (left["conditional_worst_remaining_option_count"], *left_resources)
    right_min = (right["conditional_worst_remaining_option_count"], *right_resources)
    no_worse = all(a >= b for a, b in zip(left_max, right_max, strict=True)) and all(
        a <= b for a, b in zip(left_min, right_min, strict=True)
    )
    strictly_better = any(a > b for a, b in zip(left_max, right_max, strict=True)) or any(
        a < b for a, b in zip(left_min, right_min, strict=True)
    )
    return no_worse and strictly_better


def _pareto(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frontier = []
    for candidate in candidates:
        if not any(
            _dominates(other, candidate) for other in candidates if other["id"] != candidate["id"]
        ):
            frontier.append(candidate)
    return sorted(frontier, key=lambda item: item["id"])


def _minimax(frontier: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not frontier:
        return None

    def key(item: dict[str, Any]) -> tuple[Any, ...]:
        return (
            item["conditional_worst_remaining_option_count"],
            -int(item["all_declared_informative_outcomes_resolve"]),
            -item["conditional_guaranteed_pair_count"],
            -item["conditional_possible_pair_count"],
        )

    best_key = min(key(item) for item in frontier)
    tied = sorted((item for item in frontier if key(item) == best_key), key=lambda item: item["id"])
    selected = tied[0]
    return {
        "experiment_id": selected["id"],
        "policy": "EPISTEMIC_MINIMAX_WITHIN_PARETO_RESOURCES_REMAIN_PARETO",
        "co_minimax_experiment_ids": [item["id"] for item in tied],
        "display_tie_breaker": "LEXICOGRAPHIC_EXPERIMENT_ID_NOT_SCIENTIFIC_PREFERENCE",
        "conditional_worst_remaining_option_count": selected[
            "conditional_worst_remaining_option_count"
        ],
        "all_declared_informative_outcomes_resolve": selected[
            "all_declared_informative_outcomes_resolve"
        ],
        "conditional_guaranteed_pair_count": selected["conditional_guaranteed_pair_count"],
        "conditional_possible_pair_count": selected["conditional_possible_pair_count"],
        "resources": selected["resources"],
    }


def _receipt_summary(receipts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    kinds: dict[str, int] = {}
    states: dict[str, int] = {}
    families: set[str] = set()
    for receipt in receipts.values():
        core = receipt["core"]
        kinds[core["kind"]] = kinds.get(core["kind"], 0) + 1
        state = core["execution"]["state"]
        states[state] = states.get(state, 0) + 1
        families.add(core["evidence_family"])
    return {
        "total": len(receipts),
        "kinds": dict(sorted(kinds.items())),
        "execution_states": dict(sorted(states.items())),
        "evidence_family_count": len(families),
        "evidence_families": sorted(families),
        "authenticated_receipts": 0,
        "authentication_status": "SELF_CONSISTENT_UNAUTHENTICATED",
        "empirical_n_contribution": 0,
        "independence_claimed": False,
    }


def analyze_study(
    study: dict[str, Any],
    receipts: dict[str, dict[str, Any]],
    active_world_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Analyze a validated study without priors, likelihoods, or scalar evidence scores."""

    normalized_receipts: dict[str, dict[str, Any]] = {}
    if not isinstance(receipts, dict):
        raise GraceLoopError("receipts must be an id-keyed object")
    for identity, candidate in receipts.items():
        receipt = validate_receipt(candidate)
        if identity != receipt["receipt_id"]:
            raise GraceLoopError("receipt map key does not match receipt_id")
        normalized_receipts[identity] = receipt
    receipts = normalized_receipts
    study = validate_study(study, receipts)

    world_map = {world["id"]: world for world in study["worlds"]}
    if active_world_ids is None:
        active_world_ids = sorted(world_map)
        mode = "BASELINE"
    else:
        if not active_world_ids or len(active_world_ids) != len(set(active_world_ids)):
            raise GraceLoopError("counterfactual active world set must be nonempty and unique")
        if not set(active_world_ids) <= set(world_map):
            raise GraceLoopError("counterfactual references an unknown world")
        active_world_ids = sorted(active_world_ids)
        mode = "COUNTERFACTUAL_BRANCH"
    active_worlds = [world_map[identity] for identity in active_world_ids]
    defer_id = study["decision"]["defer_option_id"]
    relevant_pairs = _decision_relevant_pairs(active_worlds, defer_id)
    experiments = [
        _experiment_analysis(experiment, study, receipts, active_worlds, relevant_pairs)
        for experiment in study["experiments"]
    ]
    separating = [item for item in experiments if item["decision_separating"]]
    currently_admissible = _pareto(
        [item for item in separating if item["current_status"] == "READY_READ_ONLY"]
    )
    conditional_scientific = _pareto(separating)
    frame_audit = []
    for frame in study["reference_frames"]:
        binding = frame["content_binding"]
        frame_audit.append(
            {
                "id": frame["id"],
                "kind": frame["kind"],
                "binding_mode": binding["mode"],
                "accession_version": binding.get("accession_version"),
                "comparison_status": (
                    "CONTENT_BOUND"
                    if binding["mode"] != "UNAVAILABLE"
                    else "UNBOUND_METADATA_LABEL_ONLY"
                ),
            }
        )
    base_diagnostic = None
    if study["base_capsule"] is not None:
        base_receipt_id = study["base_capsule"]["receipt_id"]
        base_payload = receipts[base_receipt_id]["core"]["payload"]
        base_diagnostic = {
            "receipt_id": base_receipt_id,
            "verification_status": base_payload["verification_status"],
            "static_verification_status": base_payload["static_verification_status"],
            "live_replay_status": base_payload["live_replay_status"],
            "source_capsule_embedded": base_payload["source_capsule_embedded"],
        }
    analysis_core = {
        "schema_version": "graceloop.analysis.v1",
        "compiler": {"name": "graceloop", "version": COMPILER_VERSION},
        "analysis_mode": mode,
        "study_id": study["study_id"],
        "study_sha256": sha256_bytes(canonical_bytes(study)),
        "receipt_core_sha256s": {
            identity: receipts[identity]["core_sha256"] for identity in sorted(receipts)
        },
        "boundary": fixed_boundary(),
        "scientific_status": "PLAN_ONLY_NO_EMPIRICAL_EVIDENCE",
        "verification_scope": "COUNTERFACTUAL_MODEL_AND_RECEIPT_STRUCTURE_ONLY",
        "active_world_ids": active_world_ids,
        "world_status": [
            {
                "id": world["id"],
                "status": "VIABLE_UNTESTED",
                "open_world_residual": world["open_world_residual"],
                "admissible_options": world["admissible_options"],
            }
            for world in active_worlds
        ],
        "decision": study["decision"],
        "decision_relevant_pairs": [list(item) for item in relevant_pairs],
        "receipt_summary": _receipt_summary(receipts),
        "base_capsule_diagnostic": base_diagnostic,
        "reference_frame_audit": frame_audit,
        "experiments": experiments,
        "frontiers": {
            "currently_admissible": [item["id"] for item in currently_admissible],
            "conditional_scientific": [item["id"] for item in conditional_scientific],
        },
        "minimax": {
            "currently_admissible": _minimax(currently_admissible),
            "conditional_scientific": _minimax(conditional_scientific),
        },
        "selection_policy": {
            "probabilities_used": False,
            "priors_used": False,
            "likelihoods_used": False,
            "scalar_score_used": False,
            "pareto_objectives": {
                "maximize": [
                    "conditional_minimax_option_gain",
                    "all_declared_informative_outcomes_resolve",
                    "conditional_guaranteed_pair_count",
                    "conditional_possible_pair_count",
                ],
                "minimize": [
                    "conditional_worst_remaining_option_count",
                    "duration_days",
                    "sample_units",
                    "relative_cost",
                    "material_risk",
                    "irreversibility",
                ],
            },
            "unknown_resources": "INCOMPARABLE_NOT_ZERO",
            "resource_status": "DECLARED_UNAUTHENTICATED_NOT_EMPIRICALLY_VALIDATED",
            "prediction_status": "DECLARED_UNAUTHENTICATED_NOT_EMPIRICALLY_VALIDATED",
        },
        "nonclaims": study["nonclaims"],
    }
    digest = sha256_bytes(canonical_bytes(analysis_core))
    return {**analysis_core, "analysis_sha256": digest, "run_id": digest}


def explain_experiment(analysis: dict[str, Any], experiment_id: str) -> dict[str, Any]:
    experiments = {item["id"]: item for item in analysis["experiments"]}
    if experiment_id not in experiments:
        raise GraceLoopError(f"unknown experiment: {experiment_id}")
    item = experiments[experiment_id]
    memberships = {
        name: experiment_id in members for name, members in analysis["frontiers"].items()
    }
    return {
        "schema_version": "graceloop.explanation.v1",
        "run_id": analysis["run_id"],
        "verification_scope": analysis["verification_scope"],
        "experiment": item,
        "frontier_membership": memberships,
        "boundary": analysis["boundary"],
    }


def simulate_outcome(
    study: dict[str, Any],
    receipts: dict[str, dict[str, Any]],
    experiment_id: str,
    outcome_id: str,
    active_world_ids: list[str] | None = None,
) -> dict[str, Any]:
    baseline = analyze_study(study, receipts, active_world_ids)
    experiments = {item["id"]: item for item in baseline["experiments"]}
    if experiment_id not in experiments:
        raise GraceLoopError(f"unknown experiment: {experiment_id}")
    outcomes = {item["id"]: item for item in experiments[experiment_id]["outcomes"]}
    if outcome_id not in outcomes:
        raise GraceLoopError(f"unknown outcome for {experiment_id}: {outcome_id}")
    outcome = outcomes[outcome_id]
    successors = outcome["effective_surviving_worlds"]
    successor = analyze_study(study, receipts, successors)
    return {
        "schema_version": "graceloop.counterfactual-branch.v1",
        "status": "COUNTERFACTUAL_ONLY_NOT_AN_OBSERVATION",
        "boundary": fixed_boundary(),
        "predecessor_run_id": baseline["run_id"],
        "assumed_experiment_id": experiment_id,
        "assumed_outcome_id": outcome_id,
        "outcome_effect": outcome,
        "successor_analysis": successor,
    }
