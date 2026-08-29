"""Shared builders for GraceLoop's adversarial CKX tests.

The tests deliberately enter through the production declared-model adapter.  This
keeps every fixture bound by the same protocol, matrix, receipt, and study checks
as a real compilation rather than constructing privileged in-memory objects.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PACKAGE_ROOT / "src"
CKX_BUILDER_PATH = PACKAGE_ROOT / "examples" / "ckx" / "build_fixture.py"

if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from graceloop.canonical import write_canonical
from graceloop.capture import capture_declared_model

MODEL_RECEIPT_ID = "R_CKX_DECLARED_MODEL"
MODEL_EVIDENCE_FAMILY = "GRACELOOP_DECLARED_CKX_MODEL_20260828"


@dataclass(frozen=True)
class GraceLoopCase:
    """A complete, validation-ready study with its id-keyed receipt map."""

    study: dict[str, Any]
    receipts: dict[str, dict[str, Any]]
    declaration: dict[str, Any]


def _load_ckx_builder() -> Any:
    spec = importlib.util.spec_from_file_location("graceloop_ckx_fixture", CKX_BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the CKX fixture builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def ckx_builder() -> Any:
    return _load_ckx_builder()


@pytest.fixture
def case_factory(
    tmp_path: Path,
    ckx_builder: Any,
) -> Callable[[dict[str, Any] | None], GraceLoopCase]:
    counter = 0

    def build(declaration: dict[str, Any] | None = None) -> GraceLoopCase:
        nonlocal counter
        counter += 1
        source = deepcopy(declaration if declaration is not None else ckx_builder.declaration())
        declaration_path = tmp_path / f"declared-model-{counter}.json"
        write_canonical(declaration_path, source)
        receipt = capture_declared_model(
            declaration_path,
            MODEL_RECEIPT_ID,
            MODEL_EVIDENCE_FAMILY,
        )
        study = ckx_builder.build_study(receipt)

        # The full demonstration adds live ToolUniverse and legacy capsule context.
        # Frontier correctness itself needs only the receipt that binds every
        # declared matrix, so unit tests use this minimal exact inventory.
        study["base_capsule"] = None
        study["receipt_files"] = [f"receipts/{MODEL_RECEIPT_ID}.json"]
        study["context_receipt_ids"] = [MODEL_RECEIPT_ID]
        return GraceLoopCase(
            study=study,
            receipts={MODEL_RECEIPT_ID: receipt},
            declaration=source,
        )

    return build


@pytest.fixture
def ckx_case(case_factory: Callable[[dict[str, Any] | None], GraceLoopCase]) -> GraceLoopCase:
    return case_factory()


@pytest.fixture
def capsule_source(tmp_path: Path, ckx_case: GraceLoopCase) -> Path:
    root = tmp_path / "source"
    (root / "receipts").mkdir(parents=True)
    write_canonical(root / "study.json", ckx_case.study)
    write_canonical(
        root / "receipts" / f"{MODEL_RECEIPT_ID}.json",
        ckx_case.receipts[MODEL_RECEIPT_ID],
    )
    return root / "study.json"
