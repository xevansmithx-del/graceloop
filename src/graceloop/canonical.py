"""Strict JSON, hashing, path, privacy, and atomic-publication helpers."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 256
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{0,127}$")
ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
PRIVATE_TEXT_PATTERNS = (
    re.compile(
        r"(?:^|[\s\"'(=])/(?:Users|home|Volumes|private|tmp|var|etc|opt|usr|root|proc|sys|dev|mnt)/"
    ),
    re.compile(r"\bfile://", re.IGNORECASE),
    re.compile(r"(?:^|[\s\"'(=])[A-Za-z]:[\\/]"),
    re.compile(r"(?:^|[\s\"'(=])~/"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp_|github_pat_|sk-proj-|xox[baprs]-)[A-Za-z0-9_-]{8,}"),
)
SEQUENCE_LIKE_RE = re.compile(r"(?:[ACGTUNacgtun][\s]*){80,}")
IUPAC_SEQUENCE_LIKE_RE = re.compile(r"(?:[ACGTRYSWKMBDHVNacgtryswkmbdhvn][\s]*){80,}")
UPPERCASE_PROTEIN_LIKE_RE = re.compile(r"[ACDEFGHIKLMNPQRSTVWYBXZJUO]{80,}", re.IGNORECASE)
SEQUENCE_FIELD_KEYS = {
    "sequence",
    "dna_sequence",
    "rna_sequence",
    "protein_sequence",
    "amino_acid_sequence",
    "fasta",
    "fastq",
}


class GraceLoopError(ValueError):
    """A fail-closed GraceLoop validation error."""


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GraceLoopError(f"value is not canonical JSON: {exc}") from exc


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise GraceLoopError(f"cannot hash {path.name}: {exc}") from exc
    return digest.hexdigest()


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GraceLoopError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _bounded_json_integer(value: str) -> int:
    digits = value.removeprefix("-")
    if len(digits) > 128:
        raise GraceLoopError("JSON integer exceeds the 128-digit lexical limit")
    return int(value)


def _reject_json_constant(value: str) -> Any:
    raise GraceLoopError(f"non-finite JSON constant is forbidden: {value}")


def _reject_excessive_depth(value: Any) -> None:
    stack = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise GraceLoopError(f"cannot parse JSON: nesting exceeds {MAX_JSON_DEPTH} levels")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def read_json_bytes(raw: bytes, label: str = "JSON") -> Any:
    if len(raw) > MAX_JSON_BYTES:
        raise GraceLoopError(f"{label} exceeds {MAX_JSON_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicates,
            parse_int=_bounded_json_integer,
            parse_constant=_reject_json_constant,
        )
        _reject_excessive_depth(value)
        return value
    except GraceLoopError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise GraceLoopError(f"cannot parse {label}: {exc}") from exc


def read_json(path: Path) -> Any:
    try:
        with path.open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            if size > MAX_JSON_BYTES:
                raise GraceLoopError(f"{path.name} exceeds {MAX_JSON_BYTES} bytes")
            raw = handle.read(MAX_JSON_BYTES + 1)
    except OSError as exc:
        raise GraceLoopError(f"cannot read {path.name}: {exc}") from exc
    return read_json_bytes(raw, path.name)


def write_canonical(path: Path, value: Any) -> None:
    path.write_bytes(canonical_bytes(value) + b"\n")


def atomic_write_canonical(path: Path, value: Any) -> None:
    """Create one canonical JSON file without overwriting an existing target."""

    if path.exists() or path.is_symlink():
        raise GraceLoopError(f"refusing to overwrite destination: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    parent = path.parent.resolve(strict=True)
    target = parent / path.name
    fd, stage_name = tempfile.mkstemp(prefix=f".{target.name}.stage-", dir=target.parent)
    stage = Path(stage_name)
    try:
        os.fchmod(fd, 0o600)
        payload = canonical_bytes(value) + b"\n"
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # Linking within one directory gives us an atomic no-clobber publication:
        # unlike rename(2), it cannot replace a target created by a racing writer.
        os.link(stage, target)
        stage.unlink()
        parent_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        if stage.exists() and stage.parent == target.parent:
            stage.unlink()
        raise


def require_only_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise GraceLoopError(f"{field} contains unknown field(s): {unknown}")


def require_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise GraceLoopError(f"{field} must be a stable identifier")
    return value


def require_alias(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ALIAS_RE.fullmatch(value):
        raise GraceLoopError(f"{field} must be a bounded namespace-local alias")
    return value


def require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise GraceLoopError(f"{field} must be a lowercase SHA-256 digest")
    return value


def require_string(value: Any, field: str, *, max_length: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise GraceLoopError(f"{field} must be a nonempty string <= {max_length} characters")
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        raise GraceLoopError(f"{field} contains control characters")
    return value


def require_single_line(value: Any, field: str, *, max_length: int = 2000) -> str:
    result = require_string(value, field, max_length=max_length)
    if "\n" in result or "\r" in result:
        raise GraceLoopError(f"{field} must be a single line")
    return result


def require_string_list(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise GraceLoopError(f"{field} must be a list of strings")
    if not allow_empty and not value:
        raise GraceLoopError(f"{field} must not be empty")
    if len(value) != len(set(value)):
        raise GraceLoopError(f"{field} contains duplicates")
    return value


def require_relative(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise GraceLoopError(f"{field} must be a nonempty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path == Path("."):
        raise GraceLoopError(f"{field} must stay inside its declared root")
    return path


def contained_regular_file(root: Path, value: str, field: str) -> Path:
    relative = require_relative(value, field)
    if root.is_symlink():
        raise GraceLoopError(f"{field} root must not be a symlink")
    root = root.resolve(strict=True)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise GraceLoopError(f"{field} traverses a symlink")
    try:
        target = (root / relative).resolve(strict=True)
        target.relative_to(root)
    except (OSError, ValueError) as exc:
        raise GraceLoopError(f"{field} does not resolve to a contained file") from exc
    if not target.is_file() or target.is_symlink() or target.stat().st_nlink != 1:
        raise GraceLoopError(f"{field} must be a single-link regular file")
    return target


def reject_private_material(value: Any, field: str = "value") -> None:
    """Reject obvious secrets, host paths, and raw nucleotide payloads."""

    if isinstance(value, str):
        if any(pattern.search(value) for pattern in PRIVATE_TEXT_PATTERNS):
            raise GraceLoopError(f"{field} contains forbidden path or credential material")
        if (
            SEQUENCE_LIKE_RE.search(value)
            or IUPAC_SEQUENCE_LIKE_RE.search(value)
            or UPPERCASE_PROTEIN_LIKE_RE.search(value)
        ):
            raise GraceLoopError(f"{field} contains sequence-like material")
    elif isinstance(value, list):
        string_payload = "".join(item for item in value if isinstance(item, str))
        if len(string_payload) >= 80 and (
            SEQUENCE_LIKE_RE.search(string_payload)
            or IUPAC_SEQUENCE_LIKE_RE.search(string_payload)
            or UPPERCASE_PROTEIN_LIKE_RE.search(string_payload)
        ):
            raise GraceLoopError(f"{field} contains chunked sequence-like material")
        for index, item in enumerate(value):
            reject_private_material(item, f"{field}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            reject_private_material(key, f"{field}.<key>")
            if key.lower() in SEQUENCE_FIELD_KEYS and item not in (None, "", []):
                raise GraceLoopError(f"{field}.{key} contains a forbidden sequence field")
            reject_private_material(item, f"{field}.{key}")


def reject_floats(value: Any, field: str = "value") -> None:
    if isinstance(value, float):
        raise GraceLoopError(f"{field} must encode decimals as strings")
    if isinstance(value, list):
        for index, item in enumerate(value):
            reject_floats(item, f"{field}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            reject_floats(item, f"{field}.{key}")
