"""Filename-safety and legacy local-file helpers used by ``artifact.service``.

Split out of ``artifact.service`` because it's pure, dependency-free logic
(no repository, no I/O except the legacy filesystem fallback) - a distinct
concern from ``ArtifactService``'s orchestration of the two repositories.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_SAFE_FILENAME_CHARACTER = re.compile(r"[^\w. -]", flags=re.UNICODE)
_REPEATED_SEPARATOR = re.compile(r"[- ]{2,}")
_MAX_STEM_BYTES = 180


@dataclass(frozen=True)
class StoredArtifact:
    """A generated file's safe filename and public download metadata."""

    filename: str
    download_url: str


def _truncate_utf8(value: str, maximum_bytes: int) -> str:
    """Trim a filename stem without splitting a multi-byte character."""
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return value
    return encoded[:maximum_bytes].decode("utf-8", errors="ignore")


def safe_artifact_filename(
    requested_filename: str | None,
    *,
    default_stem: str,
    extension: str,
) -> str:
    """Reduce an untrusted filename to a safe basename with a fixed extension.

    Directory components (POSIX or Windows), leading dots, control characters,
    and punctuation with special filesystem meaning are discarded or replaced.
    The caller owns ``extension``; the untrusted value can never change the
    generated file type.
    """
    if not extension.startswith(".") or len(extension) < 2:
        raise ValueError("extension must start with a dot and include a file type.")

    raw = unicodedata.normalize("NFKC", requested_filename or "")
    basename = raw.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    cleaned = _SAFE_FILENAME_CHARACTER.sub("-", basename)
    cleaned = _REPEATED_SEPARATOR.sub("-", cleaned).strip(" ._-")

    if cleaned.lower().endswith(extension.lower()):
        stem = cleaned[: -len(extension)]
    elif "." in cleaned:
        stem = cleaned.rsplit(".", maxsplit=1)[0]
    else:
        stem = cleaned

    stem = _truncate_utf8(stem.strip(" ._-"), _MAX_STEM_BYTES) or default_stem
    return f"{stem}{extension.lower()}"


def read_local_file(value: str, *, extension: str) -> bytes:
    """Read a real absolute filesystem path - the legacy tool contract.

    ``edit_pdf``/``edit_markdown`` accept an absolute path to a file we
    never generated (unrelated to ``ArtifactService.store``), so this stays
    filesystem-based even though generated artifacts themselves no longer
    are.
    """
    candidate = Path(value)
    if candidate.is_symlink():
        raise ValueError("Artifact source cannot be a symbolic link.")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Artifact source does not exist: {value}") from exc
    if not resolved.is_file():
        raise ValueError("Artifact source must be a regular file.")
    if resolved.suffix.lower() != extension.lower():
        raise ValueError(f"Artifact source must be a {extension.lower()} file.")
    if not os.access(resolved, os.R_OK):
        raise PermissionError(f"Artifact source is not readable: {value}")
    return resolved.read_bytes()


__all__ = ["StoredArtifact", "read_local_file", "safe_artifact_filename"]
