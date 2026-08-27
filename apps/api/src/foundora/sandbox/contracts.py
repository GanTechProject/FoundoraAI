from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

SHA256_PATTERN = r"^[a-f0-9]{64}$"
PROFILE_ID_PATTERN = r"^[a-z][a-z0-9-]{2,63}$"
RUNTIME_IMAGE_ID_PATTERN = r"^sha256:[a-f0-9]{64}$"
MAX_SOURCE_ARCHIVE_BYTES = 768_000
MAX_ROUTES = 16
MAX_ROUTE_ERRORS = 32
MAX_ERROR_CHARACTERS = 500
MAX_EVIDENCE_EXCERPT_CHARACTERS = 65_536

type Sha256 = Annotated[str, StringConstraints(pattern=SHA256_PATTERN)]
type ProfileId = Annotated[str, StringConstraints(pattern=PROFILE_ID_PATTERN)]
type RuntimeImageId = Annotated[str, StringConstraints(pattern=RUNTIME_IMAGE_ID_PATTERN)]
type BoundedError = Annotated[str, StringConstraints(min_length=1, max_length=MAX_ERROR_CHARACTERS)]

_ROUTE = re.compile(r"^/(?:[a-z0-9][a-z0-9_-]*/?)*$")


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SandboxProfile(FrozenContract):
    profile_id: ProfileId
    version: Annotated[int, Field(ge=1)]
    harness_contract_version: Annotated[int, Field(ge=1)]
    runtime_image_contract_key: Annotated[str, StringConstraints(pattern=PROFILE_ID_PATTERN)]
    runtime_build_manifest_sha256: Sha256
    cpu_nanos: Literal[1_000_000_000]
    memory_bytes: Literal[536_870_912]
    memory_swap_bytes: Literal[536_870_912]
    pids_limit: Literal[128]
    wall_timeout_seconds: Literal[60]
    termination_grace_seconds: Literal[3]
    tmpfs_bytes: Literal[134_217_728]
    dev_shm_bytes: Literal[134_217_728]
    combined_output_bytes: Literal[1_048_576]
    network_mode: Literal["none"]
    read_only_root_filesystem: Literal[True]
    source_read_only: Literal[True]
    run_as_non_root: Literal[True]
    drop_all_capabilities: Literal[True]
    add_sys_chroot_capability: Literal[True]
    no_new_privileges: Literal[True]
    no_host_namespaces: Literal[True]
    no_devices: Literal[True]
    allowed_project_kind: Literal["static-website"]


# Updated only after apps/sandbox-runtime/runtime-manifest.json is reviewed.
STATIC_WEBSITE_PROFILE = SandboxProfile(
    profile_id="static-website",
    version=1,
    harness_contract_version=1,
    runtime_image_contract_key="foundora-static-website-runtime",
    runtime_build_manifest_sha256="ab73f13726b30608c83a212d7cf762ee2b74986f535680377560db69286d8601",
    cpu_nanos=1_000_000_000,
    memory_bytes=536_870_912,
    memory_swap_bytes=536_870_912,
    pids_limit=128,
    wall_timeout_seconds=60,
    termination_grace_seconds=3,
    tmpfs_bytes=134_217_728,
    dev_shm_bytes=134_217_728,
    combined_output_bytes=1_048_576,
    network_mode="none",
    read_only_root_filesystem=True,
    source_read_only=True,
    run_as_non_root=True,
    drop_all_capabilities=True,
    add_sys_chroot_capability=True,
    no_new_privileges=True,
    no_host_namespaces=True,
    no_devices=True,
    allowed_project_kind="static-website",
)


class SandboxExecutePayload(FrozenContract):
    execution_id: uuid.UUID
    business_id: uuid.UUID
    website_project_id: uuid.UUID
    website_project_version: Annotated[int, Field(ge=1)]
    website_specification_id: uuid.UUID
    website_specification_version: Annotated[int, Field(ge=1)]
    profile_id: Literal["static-website"]
    profile_version: Literal[1]
    source_digest: Sha256
    build_digest: Sha256
    source_archive_sha256: Sha256
    source_archive_size_bytes: Annotated[int, Field(ge=1, le=MAX_SOURCE_ARCHIVE_BYTES)]
    routes: tuple[str, ...]

    @field_validator("routes")
    @classmethod
    def validate_routes(cls, routes: tuple[str, ...]) -> tuple[str, ...]:
        if not routes or len(routes) > MAX_ROUTES:
            raise ValueError(f"routes must contain between 1 and {MAX_ROUTES} entries")
        if len(routes) != len(set(routes)):
            raise ValueError("routes must be unique")
        for route in routes:
            if route != "/" and (not _ROUTE.fullmatch(route) or route.endswith("/")):
                raise ValueError("routes must be normalized absolute static-site routes")
        return routes


class SandboxExecuteRequest(FrozenContract):
    contract_version: Literal[1]
    payload: SandboxExecutePayload
    request_digest: Sha256

    @model_validator(mode="after")
    def validate_request_digest(self) -> SandboxExecuteRequest:
        expected = canonical_sha256(self.payload)
        if not self.request_digest == expected:
            raise ValueError("request_digest does not match the canonical payload")
        return self

    @classmethod
    def create(cls, payload: SandboxExecutePayload) -> SandboxExecuteRequest:
        return cls(contract_version=1, payload=payload, request_digest=canonical_sha256(payload))


class EffectiveSandboxLimits(FrozenContract):
    cpu_nanos: Literal[1_000_000_000]
    memory_bytes: Literal[536_870_912]
    memory_swap_bytes: Literal[536_870_912]
    pids_limit: Literal[128]
    wall_timeout_seconds: Literal[60]
    termination_grace_seconds: Literal[3]
    tmpfs_bytes: Literal[134_217_728]
    dev_shm_bytes: Literal[134_217_728]
    combined_output_bytes: Literal[1_048_576]
    network_mode: Literal["none"]
    read_only_root_filesystem: Literal[True]
    source_read_only: Literal[True]
    run_as_non_root: Literal[True]
    drop_all_capabilities: Literal[True]
    add_sys_chroot_capability: Literal[True]
    no_new_privileges: Literal[True]
    no_host_namespaces: Literal[True]
    no_devices: Literal[True]
    seccomp_profile_sha256: Sha256

    @classmethod
    def from_profile(
        cls, profile: SandboxProfile, *, seccomp_profile_sha256: Sha256
    ) -> EffectiveSandboxLimits:
        return cls(
            **profile.model_dump(
                include={
                    "cpu_nanos",
                    "memory_bytes",
                    "memory_swap_bytes",
                    "pids_limit",
                    "wall_timeout_seconds",
                    "termination_grace_seconds",
                    "tmpfs_bytes",
                    "dev_shm_bytes",
                    "combined_output_bytes",
                    "network_mode",
                    "read_only_root_filesystem",
                    "source_read_only",
                    "run_as_non_root",
                    "drop_all_capabilities",
                    "add_sys_chroot_capability",
                    "no_new_privileges",
                    "no_host_namespaces",
                    "no_devices",
                }
            ),
            seccomp_profile_sha256=seccomp_profile_sha256,
        )


class SandboxRouteResult(FrozenContract):
    route: str
    status: Literal["passed", "failed"]
    http_status: Annotated[int | None, Field(ge=100, le=599)] = None
    document_ready_state: Literal["loading", "interactive", "complete"] | None = None
    script_count: Annotated[int, Field(ge=0, le=1_000)] = 0
    runtime_errors: Annotated[tuple[BoundedError, ...], Field(max_length=MAX_ROUTE_ERRORS)] = ()

    @field_validator("route")
    @classmethod
    def validate_route(cls, route: str) -> str:
        if route != "/" and (not _ROUTE.fullmatch(route) or route.endswith("/")):
            raise ValueError("route must be a normalized absolute static-site route")
        return route

    @model_validator(mode="after")
    def validate_passing_route(self) -> SandboxRouteResult:
        if self.status == "passed" and (
            self.http_status != 200
            or self.document_ready_state != "complete"
            or self.runtime_errors
        ):
            raise ValueError("passing route requires HTTP 200, complete document, and no errors")
        return self


class SandboxHarnessRouteResult(FrozenContract):
    route: str
    status: Literal["passed", "failed"]
    http_status: Annotated[int | None, Field(ge=100, le=599)]
    document_ready_state: Literal["loading", "interactive", "complete"] | None
    script_count: Annotated[int, Field(ge=0, le=1_000)]
    execution_marker: bool
    runtime_errors: Annotated[tuple[BoundedError, ...], Field(max_length=MAX_ROUTE_ERRORS)]

    @model_validator(mode="after")
    def validate_route_result(self) -> SandboxHarnessRouteResult:
        SandboxRouteResult(
            route=self.route,
            status=self.status,
            http_status=self.http_status,
            document_ready_state=self.document_ready_state,
            script_count=self.script_count,
            runtime_errors=self.runtime_errors,
        )
        return self


class SandboxHarnessResult(FrozenContract):
    contract_version: Literal[1]
    status: Literal["passed", "failed"]
    duration_ms: Annotated[int, Field(ge=0, le=60_000)]
    route_results: Annotated[
        tuple[SandboxHarnessRouteResult, ...], Field(min_length=1, max_length=MAX_ROUTES)
    ]

    @model_validator(mode="after")
    def validate_status(self) -> SandboxHarnessResult:
        all_passed = all(item.status == "passed" for item in self.route_results)
        if (self.status == "passed") != all_passed:
            raise ValueError("harness status must match the route results")
        return self


class CleanupEvidence(FrozenContract):
    status: Literal["verified", "failed"]
    cleanup_attempts: Annotated[int, Field(ge=1, le=10)]
    final_labeled_resource_count: Annotated[int, Field(ge=0, le=10_000)]
    receipt_digest: Sha256

    @model_validator(mode="after")
    def validate_verified_cleanup(self) -> CleanupEvidence:
        if self.status == "verified" and self.final_labeled_resource_count != 0:
            raise ValueError("verified cleanup requires zero labeled resources")
        return self


class SandboxExecutionResult(FrozenContract):
    contract_version: Literal[1]
    execution_id: uuid.UUID
    request_digest: Sha256
    profile_id: Literal["static-website"]
    profile_version: Literal[1]
    runtime_image_id: RuntimeImageId
    outcome: Literal[
        "succeeded",
        "failed",
        "cancelled",
        "timed_out",
        "resource_exhausted",
        "infrastructure_failed",
        "cleanup_failed",
    ]
    termination_reason: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    duration_ms: Annotated[int, Field(ge=0, le=120_000)]
    exit_code: Annotated[int | None, Field(ge=0, le=255)] = None
    effective_limits: EffectiveSandboxLimits
    route_results: Annotated[tuple[SandboxRouteResult, ...], Field(max_length=MAX_ROUTES)]
    stdout_sha256: Sha256
    stderr_sha256: Sha256
    stdout_excerpt: Annotated[
        str, StringConstraints(max_length=MAX_EVIDENCE_EXCERPT_CHARACTERS)
    ] = ""
    stderr_excerpt: Annotated[
        str, StringConstraints(max_length=MAX_EVIDENCE_EXCERPT_CHARACTERS)
    ] = ""
    cleanup: CleanupEvidence

    @model_validator(mode="after")
    def validate_truthful_success(self) -> SandboxExecutionResult:
        if self.outcome == "succeeded":
            if self.cleanup.status != "verified":
                raise ValueError("successful execution requires verified cleanup")
            if not self.route_results or any(
                item.status != "passed" for item in self.route_results
            ):
                raise ValueError("successful execution requires every route to pass")
        if self.cleanup.status == "failed" and self.outcome != "cleanup_failed":
            raise ValueError("failed cleanup requires cleanup_failed outcome")
        return self


type CanonicalValue = BaseModel | Mapping[str, object] | Sequence[object] | str | int | bool | None


def canonical_json_bytes(value: CanonicalValue) -> bytes:
    serializable: object
    if isinstance(value, BaseModel):
        serializable = value.model_dump(mode="json")
    else:
        serializable = value
    return json.dumps(
        serializable,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: CanonicalValue) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
