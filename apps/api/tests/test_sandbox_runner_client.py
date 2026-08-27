import hashlib
import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from foundora.sandbox.contracts import (
    STATIC_WEBSITE_PROFILE,
    EffectiveSandboxLimits,
    SandboxExecutePayload,
    SandboxExecuteRequest,
    canonical_sha256,
)
from foundora.sandbox.runner_client import (
    RunnerAbsenceProof,
    RunnerProtocolError,
    RunnerReceipt,
    SandboxRunnerClient,
)

TOKEN = "sandbox-runner-test-token-000000000001"
SECCOMP_SHA256 = "17e2d449ab7c2c6fefc5b9f978224a49929864eb1d5a42f4f9002266c9300de2"


def _request(execution_id: uuid.UUID) -> SandboxExecuteRequest:
    return SandboxExecuteRequest.create(
        SandboxExecutePayload(
            execution_id=execution_id,
            business_id=uuid.uuid4(),
            website_project_id=uuid.uuid4(),
            website_project_version=1,
            website_specification_id=uuid.uuid4(),
            website_specification_version=1,
            profile_id="static-website",
            profile_version=1,
            source_digest="1" * 64,
            build_digest="1" * 64,
            source_archive_sha256=hashlib.sha256(b"{}").hexdigest(),
            source_archive_size_bytes=2,
            routes=("/",),
        )
    )


def _receipt(request: SandboxExecuteRequest, *, status: str = "succeeded") -> dict[str, object]:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    limits = EffectiveSandboxLimits.from_profile(
        STATIC_WEBSITE_PROFILE,
        seccomp_profile_sha256=SECCOMP_SHA256,
    )
    return {
        "contract_version": 1,
        "execution_id": str(request.payload.execution_id),
        "request_digest": request.request_digest,
        "source_archive_sha256": request.payload.source_archive_sha256,
        "profile_id": "static-website",
        "profile_version": 1,
        "state": "terminal",
        "status": status,
        "runtime_image_id": f"sha256:{'3' * 64}",
        "container_id": None,
        "source_volume_name": None,
        "effective_limits": limits.model_dump(mode="json"),
        "effective_limits_digest": canonical_sha256(limits),
        "termination_reason": "completed",
        "exit_code": 0,
        "duration_ms": 10,
        "route_results": [
            {
                "route": "/",
                "status": "passed",
                "http_status": 200,
                "document_ready_state": "complete",
                "script_count": 1,
                "runtime_errors": [],
            }
        ],
        "process_results": None,
        "stdout_excerpt": "{}",
        "stderr_excerpt": "",
        "stdout_sha256": "4" * 64,
        "stderr_sha256": "5" * 64,
        "cleanup": {
            "status": "verified",
            "cleanup_attempts": 1,
            "final_labeled_resource_count": 0,
            "receipt_digest": "6" * 64,
            "started_at": now,
            "finished_at": now,
        },
        "cancel_requested_at": None,
        "created_at": now,
        "started_at": now,
        "finished_at": now,
        "acknowledged_at": None,
    }


@pytest.mark.asyncio
async def test_runner_client_authenticates_and_pins_the_exact_submission() -> None:
    execution_id = uuid.uuid4()
    request = _request(execution_id)

    def handler(message: httpx.Request) -> httpx.Response:
        assert message.headers["authorization"] == f"Bearer {TOKEN}"
        body = json.loads(message.content)
        assert set(body) == {"contract_version", "operation", "request", "source_archive"}
        assert body["request"]["request_digest"] == request.request_digest
        assert body["source_archive"]["data"] == "e30="
        return httpx.Response(200, json=_receipt(request))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SandboxRunnerClient(base_url="http://runner.test", token=TOKEN, client=http)
        receipt = await client.execute(request, b"{}")

    assert isinstance(receipt, RunnerReceipt)
    assert receipt.status == "succeeded"
    assert receipt.cleanup.final_labeled_resource_count == 0


@pytest.mark.asyncio
async def test_runner_client_rejects_undeclared_receipt_fields() -> None:
    request = _request(uuid.uuid4())
    body = _receipt(request)
    body["engine_options"] = {"Privileged": True}

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SandboxRunnerClient(base_url="http://runner.test", token=TOKEN, client=http)
        with pytest.raises(RunnerProtocolError, match="invalid receipt"):
            await client.inspect(request.payload.execution_id)


@pytest.mark.asyncio
async def test_missing_execution_cancellation_requires_zero_resource_proof() -> None:
    execution_id = uuid.uuid4()
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "contract_version": 1,
                "execution_id": str(execution_id),
                "status": "absent",
                "cleanup": {
                    "status": "verified",
                    "cleanup_attempts": 1,
                    "final_labeled_resource_count": 0,
                    "receipt_digest": "7" * 64,
                    "started_at": now,
                    "finished_at": now,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SandboxRunnerClient(base_url="http://runner.test", token=TOKEN, client=http)
        proof = await client.cancel(execution_id)

    assert isinstance(proof, RunnerAbsenceProof)
    assert proof.cleanup.status == "verified"
