from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy.ext.asyncio import AsyncSession

from foundora.models import DomainEvent

EventHandler = Callable[[AsyncSession, DomainEvent], Awaitable[dict[str, object]]]


class EventContractError(Exception):
    pass


@dataclass(frozen=True)
class EventContract:
    event_type: str
    schema_version: int
    aggregate_type: str
    description: str
    payload_schema: Mapping[str, object]


@dataclass(frozen=True)
class EventConsumer:
    name: str
    event_types: frozenset[str]
    handler: EventHandler
    max_attempts: int = 5
    timeout_seconds: float = 30.0


def _schema(properties: dict[str, object], required: list[str]) -> Mapping[str, object]:
    return MappingProxyType(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }
    )


EVENT_CONTRACTS: Mapping[str, EventContract] = MappingProxyType(
    {
        "business.created": EventContract(
            event_type="business.created",
            schema_version=1,
            aggregate_type="business",
            description="A new owner business workspace was committed.",
            payload_schema=_schema(
                {
                    "business_id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string", "minLength": 1, "maxLength": 120},
                },
                ["business_id", "name"],
            ),
        ),
        "goal.created": EventContract(
            event_type="goal.created",
            schema_version=1,
            aggregate_type="goal",
            description="A selected-business goal was committed.",
            payload_schema=_schema(
                {
                    "goal_id": {"type": "string", "format": "uuid"},
                    "title": {"type": "string", "minLength": 1, "maxLength": 200},
                },
                ["goal_id", "title"],
            ),
        ),
        "task.completed": EventContract(
            event_type="task.completed",
            schema_version=1,
            aggregate_type="task",
            description="A task entered its completed terminal state.",
            payload_schema=_schema(
                {
                    "task_id": {"type": "string", "format": "uuid"},
                    "previous_status": {"type": "string", "minLength": 1, "maxLength": 24},
                },
                ["task_id", "previous_status"],
            ),
        ),
        "task.failed": EventContract(
            event_type="task.failed",
            schema_version=1,
            aggregate_type="task",
            description="A task entered its failed terminal state.",
            payload_schema=_schema(
                {
                    "task_id": {"type": "string", "format": "uuid"},
                    "previous_status": {"type": "string", "minLength": 1, "maxLength": 24},
                    "error": {"type": ["string", "null"], "maxLength": 500},
                },
                ["task_id", "previous_status", "error"],
            ),
        ),
        "approval.requested": EventContract(
            event_type="approval.requested",
            schema_version=1,
            aggregate_type="approval_request",
            description="Governance committed a new owner approval request.",
            payload_schema=_schema(
                {
                    "approval_request_id": {"type": "string", "format": "uuid"},
                    "action_id": {"type": "string", "format": "uuid"},
                    "action_type": {"type": "string", "minLength": 1, "maxLength": 120},
                    "risk_class": {"enum": ["R0", "R1", "R2", "R3", "R4", "R5"]},
                },
                ["approval_request_id", "action_id", "action_type", "risk_class"],
            ),
        ),
    }
)


async def audit_event_handler(_: AsyncSession, event: DomainEvent) -> dict[str, object]:
    contract = EVENT_CONTRACTS.get(event.event_type)
    if contract is None or contract.schema_version != event.schema_version:
        raise EventContractError("The event contract is not registered")
    return {
        "observed": True,
        "event_type": event.event_type,
        "schema_version": event.schema_version,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": event.aggregate_id,
    }


AUDIT_CONSUMER = EventConsumer(
    name="foundora.event-audit.v1",
    event_types=frozenset(EVENT_CONTRACTS),
    handler=audit_event_handler,
    max_attempts=5,
    timeout_seconds=5.0,
)

REGISTERED_CONSUMERS: Mapping[str, EventConsumer] = MappingProxyType(
    {AUDIT_CONSUMER.name: AUDIT_CONSUMER}
)


def consumers_for(
    event_type: str,
    consumers: Mapping[str, EventConsumer] = REGISTERED_CONSUMERS,
) -> tuple[EventConsumer, ...]:
    return tuple(item for item in consumers.values() if event_type in item.event_types)


def validate_event(
    event_type: str,
    schema_version: int,
    aggregate_type: str,
    payload: Mapping[str, object],
) -> EventContract:
    contract = EVENT_CONTRACTS.get(event_type)
    if contract is None:
        raise EventContractError("The event type is not registered")
    if schema_version != contract.schema_version:
        raise EventContractError("The event schema version is not registered")
    if aggregate_type != contract.aggregate_type:
        raise EventContractError("The event aggregate type does not match its contract")
    errors = sorted(
        Draft202012Validator(contract.payload_schema, format_checker=FormatChecker()).iter_errors(
            payload
        ),
        key=str,
    )
    if errors:
        raise EventContractError("The event payload does not match its registered contract")
    return contract
