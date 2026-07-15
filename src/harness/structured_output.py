"""Compatibility exports for the builder structured-output schema.

New code should import :mod:`harness.builder_schema`, whose name reflects that these
schemas describe the two-stage builder response rather than arbitrary output.
"""

from .builder_schema import (
    CONDITION_OPERATIONS,
    EFFECT_OPERATIONS,
    MANIFEST_SCHEMA,
    NON_REPEAT_EFFECT_OPERATIONS,
    build_response_schema,
    manifest_from_generated,
    manifest_mismatch,
    validate_manifest,
)

__all__ = [
    "CONDITION_OPERATIONS",
    "EFFECT_OPERATIONS",
    "MANIFEST_SCHEMA",
    "NON_REPEAT_EFFECT_OPERATIONS",
    "build_response_schema",
    "manifest_from_generated",
    "manifest_mismatch",
    "validate_manifest",
]
