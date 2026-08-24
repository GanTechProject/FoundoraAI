from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.events.contracts import EVENT_CONTRACTS, REGISTERED_CONSUMERS
from foundora.events.service import (
    EventBusService,
    EventDashboard,
    EventDeliveryNotFound,
    EventRecord,
    EventRedriveConflict,
)
from foundora.models import EventDelivery

router = APIRouter(prefix="/events", tags=["internal event bus"])
DeliveryStatus = Literal["pending", "retry_wait", "processing", "completed", "dead_letter"]


class RedriveDeliveryRequest(BaseModel):
    expected_redrive_count: int = Field(ge=0)


class EventContractView(BaseModel):
    event_type: str
    schema_version: int
    aggregate_type: str
    description: str
    consumer_names: list[str]


class EventDeliveryView(BaseModel):
    id: UUID
    consumer_name: str
    status: DeliveryStatus
    attempt_count: int
    max_attempts: int
    redrive_count: int
    available_at: datetime
    claimed_at: datetime | None
    completed_at: datetime | None
    dead_lettered_at: datetime | None
    last_error_type: str | None
    last_error_message: str | None
    handler_result: dict[str, object] | None
    created_at: datetime
    updated_at: datetime


class DomainEventView(BaseModel):
    id: UUID
    business_id: UUID
    event_type: str
    schema_version: int
    aggregate_type: str
    aggregate_id: str
    idempotency_key: str
    correlation_id: str | None
    causation_event_id: UUID | None
    payload: dict[str, object]
    occurred_at: datetime
    created_at: datetime
    deliveries: list[EventDeliveryView]


class EventDashboardView(BaseModel):
    business_id: UUID
    contracts: list[EventContractView]
    events: list[DomainEventView]
    total_events: int
    limit: int
    offset: int


def _delivery_view(item: EventDelivery) -> EventDeliveryView:
    return EventDeliveryView(
        id=item.id,
        consumer_name=item.consumer_name,
        status=item.status,  # type: ignore[arg-type]
        attempt_count=item.attempt_count,
        max_attempts=item.max_attempts,
        redrive_count=item.redrive_count,
        available_at=item.available_at,
        claimed_at=item.claimed_at,
        completed_at=item.completed_at,
        dead_lettered_at=item.dead_lettered_at,
        last_error_type=item.last_error_type,
        last_error_message=item.last_error_message,
        handler_result=item.handler_result,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _event_view(record: EventRecord) -> DomainEventView:
    item = record.event
    return DomainEventView(
        id=item.id,
        business_id=item.business_id,
        event_type=item.event_type,
        schema_version=item.schema_version,
        aggregate_type=item.aggregate_type,
        aggregate_id=item.aggregate_id,
        idempotency_key=item.idempotency_key,
        correlation_id=item.correlation_id,
        causation_event_id=item.causation_event_id,
        payload=item.payload,
        occurred_at=item.occurred_at,
        created_at=item.created_at,
        deliveries=[_delivery_view(delivery) for delivery in record.deliveries],
    )


def _dashboard_view(record: EventDashboard) -> EventDashboardView:
    return EventDashboardView(
        business_id=record.business_id,
        contracts=[
            EventContractView(
                event_type=contract.event_type,
                schema_version=contract.schema_version,
                aggregate_type=contract.aggregate_type,
                description=contract.description,
                consumer_names=[
                    consumer.name
                    for consumer in REGISTERED_CONSUMERS.values()
                    if contract.event_type in consumer.event_types
                ],
            )
            for contract in EVENT_CONTRACTS.values()
        ],
        events=[_event_view(event) for event in record.events],
        total_events=record.total_events,
        limit=record.limit,
        offset=record.offset,
    )


@router.get("", response_model=EventDashboardView)
async def event_dashboard(
    context: Annotated[AuthContext, Depends(require_auth)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    delivery_status: Annotated[DeliveryStatus | None, Query()] = None,
) -> EventDashboardView:
    record = await EventBusService().dashboard(
        context,
        limit=limit,
        offset=offset,
        delivery_status=delivery_status,
    )
    return _dashboard_view(record)


@router.post("/deliveries/{delivery_id}/redrive", response_model=EventDeliveryView)
async def redrive_delivery(
    delivery_id: UUID,
    payload: RedriveDeliveryRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
    response: Response,
) -> EventDeliveryView:
    try:
        delivery = await EventBusService().redrive(
            context,
            delivery_id,
            expected_redrive_count=payload.expected_redrive_count,
        )
    except EventDeliveryNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found"
        ) from error
    except EventRedriveConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    response.status_code = status.HTTP_202_ACCEPTED
    return _delivery_view(delivery)
