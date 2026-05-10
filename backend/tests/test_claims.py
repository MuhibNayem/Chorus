import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.swarm.claims import (
    ClaimStatus,
    ClaimType,
    REQUIRED_CLAIM_STATUSES,
    REQUIRED_CLAIM_TYPES,
    build_claim_payload,
    claim_now_iso,
    is_terminal_claim_status,
    normalize_evidence,
)


def test_required_claim_types_exist():
    assert REQUIRED_CLAIM_TYPES == (
        "SPEC_READY",
        "BACKEND_RUNTIME_READY",
        "BACKEND_API_READY",
        "FRONTEND_SOURCE_READY",
        "FRONTEND_BUILD_READY",
        "DEPLOYMENT_READY",
        "PACKAGE_READY",
    )


def test_required_claim_statuses_exist():
    assert REQUIRED_CLAIM_STATUSES == (
        "draft",
        "claimed",
        "valid",
        "invalid",
        "stale",
        "revoked",
    )


def test_terminal_status_helper():
    assert is_terminal_claim_status(ClaimStatus.REVOKED)
    assert is_terminal_claim_status("revoked")
    assert not is_terminal_claim_status(ClaimStatus.VALID)
    assert not is_terminal_claim_status("stale")


def test_claim_now_iso_uses_utc_suffix():
    assert claim_now_iso().endswith("Z")


def test_normalize_evidence_defaults_shape():
    assert normalize_evidence() == {
        "files": [],
        "ports": [],
        "commands": [],
        "metadata": {},
    }


def test_normalize_evidence_preserves_known_fields():
    evidence = normalize_evidence({
        "files": ("backend/pom.xml",),
        "ports": 8080,
        "commands": ["mvn test"],
        "metadata": {"runtime": "java"},
        "ignored": "value",
    })

    assert evidence == {
        "files": ["backend/pom.xml"],
        "ports": [8080],
        "commands": ["mvn test"],
        "metadata": {"runtime": "java"},
    }


def test_build_claim_payload_has_required_keys():
    claim = build_claim_payload(
        project_id="project-1",
        claim_type=ClaimType.BACKEND_API_READY,
        producer_agent="backend",
        evidence={"files": ["backend/API_MANIFEST.json"]},
        depends_on=[ClaimType.BACKEND_RUNTIME_READY.value],
        producer_event_seq=42,
        workspace_revision="rev-1",
        now="2026-05-07T00:00:00Z",
    )

    assert claim == {
        "id": claim["id"],
        "project_id": "project-1",
        "claim_type": "BACKEND_API_READY",
        "producer_agent": "backend",
        "status": "claimed",
        "evidence": {
            "files": ["backend/API_MANIFEST.json"],
            "ports": [],
            "commands": [],
            "metadata": {},
        },
        "depends_on": ["BACKEND_RUNTIME_READY"],
        "created_at": "2026-05-07T00:00:00Z",
        "updated_at": "2026-05-07T00:00:00Z",
        "producer_event_seq": 42,
        "workspace_revision": "rev-1",
        "validation": {
            "status": "unknown",
            "validated_at": None,
            "errors": [],
            "warnings": [],
        },
    }
    assert claim["id"].startswith("claim-")


def test_build_claim_payload_accepts_explicit_status_and_id():
    claim = build_claim_payload(
        project_id="project-1",
        claim_type="SPEC_READY",
        producer_agent="rootdep",
        status=ClaimStatus.DRAFT,
        claim_id="claim-fixed",
    )

    assert claim["id"] == "claim-fixed"
    assert claim["status"] == "draft"
