"""GraceLoop public package boundary."""

from .frontier import analyze_study
from .models import COMPILER_VERSION, STUDY_SCHEMA, load_study
from .receipt import RECEIPT_SCHEMA, validate_receipt

__all__ = [
    "COMPILER_VERSION",
    "RECEIPT_SCHEMA",
    "STUDY_SCHEMA",
    "analyze_study",
    "load_study",
    "validate_receipt",
]

__version__ = COMPILER_VERSION
