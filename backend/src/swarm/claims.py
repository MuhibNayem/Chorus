"""Claim model helpers for the swarm blackboard protocol.

Claims are evidence-backed readiness statements published by autonomous agents.
This module intentionally has no Redis, FastAPI, or LangChain dependency so it
can be reused by stores, tools, validators, and tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


class ClaimType(StrEnum):
    SPEC_READY = "SPEC_READY"
    BACKEND_RUNTIME_READY = "BACKEND_RUNTIME_READY"
    BACKEND_API_ENDPOINT = "BACKEND_API_ENDPOINT"
    BACKEND_API_READY = "BACKEND_API_READY"
    FRONTEND_SOURCE_READY = "FRONTEND_SOURCE_READY"
    FRONTEND_BUILD_READY = "FRONTEND_BUILD_READY"
    DEPLOYMENT_READY = "DEPLOYMENT_READY"
    PACKAGE_READY = "PACKAGE_READY"


class ClaimStatus(StrEnum):
    DRAFT = "draft"
    CLAIMED = "claimed"
    VALID = "valid"
    INVALID = "invalid"
    STALE = "stale"
    REVOKED = "revoked"


class FailureType(StrEnum):
    """Classification of validation/recovery failures for routing to correct tier."""

    COMPILE_ERROR = "compile_error"             # Tier 1: sandbox feedback loop
    TEST_FAILED = "test_failed"                 # Tier 1: sandbox feedback loop
    TYPE_CHECK_FAILED = "type_check_failed"     # Tier 1: sandbox feedback loop
    EVIDENCE_DRIFT = "evidence_drift"           # Tier 2: rollback + re-run
    AGENT_INCONSISTENT = "agent_inconsistent"   # Tier 2: quarantine + human
    DEPENDENCY_STALE = "dependency_stale"       # Tier 2: wait + re-validate
    EVIDENCE_MISMATCH = "evidence_mismatch"     # Tier 2: rollback + re-run


# Max coordinator-level recovery retries for Tier 2 failures.
MAX_RECOVERY_RETRIES = 2


TERMINAL_CLAIM_STATUSES = frozenset({
    ClaimStatus.REVOKED.value,
})


REQUIRED_CLAIM_TYPES = tuple(claim_type.value for claim_type in ClaimType)
REQUIRED_CLAIM_STATUSES = tuple(status.value for status in ClaimStatus)

# Forward dependency graph: claim_type -> tuple of dependencies
CLAIM_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    ClaimType.SPEC_READY.value: (),
    ClaimType.BACKEND_RUNTIME_READY.value: (ClaimType.SPEC_READY.value,),
    ClaimType.BACKEND_API_ENDPOINT.value: (ClaimType.BACKEND_RUNTIME_READY.value,),
    ClaimType.BACKEND_API_READY.value: (ClaimType.BACKEND_RUNTIME_READY.value,),
    ClaimType.FRONTEND_SOURCE_READY.value: (ClaimType.SPEC_READY.value,),
    ClaimType.FRONTEND_BUILD_READY.value: (ClaimType.BACKEND_API_READY.value,),
    ClaimType.DEPLOYMENT_READY.value: (
        ClaimType.BACKEND_RUNTIME_READY.value,
        ClaimType.FRONTEND_BUILD_READY.value,
    ),
    ClaimType.PACKAGE_READY.value: (ClaimType.DEPLOYMENT_READY.value,),
}

# Claim producer mapping: claim_type -> agent_name
CLAIM_PRODUCERS: dict[str, str] = {
    ClaimType.SPEC_READY.value: "rootdep",
    ClaimType.BACKEND_RUNTIME_READY.value: "backend",
    ClaimType.BACKEND_API_ENDPOINT.value: "backend",
    ClaimType.BACKEND_API_READY.value: "backend",
    ClaimType.FRONTEND_SOURCE_READY.value: "frontend",
    ClaimType.FRONTEND_BUILD_READY.value: "frontend",
    ClaimType.DEPLOYMENT_READY.value: "devops",
    ClaimType.PACKAGE_READY.value: "packager",
}


def get_claim_producer(claim_type: str | ClaimType) -> str | None:
    """Return the agent name that produces this claim type."""
    return CLAIM_PRODUCERS.get(_enum_value(claim_type))


def get_claim_dependents(claim_type: str | ClaimType) -> tuple[str, ...]:
    """Return claim types that directly depend on the given claim type."""
    ct = _enum_value(claim_type)
    dependents: list[str] = []
    for candidate, deps in CLAIM_DEPENDENCIES.items():
        if ct in deps:
            dependents.append(candidate)
    return tuple(dependents)


def is_terminal_claim_status(status: str | ClaimStatus) -> bool:
    return _enum_value(status) in TERMINAL_CLAIM_STATUSES


def claim_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_evidence(evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    source = dict(evidence or {})
    return {
        "files": _coerce_list(source.get("files")),
        "ports": _coerce_list(source.get("ports")),
        "commands": _coerce_list(source.get("commands")),
        "metadata": _coerce_dict(source.get("metadata")),
    }


def build_claim_payload(
    *,
    project_id: str,
    claim_type: str | ClaimType,
    producer_agent: str,
    evidence: dict[str, Any] | None = None,
    depends_on: list[str] | tuple[str, ...] | None = None,
    status: str | ClaimStatus = ClaimStatus.CLAIMED,
    claim_id: str | None = None,
    producer_event_seq: int | None = None,
    workspace_revision: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = now or claim_now_iso()
    normalized_status = _enum_value(status)
    normalized_claim_type = _enum_value(claim_type)

    return {
        "id": claim_id or f"claim-{uuid4()}",
        "project_id": project_id,
        "claim_type": normalized_claim_type,
        "producer_agent": producer_agent,
        "status": normalized_status,
        "evidence": normalize_evidence(evidence),
        "depends_on": list(depends_on or []),
        "created_at": timestamp,
        "updated_at": timestamp,
        "producer_event_seq": producer_event_seq,
        "workspace_revision": workspace_revision,
        "validation": {
            "status": "unknown",
            "validated_at": None,
            "errors": [],
            "warnings": [],
        },
    }


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _coerce_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _enum_value(value: str | StrEnum) -> str:
    return value.value if isinstance(value, StrEnum) else str(value)
