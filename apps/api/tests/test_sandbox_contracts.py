from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError

from foundora.sandbox.contracts import (
    STATIC_WEBSITE_PROFILE,
    CleanupEvidence,
    EffectiveSandboxLimits,
    SandboxExecutePayload,
    SandboxExecuteRequest,
    SandboxExecutionResult,
    SandboxHarnessResult,
    SandboxRouteResult,
    canonical_json_bytes,
    canonical_sha256,
)


def _payload() -> SandboxExecutePayload:
    return SandboxExecutePayload(
        execution_id=uuid.UUID("10000000-0000-4000-8000-000000000001"),
        business_id=uuid.UUID("20000000-0000-4000-8000-000000000002"),
        website_project_id=uuid.UUID("30000000-0000-4000-8000-000000000003"),
        website_project_version=2,
        website_specification_id=uuid.UUID("40000000-0000-4000-8000-000000000004"),
        website_specification_version=3,
        profile_id="static-website",
        profile_version=1,
        source_digest="a" * 64,
        build_digest="b" * 64,
        source_archive_sha256="c" * 64,
        source_archive_size_bytes=512_000,
        routes=("/", "/pricing", "/about/team"),
    )


def _limits() -> EffectiveSandboxLimits:
    return EffectiveSandboxLimits.from_profile(
        STATIC_WEBSITE_PROFILE, seccomp_profile_sha256="d" * 64
    )


def _cleanup(*, status: str = "verified", resources: int = 0) -> CleanupEvidence:
    return CleanupEvidence.model_validate(
        {
            "status": status,
            "cleanup_attempts": 1,
            "final_labeled_resource_count": resources,
            "receipt_digest": "e" * 64,
        }
    )


def _result(**overrides: object) -> SandboxExecutionResult:
    values: dict[str, object] = {
        "contract_version": 1,
        "execution_id": _payload().execution_id,
        "request_digest": canonical_sha256(_payload()),
        "profile_id": "static-website",
        "profile_version": 1,
        "runtime_image_id": f"sha256:{'f' * 64}",
        "outcome": "succeeded",
        "termination_reason": "completed",
        "duration_ms": 250,
        "exit_code": 0,
        "effective_limits": _limits(),
        "route_results": (
            SandboxRouteResult(
                route="/",
                status="passed",
                http_status=200,
                document_ready_state="complete",
                script_count=1,
            ),
        ),
        "stdout_sha256": "1" * 64,
        "stderr_sha256": "2" * 64,
        "cleanup": _cleanup(),
    }
    values.update(overrides)
    return SandboxExecutionResult.model_validate(values)


def test_canonical_payload_hash_is_stable_across_json_key_order() -> None:
    payload = _payload()
    rendered = json.loads(canonical_json_bytes(payload))
    reversed_mapping = dict(reversed(list(rendered.items())))

    assert canonical_sha256(payload) == canonical_sha256(reversed_mapping)
    assert canonical_json_bytes(payload) == canonical_json_bytes(reversed_mapping)


def test_request_factory_pins_and_validates_canonical_payload() -> None:
    request = SandboxExecuteRequest.create(_payload())

    assert request.request_digest == canonical_sha256(request.payload)
    assert SandboxExecuteRequest.model_validate_json(request.model_dump_json()) == request


def test_request_rejects_digest_mismatch_and_unknown_fields() -> None:
    payload = _payload().model_dump()
    payload["command"] = "sh"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SandboxExecutePayload.model_validate(payload)

    with pytest.raises(ValidationError, match="request_digest does not match"):
        SandboxExecuteRequest(
            contract_version=1,
            payload=_payload(),
            request_digest="0" * 64,
        )


@pytest.mark.parametrize(
    "routes",
    [(), ("/", "/"), ("relative",), ("/trailing/",), ("/../escape",), ("/has space",)],
)
def test_payload_rejects_empty_duplicate_or_unsafe_routes(routes: tuple[str, ...]) -> None:
    values = _payload().model_dump()
    values["routes"] = routes

    with pytest.raises(ValidationError):
        SandboxExecutePayload.model_validate(values)


def test_profile_limits_cannot_be_weakened_or_extended() -> None:
    values = STATIC_WEBSITE_PROFILE.model_dump()
    values["memory_bytes"] = 1_073_741_824
    values["network_mode"] = "bridge"
    values["environment"] = {"OPENAI_API_KEY": "sentinel"}

    with pytest.raises(ValidationError):
        type(STATIC_WEBSITE_PROFILE).model_validate(values)


def test_success_requires_all_routes_and_verified_zero_resource_cleanup() -> None:
    failed_route = SandboxRouteResult(route="/", status="failed", runtime_errors=("boom",))

    with pytest.raises(ValidationError, match="every route to pass"):
        _result(route_results=(failed_route,))

    with pytest.raises(ValidationError, match="zero labeled resources"):
        _cleanup(resources=1)

    with pytest.raises(ValidationError, match="failed cleanup requires cleanup_failed"):
        _result(outcome="failed", cleanup=_cleanup(status="failed", resources=1))


def test_cleanup_failure_can_preserve_a_bounded_original_outcome() -> None:
    result = _result(
        outcome="cleanup_failed",
        termination_reason="child passed but cleanup could not be verified",
        cleanup=_cleanup(status="failed", resources=1),
    )

    assert result.outcome == "cleanup_failed"
    assert result.cleanup.final_labeled_resource_count == 1


def test_result_contract_rejects_unbounded_or_unknown_evidence() -> None:
    values = _result().model_dump()
    values["stdout_excerpt"] = "x" * 65_537
    values["container_options"] = {"Privileged": True}

    with pytest.raises(ValidationError):
        SandboxExecutionResult.model_validate(values)


def test_harness_result_strictly_validates_runtime_output() -> None:
    result = SandboxHarnessResult.model_validate_json(
        json.dumps(
            {
                "contract_version": 1,
                "duration_ms": 250,
                "route_results": [
                    {
                        "document_ready_state": "complete",
                        "execution_marker": True,
                        "http_status": 200,
                        "route": "/",
                        "runtime_errors": [],
                        "script_count": 1,
                        "status": "passed",
                    }
                ],
                "status": "passed",
            }
        )
    )

    assert result.route_results[0].execution_marker is True


def test_harness_cannot_claim_success_when_a_route_failed() -> None:
    with pytest.raises(ValidationError, match="harness status must match"):
        SandboxHarnessResult.model_validate(
            {
                "contract_version": 1,
                "duration_ms": 250,
                "route_results": (
                    {
                        "document_ready_state": None,
                        "execution_marker": False,
                        "http_status": None,
                        "route": "/",
                        "runtime_errors": ("page crashed",),
                        "script_count": 0,
                        "status": "failed",
                    },
                ),
                "status": "passed",
            }
        )
