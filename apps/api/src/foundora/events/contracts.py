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
        "strategy.approved": EventContract(
            event_type="strategy.approved",
            schema_version=1,
            aggregate_type="business_strategy",
            description="A validated proposed strategy received explicit founder approval.",
            payload_schema=_schema(
                {
                    "business_id": {"type": "string", "format": "uuid"},
                    "strategy_version": {"type": "integer", "minimum": 1},
                    "source_agent_run_id": {"type": "string", "format": "uuid"},
                    "context_id": {
                        "type": "string",
                        "pattern": "^[a-f0-9]{64}$",
                    },
                },
                [
                    "business_id",
                    "strategy_version",
                    "source_agent_run_id",
                    "context_id",
                ],
            ),
        ),
        "product_offer.approved": EventContract(
            event_type="product_offer.approved",
            schema_version=1,
            aggregate_type="product_offer_portfolio",
            description=(
                "A validated product and offer proposal received explicit founder approval."
            ),
            payload_schema=_schema(
                {
                    "business_id": {"type": "string", "format": "uuid"},
                    "portfolio_id": {"type": "string", "format": "uuid"},
                    "portfolio_version": {"type": "integer", "minimum": 1},
                    "source_agent_run_id": {"type": "string", "format": "uuid"},
                    "source_strategy_version": {"type": "integer", "minimum": 1},
                    "context_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                },
                [
                    "business_id",
                    "portfolio_id",
                    "portfolio_version",
                    "source_agent_run_id",
                    "source_strategy_version",
                    "context_id",
                ],
            ),
        ),
        "brand.approved": EventContract(
            event_type="brand.approved",
            schema_version=1,
            aggregate_type="brand_system",
            description="A validated brand-system proposal received explicit founder approval.",
            payload_schema=_schema(
                {
                    "business_id": {"type": "string", "format": "uuid"},
                    "brand_system_id": {"type": "string", "format": "uuid"},
                    "brand_version": {"type": "integer", "minimum": 1},
                    "source_agent_run_id": {"type": "string", "format": "uuid"},
                    "source_strategy_version": {"type": "integer", "minimum": 1},
                    "source_product_offer_id": {"type": "string", "format": "uuid"},
                    "source_product_offer_version": {"type": "integer", "minimum": 1},
                    "context_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                },
                [
                    "business_id",
                    "brand_system_id",
                    "brand_version",
                    "source_agent_run_id",
                    "source_strategy_version",
                    "source_product_offer_id",
                    "source_product_offer_version",
                    "context_id",
                ],
            ),
        ),
        "website_specification.approved": EventContract(
            event_type="website_specification.approved",
            schema_version=1,
            aggregate_type="website_specification",
            description=("A complete website specification received explicit founder approval."),
            payload_schema=_schema(
                {
                    "business_id": {"type": "string", "format": "uuid"},
                    "website_specification_id": {"type": "string", "format": "uuid"},
                    "website_specification_version": {"type": "integer", "minimum": 1},
                    "source_agent_run_id": {"type": "string", "format": "uuid"},
                    "source_strategy_version": {"type": "integer", "minimum": 1},
                    "source_product_offer_id": {"type": "string", "format": "uuid"},
                    "source_product_offer_version": {"type": "integer", "minimum": 1},
                    "source_brand_system_id": {"type": "string", "format": "uuid"},
                    "source_brand_version": {"type": "integer", "minimum": 1},
                    "context_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                },
                [
                    "business_id",
                    "website_specification_id",
                    "website_specification_version",
                    "source_agent_run_id",
                    "source_strategy_version",
                    "source_product_offer_id",
                    "source_product_offer_version",
                    "source_brand_system_id",
                    "source_brand_version",
                    "context_id",
                ],
            ),
        ),
        "knowledge.source_registered": EventContract(
            event_type="knowledge.source_registered",
            schema_version=1,
            aggregate_type="knowledge_source",
            description="A selected-business knowledge source was registered.",
            payload_schema=_schema(
                {
                    "source_id": {"type": "string", "format": "uuid"},
                    "source_type": {"enum": ["upload", "reference"]},
                    "title": {"type": "string", "minLength": 1, "maxLength": 200},
                },
                ["source_id", "source_type", "title"],
            ),
        ),
        "knowledge.document_indexed": EventContract(
            event_type="knowledge.document_indexed",
            schema_version=1,
            aggregate_type="knowledge_document",
            description="An uploaded knowledge document was extracted, chunked, and indexed.",
            payload_schema=_schema(
                {
                    "source_id": {"type": "string", "format": "uuid"},
                    "document_id": {"type": "string", "format": "uuid"},
                    "filename": {"type": "string", "minLength": 1, "maxLength": 255},
                    "content_sha256": {
                        "type": "string",
                        "pattern": "^[a-f0-9]{64}$",
                    },
                    "chunk_count": {"type": "integer", "minimum": 1},
                },
                ["source_id", "document_id", "filename", "content_sha256", "chunk_count"],
            ),
        ),
        "knowledge.source_invalidated": EventContract(
            event_type="knowledge.source_invalidated",
            schema_version=1,
            aggregate_type="knowledge_source",
            description="A source and its currently indexed documents were invalidated.",
            payload_schema=_schema(
                {
                    "source_id": {"type": "string", "format": "uuid"},
                    "revision": {"type": "integer", "minimum": 2},
                    "invalidated_document_count": {"type": "integer", "minimum": 0},
                },
                ["source_id", "revision", "invalidated_document_count"],
            ),
        ),
        "knowledge.document_invalidated": EventContract(
            event_type="knowledge.document_invalidated",
            schema_version=1,
            aggregate_type="knowledge_document",
            description="One indexed knowledge document was invalidated.",
            payload_schema=_schema(
                {
                    "source_id": {"type": "string", "format": "uuid"},
                    "document_id": {"type": "string", "format": "uuid"},
                    "revision": {"type": "integer", "minimum": 2},
                },
                ["source_id", "document_id", "revision"],
            ),
        ),
        "memory.proposed": EventContract(
            event_type="memory.proposed",
            schema_version=1,
            aggregate_type="memory_proposal",
            description="The curator committed a selected-business memory proposal.",
            payload_schema=_schema(
                {
                    "proposal_id": {"type": "string", "format": "uuid"},
                    "memory_type": {
                        "enum": [
                            "working",
                            "episodic",
                            "semantic",
                            "decision",
                            "preference",
                            "workflow",
                            "evaluation",
                        ]
                    },
                    "epistemic_status": {
                        "enum": [
                            "observation",
                            "assumption",
                            "fact",
                            "decision",
                            "preference",
                            "procedure",
                            "evaluation",
                        ]
                    },
                    "acceptance_route": {"enum": ["founder", "automatic"]},
                },
                ["proposal_id", "memory_type", "epistemic_status", "acceptance_route"],
            ),
        ),
        "memory.accepted": EventContract(
            event_type="memory.accepted",
            schema_version=1,
            aggregate_type="memory_record",
            description="A curated proposal became durable selected-business memory.",
            payload_schema=_schema(
                {
                    "proposal_id": {"type": "string", "format": "uuid"},
                    "memory_id": {"type": "string", "format": "uuid"},
                    "memory_type": {"type": "string", "minLength": 1, "maxLength": 24},
                    "epistemic_status": {"type": "string", "minLength": 1, "maxLength": 24},
                    "revision": {"type": "integer", "minimum": 1},
                    "accepted_via": {"enum": ["founder", "automatic"]},
                },
                [
                    "proposal_id",
                    "memory_id",
                    "memory_type",
                    "epistemic_status",
                    "revision",
                    "accepted_via",
                ],
            ),
        ),
        "memory.merged": EventContract(
            event_type="memory.merged",
            schema_version=1,
            aggregate_type="memory_record",
            description="An accepted exact duplicate merged into revisioned memory provenance.",
            payload_schema=_schema(
                {
                    "proposal_id": {"type": "string", "format": "uuid"},
                    "memory_id": {"type": "string", "format": "uuid"},
                    "memory_type": {"type": "string", "minLength": 1, "maxLength": 24},
                    "epistemic_status": {"type": "string", "minLength": 1, "maxLength": 24},
                    "revision": {"type": "integer", "minimum": 2},
                    "accepted_via": {"enum": ["founder", "automatic"]},
                },
                [
                    "proposal_id",
                    "memory_id",
                    "memory_type",
                    "epistemic_status",
                    "revision",
                    "accepted_via",
                ],
            ),
        ),
        "memory.invalidated": EventContract(
            event_type="memory.invalidated",
            schema_version=1,
            aggregate_type="memory_record",
            description="A stale selected-business memory was explicitly invalidated.",
            payload_schema=_schema(
                {
                    "memory_id": {"type": "string", "format": "uuid"},
                    "memory_type": {"type": "string", "minLength": 1, "maxLength": 24},
                    "revision": {"type": "integer", "minimum": 2},
                },
                ["memory_id", "memory_type", "revision"],
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
