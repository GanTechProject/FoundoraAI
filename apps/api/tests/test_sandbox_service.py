from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest

from foundora.governance.registry import ACTION_CATALOG, TOOL_CATALOG, classify_action
from foundora.models import (
    SandboxExecution,
    SandboxProfile,
    WebsiteProjectVersion,
    WebsiteSpecificationVersion,
)
from foundora.sandbox.contracts import STATIC_WEBSITE_PROFILE
from foundora.sandbox.service import (
    SandboxConflict,
    SandboxIllegalTransition,
    SandboxNotReady,
    SandboxProfileMismatch,
    _sandbox_job_id,
    assert_idempotent_request,
    assert_pinned_execution,
    assert_profile_parity,
    governance_target,
    prepare_execution_request,
    transition_execution,
)


def _tree_digest(files: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda value: str(value["path"])):
        digest.update(str(item["path"]).encode())
        digest.update(b"\0")
        digest.update(str(item["sha256"]).encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _inputs() -> tuple[uuid.UUID, WebsiteProjectVersion, WebsiteSpecificationVersion]:
    business_id = uuid.uuid4()
    specification_id = uuid.uuid4()
    content = "<!doctype html><html><body><main>Ready</main></body></html>"
    encoded = content.encode()
    source_files: list[dict[str, object]] = [
        {
            "path": "index.html",
            "media_type": "text/html",
            "content": content,
            "size_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    ]
    build_manifest: list[dict[str, object]] = [
        {
            "path": "index.html",
            "size_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    ]
    project = WebsiteProjectVersion(
        id=uuid.uuid4(),
        business_id=business_id,
        version=2,
        status="active",
        source_website_specification_id=specification_id,
        source_website_specification_version=3,
        source_files=source_files,
        dependency_manifest={"manager": "none", "dependencies": []},
        source_digest=_tree_digest(source_files),
        build_digest=_tree_digest(build_manifest),
        build_manifest=build_manifest,
    )
    specification = WebsiteSpecificationVersion(
        id=specification_id,
        business_id=business_id,
        version=3,
        status="active",
        specification={"sitemap": [{"path": "/"}]},
    )
    return business_id, project, specification


def _execution(status: str) -> SandboxExecution:
    now = datetime.now(UTC)
    return SandboxExecution(
        id=uuid.uuid4(),
        status=status,
        cleanup_status="pending",
        worker_recovery_count=0,
        cleanup_attempts=0,
        created_at=now,
        updated_at=now,
    )


def test_profile_seed_shape_matches_reviewed_catalog() -> None:
    profile = SandboxProfile(**STATIC_WEBSITE_PROFILE.model_dump(), created_at=datetime.now(UTC))
    assert_profile_parity(profile)

    profile.network_mode = "bridge"
    with pytest.raises(SandboxProfileMismatch, match="disagrees"):
        assert_profile_parity(profile)


def test_request_pins_exact_inputs_and_governance_target() -> None:
    business_id, project, specification = _inputs()
    request = prepare_execution_request(
        execution_id=uuid.uuid4(),
        business_id=business_id,
        project=project,
        specification=specification,
    )

    assert request.payload.website_project_id == project.id
    assert request.payload.website_project_version == project.version
    assert request.payload.website_specification_id == specification.id
    assert request.payload.website_specification_version == specification.version
    assert request.payload.routes == ("/",)
    assert governance_target(request).endswith(f"request:{request.request_digest}")
    assert "profile:static-website@1" in governance_target(request)


def test_stale_or_tampered_project_is_rejected() -> None:
    business_id, project, specification = _inputs()
    project.source_website_specification_version = 2
    with pytest.raises(SandboxNotReady, match="stale"):
        prepare_execution_request(
            execution_id=uuid.uuid4(),
            business_id=business_id,
            project=project,
            specification=specification,
        )

    project.source_website_specification_version = specification.version
    project.source_files[0]["content"] = "tampered"
    with pytest.raises(SandboxNotReady, match="no longer matches"):
        prepare_execution_request(
            execution_id=uuid.uuid4(),
            business_id=business_id,
            project=project,
            specification=specification,
        )


def test_idempotency_requires_the_same_canonical_request() -> None:
    business_id, project, specification = _inputs()
    execution_id = uuid.uuid4()
    request = prepare_execution_request(
        execution_id=execution_id,
        business_id=business_id,
        project=project,
        specification=specification,
    )
    existing = _execution("waiting_approval")
    existing.id = execution_id
    existing.request_digest = request.request_digest
    assert_idempotent_request(existing, request)

    existing.request_digest = "0" * 64
    with pytest.raises(SandboxConflict, match="another sandbox request"):
        assert_idempotent_request(existing, request)


def test_pinned_execution_and_recovery_job_identity_are_exact() -> None:
    business_id, project, specification = _inputs()
    execution_id = uuid.uuid4()
    request = prepare_execution_request(
        execution_id=execution_id,
        business_id=business_id,
        project=project,
        specification=specification,
    )
    execution = _execution("queued")
    execution.id = execution_id
    execution.business_id = business_id
    execution.website_project_id = project.id
    execution.website_project_version = project.version
    execution.website_specification_id = specification.id
    execution.website_specification_version = specification.version
    execution.profile_id = "static-website"
    execution.profile_version = 1
    execution.source_digest = project.source_digest
    execution.build_digest = project.build_digest
    execution.source_archive_sha256 = request.payload.source_archive_sha256
    execution.source_archive_size_bytes = request.payload.source_archive_size_bytes
    execution.routes = list(request.payload.routes)
    execution.request_digest = request.request_digest
    execution.policy_version_id = uuid.uuid4()

    assert_pinned_execution(execution, request)
    assert _sandbox_job_id(execution_id, 0) == f"sandbox-execution-{execution_id}"
    assert _sandbox_job_id(execution_id, 2).endswith("-recovery-2")

    execution.source_digest = "0" * 64
    with pytest.raises(SandboxNotReady, match="evidence is stale"):
        assert_pinned_execution(execution, request)


def test_state_machine_rejects_skips_and_requires_truthful_cleanup() -> None:
    execution = _execution("waiting_approval")
    with pytest.raises(SandboxIllegalTransition, match="waiting_approval -> running"):
        transition_execution(execution, "running")

    transition_execution(execution, "queued")
    transition_execution(execution, "authorizing")
    transition_execution(execution, "running")
    transition_execution(execution, "cleaning")
    with pytest.raises(SandboxIllegalTransition, match="verified zero-resource"):
        transition_execution(execution, "succeeded")

    execution.cleanup_status = "verified"
    execution.final_labeled_resource_count = 0
    transition_execution(execution, "succeeded")
    assert execution.finished_at is not None

    with pytest.raises(SandboxIllegalTransition, match="succeeded -> failed"):
        transition_execution(execution, "failed")

    interrupted = _execution("authorizing")
    transition_execution(interrupted, "cleaning")
    interrupted.cleanup_status = "verified"
    interrupted.final_labeled_resource_count = 0
    transition_execution(interrupted, "infrastructure_failed")


def test_sandbox_catalog_entries_are_fixed_r2_internal_controls() -> None:
    action = ACTION_CATALOG["internal.code.execute"]
    tool = TOOL_CATALOG["foundora.sandbox.website"]

    assert action.risk_class == "R2"
    assert tool.risk_class == "R2"
    assert tool.internal is True
    assert (
        classify_action(
            action.action_type,
            tool_id=tool.tool_id,
            requested_spend_microusd=0,
        )
        == "R2"
    )
