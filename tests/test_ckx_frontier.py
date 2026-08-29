"""Acceptance and branch-semantics tests for the CKX GraceLoop fixture."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from conftest import GraceLoopCase

from graceloop.frontier import analyze_study, simulate_outcome

ALL_SIX = "E_ALL_SIX_IDENTITY_EXPRESSION"
ALL_WORLD_IDS = ["W_CKX2_ONLY", "W_CKX3_ONLY", "W_COMBINED", "W_OTHER"]
FAILURE_CLASSES = {"NO_CALL", "QC_FAILED", "CONTRADICTORY", "UNEXPECTED"}
SCIENTIFIC_CLASSES = {
    "INFORMATIVE_POSITIVE",
    "INFORMATIVE_NEGATIVE",
    "INFORMATIVE_ALTERNATIVE",
    "OTHER",
}


def _experiment(analysis: dict[str, Any], experiment_id: str) -> dict[str, Any]:
    return next(item for item in analysis["experiments"] if item["id"] == experiment_id)


def test_ckx_acceptance_frontier_is_exact_and_prior_free(ckx_case: GraceLoopCase) -> None:
    analysis = analyze_study(ckx_case.study, ckx_case.receipts)

    assert analysis["frontiers"] == {
        "currently_admissible": [],
        "conditional_scientific": [ALL_SIX],
    }
    assert analysis["minimax"]["currently_admissible"] is None
    assert analysis["minimax"]["conditional_scientific"] == {
        "experiment_id": ALL_SIX,
        "policy": "EPISTEMIC_MINIMAX_WITHIN_PARETO_RESOURCES_REMAIN_PARETO",
        "co_minimax_experiment_ids": [ALL_SIX],
        "display_tie_breaker": "LEXICOGRAPHIC_EXPERIMENT_ID_NOT_SCIENTIFIC_PREFERENCE",
        "conditional_worst_remaining_option_count": 1,
        "all_declared_informative_outcomes_resolve": True,
        "conditional_guaranteed_pair_count": 0,
        "conditional_possible_pair_count": 6,
        "resources": {
            "duration_days": "UNKNOWN",
            "irreversibility": 0,
            "material_risk": 1,
            "relative_cost": 4,
            "sample_units": "UNKNOWN",
        },
    }
    assert len(analysis["decision_relevant_pairs"]) == 6
    assert analysis["selection_policy"]["probabilities_used"] is False
    assert analysis["selection_policy"]["priors_used"] is False
    assert analysis["selection_policy"]["likelihoods_used"] is False
    assert analysis["selection_policy"]["scalar_score_used"] is False


def test_all_six_has_expected_conditional_discrimination(ckx_case: GraceLoopCase) -> None:
    experiment = _experiment(analyze_study(ckx_case.study, ckx_case.receipts), ALL_SIX)

    assert experiment["current_status"] == "BLOCKED"
    assert "ALPHA_EXPERIMENT_AUTHORIZATION_FALSE" in experiment["blocked_reasons"]
    assert experiment["conditional_worst_remaining_option_count"] == 1
    assert experiment["conditional_minimax_option_gain"] == 3
    assert experiment["conditional_possible_pair_count"] == 6
    assert experiment["conditional_guaranteed_pair_count"] == 0
    assert experiment["all_declared_informative_outcomes_resolve"] is True
    assert experiment["failure_branches_preserve_all_active_worlds"] is True

    scientific = [item for item in experiment["outcomes"] if item["class"] in SCIENTIFIC_CLASSES]
    assert {item["resolution"] for item in scientific} == {
        "RESOLVES_DECLARED_DECISION_CONDITIONALLY"
    }
    assert all(item["remaining_substantive_option_count"] == 1 for item in scientific)


def test_unknown_relations_never_count_as_pair_separation(ckx_case: GraceLoopCase) -> None:
    analysis = analyze_study(ckx_case.study, ckx_case.receipts)
    for experiment_id in (
        "E_REPEAT_CORRECTED_TREE",
        "E_CROSS_SPECIES_MICROSYNTENY",
        "E_PREMATURE_SINGLE_CKX3",
        "E_CONDITIONAL_CKX2_CKX3_PAIR_SCREEN",
    ):
        experiment = _experiment(analysis, experiment_id)
        assert experiment["conditional_possible_pair_count"] == 0
        for outcome in experiment["outcomes"]:
            assert outcome["separated_decision_pairs"] == []


def test_failure_branch_preserves_every_world_and_never_updates(
    ckx_case: GraceLoopCase,
) -> None:
    analysis = analyze_study(ckx_case.study, ckx_case.receipts)
    experiment = _experiment(analysis, ALL_SIX)
    failures = [item for item in experiment["outcomes"] if item["class"] in FAILURE_CLASSES]

    assert len(failures) == 4
    for failure in failures:
        assert failure["predicted_surviving_worlds"] == ALL_WORLD_IDS
        assert failure["effective_surviving_worlds"] == ALL_WORLD_IDS
        assert failure["resolution"] == "FAIL_CLOSED_NO_UPDATE"
        assert failure["source_receipt_ids"] == []

    branch = simulate_outcome(
        ckx_case.study,
        ckx_case.receipts,
        ALL_SIX,
        "O_QC_FAILED",
    )
    assert branch["status"] == "COUNTERFACTUAL_ONLY_NOT_AN_OBSERVATION"
    assert branch["outcome_effect"]["effective_surviving_worlds"] == ALL_WORLD_IDS
    assert branch["successor_analysis"]["active_world_ids"] == ALL_WORLD_IDS


def test_model_misspecification_branch_preserves_every_world(
    case_factory: Callable[[dict[str, Any] | None], GraceLoopCase],
    ckx_case: GraceLoopCase,
) -> None:
    declaration = deepcopy(ckx_case.declaration)
    experiment = next(item for item in declaration["experiments"] if item["id"] == ALL_SIX)
    for prediction in experiment["predictions"]:
        if prediction["outcome_id"] == "O_POSITIVE":
            prediction["relation"] = "EXCLUDES"
        elif prediction["world_id"] == "W_CKX2_ONLY" and prediction["outcome_id"] == "O_NEGATIVE":
            # Model validation correctly requires every world to permit at least
            # one scientific branch. Preserve that invariant while making the
            # positive branch itself a complete declared-model misspecification.
            prediction["relation"] = "PERMITS"

    altered = case_factory(declaration)
    analysis = analyze_study(altered.study, altered.receipts)
    outcome = next(
        item for item in _experiment(analysis, ALL_SIX)["outcomes"] if item["id"] == "O_POSITIVE"
    )

    assert outcome["predicted_surviving_worlds"] == []
    assert outcome["effective_surviving_worlds"] == ALL_WORLD_IDS
    assert outcome["model_misspecification"] is True
    assert outcome["resolution"] == "MODEL_MISSPECIFICATION_NO_UPDATE"
