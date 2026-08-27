from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime
from typing import Annotated, Literal

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from foundora.sandbox.contracts import (
    MAX_EVIDENCE_EXCERPT_CHARACTERS,
    MAX_ROUTES,
    CleanupEvidence,
    EffectiveSandboxLimits,
    SandboxExecuteRequest,
    SandboxRouteResult,
    Sha256,
    canonical_json_bytes,
    canonical_sha256,
)

MAX_RUNNER_RESPONSE_BYTES = 1_200_000
type RunnerStatus = Literal[
    "pending",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "resource_exhausted",
    "infrastructure_failed",
    "cleanup_failed",
]
TERMINAL_RUNNER_STATUSES = frozenset(
    {
        "succeeded",
        "failed",
        "cancelled",
        "timed_out",
        "resource_exhausted",
        "infrastructure_failed",
        "cleanup_failed",
    }
)


class RunnerUnavailable(Exception):
    pass


class RunnerProtocolError(Exception):
    pass


class RunnerConflict(Exception):
    pass


class RunnerContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RunnerCleanupEvidence(RunnerContract):
    status: Literal["pending", "verified", "failed"]
    cleanup_attempts: Annotated[int, Field(ge=0, le=10)]
    final_labeled_resource_count: Annotated[int | None, Field(ge=0)]
    receipt_digest: Sha256 | None
    started_at: datetime | None
    finished_at: datetime | None

    @model_validator(mode="after")
    def validate_cleanup(self) -> RunnerCleanupEvidence:
        if self.status == "pending" and any(
            value is not None
            for value in (
                self.final_labeled_resource_count,
                self.receipt_digest,
                self.finished_at,
            )
        ):
            raise ValueError("pending cleanup cannot contain terminal evidence")
        if self.status in {"verified", "failed"} and (
            self.cleanup_attempts < 1
            or self.final_labeled_resource_count is None
            or self.receipt_digest is None
            or self.started_at is None
            or self.finished_at is None
        ):
            raise ValueError("terminal cleanup evidence is incomplete")
        if self.status == "verified" and self.final_labeled_resource_count != 0:
            raise ValueError("verified cleanup requires zero labeled resources")
        return self


class RunnerReceipt(RunnerContract):
    contract_version: Literal[1]
    execution_id: uuid.UUID
    request_digest: Sha256
    source_archive_sha256: Sha256
    profile_id: Literal["static-website"]
    profile_version: Literal[1]
    state: Literal["received", "creating", "running", "cleaning", "terminal"]
    status: RunnerStatus
    runtime_image_id: Annotated[str | None, StringConstraints(pattern=r"^sha256:[a-f0-9]{64}$")]
    container_id: Annotated[str | None, StringConstraints(max_length=128)]
    source_volume_name: Annotated[str | None, StringConstraints(max_length=160)]
    effective_limits: EffectiveSandboxLimits | None
    effective_limits_digest: Sha256 | None
    termination_reason: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    exit_code: Annotated[int | None, Field(ge=0, le=255)]
    duration_ms: Annotated[int, Field(ge=0, le=120_000)]
    route_results: Annotated[tuple[SandboxRouteResult, ...], Field(max_length=MAX_ROUTES)]
    process_results: dict[str, str | int | bool | None] | None
    stdout_excerpt: Annotated[str, StringConstraints(max_length=MAX_EVIDENCE_EXCERPT_CHARACTERS)]
    stderr_excerpt: Annotated[str, StringConstraints(max_length=MAX_EVIDENCE_EXCERPT_CHARACTERS)]
    stdout_sha256: Sha256
    stderr_sha256: Sha256
    cleanup: RunnerCleanupEvidence
    cancel_requested_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    acknowledged_at: datetime | None

    @field_validator("process_results")
    @classmethod
    def validate_process_results(
        cls, value: dict[str, str | int | bool | None] | None
    ) -> dict[str, str | int | bool | None] | None:
        if value is not None and (len(value) > 16 or len(canonical_json_bytes(value)) > 32_768):
            raise ValueError("process results exceed their boundary")
        return value

    @model_validator(mode="after")
    def validate_receipt(self) -> RunnerReceipt:
        terminal = self.status in TERMINAL_RUNNER_STATUSES
        if terminal != (self.state == "terminal"):
            raise ValueError("runner state and status disagree")
        if terminal and (
            self.finished_at is None
            or self.runtime_image_id is None
            or self.cleanup.status == "pending"
        ):
            raise ValueError("terminal runner receipt is incomplete")
        if self.status == "succeeded" and (
            self.cleanup.status != "verified"
            or not self.route_results
            or any(item.status != "passed" for item in self.route_results)
        ):
            raise ValueError("successful runner receipt is not truthful")
        if self.cleanup.status == "failed" and self.status != "cleanup_failed":
            raise ValueError("failed cleanup must produce cleanup_failed")
        if self.effective_limits is None and self.effective_limits_digest is not None:
            raise ValueError("effective limit digest has no matching evidence")
        if self.effective_limits is not None and (
            self.effective_limits_digest != canonical_sha256(self.effective_limits)
        ):
            raise ValueError("effective limit digest does not match its evidence")
        return self

    def cleanup_contract(self) -> CleanupEvidence:
        if (
            self.cleanup.status == "pending"
            or self.cleanup.final_labeled_resource_count is None
            or self.cleanup.receipt_digest is None
        ):
            raise RunnerProtocolError("runner cleanup is not terminal")
        return CleanupEvidence(
            status=self.cleanup.status,
            cleanup_attempts=self.cleanup.cleanup_attempts,
            final_labeled_resource_count=self.cleanup.final_labeled_resource_count,
            receipt_digest=self.cleanup.receipt_digest,
        )


class RunnerAbsenceProof(RunnerContract):
    contract_version: Literal[1]
    execution_id: uuid.UUID
    status: Literal["absent"]
    cleanup: RunnerCleanupEvidence

    @model_validator(mode="after")
    def validate_absence(self) -> RunnerAbsenceProof:
        if self.cleanup.status != "verified" or self.cleanup.final_labeled_resource_count != 0:
            raise ValueError("absence proof requires verified zero-resource cleanup")
        return self


type RunnerCancellation = RunnerReceipt | RunnerAbsenceProof


class SandboxRunnerClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if len(token) < 32:
            raise ValueError("sandbox runner token must contain at least 32 characters")
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
        timeout_seconds: float = 75.0,
    ) -> httpx.Response:
        headers = {
            "authorization": f"Bearer {self._token}",
            "content-type": "application/json",
        }
        try:
            if self._client is not None:
                response = await self._client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=headers,
                    json=body,
                    timeout=timeout_seconds,
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.request(
                        method,
                        f"{self._base_url}{path}",
                        headers=headers,
                        json=body,
                        timeout=timeout_seconds,
                    )
        except httpx.HTTPError as error:
            raise RunnerUnavailable("Sandbox runner is unavailable") from error
        if len(response.content) > MAX_RUNNER_RESPONSE_BYTES:
            raise RunnerProtocolError("Sandbox runner response exceeded its boundary")
        return response

    @staticmethod
    def _receipt(response: httpx.Response) -> RunnerReceipt:
        try:
            return RunnerReceipt.model_validate_json(response.content, strict=True)
        except ValueError as error:
            raise RunnerProtocolError("Sandbox runner returned an invalid receipt") from error

    async def execute(self, request: SandboxExecuteRequest, source_archive: bytes) -> RunnerReceipt:
        if (
            len(source_archive) != request.payload.source_archive_size_bytes
            or hashlib.sha256(source_archive).hexdigest() != request.payload.source_archive_sha256
        ):
            raise RunnerProtocolError("Pinned source archive changed before submission")
        body: dict[str, object] = {
            "contract_version": 1,
            "operation": "execute",
            "request": request.model_dump(mode="json"),
            "source_archive": {
                "data": base64.b64encode(source_archive).decode("ascii"),
                "encoding": "base64",
                "media_type": "application/vnd.foundora.sandbox-source+json",
            },
        }
        response = await self._request("POST", "/v1/executions", body=body)
        if response.status_code == 409:
            raise RunnerConflict("Sandbox runner execution identity conflicted")
        if response.status_code not in {200, 202}:
            raise RunnerUnavailable("Sandbox runner rejected execution")
        receipt = self._receipt(response)
        if (
            receipt.execution_id != request.payload.execution_id
            or receipt.request_digest != request.request_digest
            or receipt.source_archive_sha256 != request.payload.source_archive_sha256
        ):
            raise RunnerProtocolError("Sandbox runner receipt identity mismatched")
        return receipt

    async def inspect(self, execution_id: uuid.UUID) -> RunnerReceipt | None:
        response = await self._request("GET", f"/v1/executions/{execution_id}")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise RunnerUnavailable("Sandbox runner inspection failed")
        receipt = self._receipt(response)
        if receipt.execution_id != execution_id:
            raise RunnerProtocolError("Sandbox runner inspection identity mismatched")
        return receipt

    async def cancel(self, execution_id: uuid.UUID) -> RunnerCancellation:
        response = await self._request(
            "POST",
            f"/v1/executions/{execution_id}/cancel",
            body={"contract_version": 1},
        )
        if response.status_code == 200:
            try:
                proof = RunnerAbsenceProof.model_validate_json(response.content, strict=True)
            except ValueError as error:
                raise RunnerProtocolError(
                    "Sandbox runner returned an invalid absence proof"
                ) from error
            if proof.execution_id != execution_id:
                raise RunnerProtocolError("Sandbox runner absence identity mismatched")
            return proof
        if response.status_code != 202:
            raise RunnerUnavailable("Sandbox runner cancellation failed")
        receipt = self._receipt(response)
        if receipt.execution_id != execution_id:
            raise RunnerProtocolError("Sandbox runner cancellation identity mismatched")
        return receipt

    async def acknowledge(self, execution_id: uuid.UUID) -> RunnerReceipt:
        response = await self._request(
            "POST",
            f"/v1/executions/{execution_id}/acknowledge",
            body={"contract_version": 1},
        )
        if response.status_code != 200:
            raise RunnerUnavailable("Sandbox runner acknowledgement failed")
        receipt = self._receipt(response)
        if receipt.execution_id != execution_id or receipt.acknowledged_at is None:
            raise RunnerProtocolError("Sandbox runner acknowledgement was invalid")
        return receipt
