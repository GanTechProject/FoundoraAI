from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.auth.service import AuthContext
from foundora.business.context import resolve_selected_business
from foundora.events.contracts import (
    REGISTERED_CONSUMERS,
    EventConsumer,
    consumers_for,
    validate_event,
)
from foundora.infrastructure.database import get_session_factory
from foundora.logging import correlation_id
from foundora.models import DomainEvent, EventDelivery


class EventConflict(Exception):
    pass


class EventDeliveryNotFound(Exception):
    pass


class EventRedriveConflict(Exception):
    pass


@dataclass(frozen=True)
class EventRecord:
    event: DomainEvent
    deliveries: list[EventDelivery]


@dataclass(frozen=True)
class EventDashboard:
    business_id: uuid.UUID
    events: list[EventRecord]
    total_events: int
    limit: int
    offset: int


@dataclass(frozen=True)
class DispatchSummary:
    completed: int
    retry_scheduled: int
    dead_lettered: int


DeliveryOutcome = Literal["ignored", "completed", "retry_wait", "dead_letter"]


def _now() -> datetime:
    return datetime.now(UTC)


async def publish_event(
    database: AsyncSession,
    *,
    business_id: uuid.UUID,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    idempotency_key: str,
    payload: dict[str, object],
    schema_version: int = 1,
    causation_event_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
    consumers: Mapping[str, EventConsumer] = REGISTERED_CONSUMERS,
) -> DomainEvent:
    validate_event(event_type, schema_version, aggregate_type, payload)
    registered = consumers_for(event_type, consumers)
    if not registered:
        raise EventConflict("The event has no registered consumer")
    existing = await database.scalar(
        select(DomainEvent).where(
            DomainEvent.business_id == business_id,
            DomainEvent.event_type == event_type,
            DomainEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if any(
            (
                existing.schema_version != schema_version,
                existing.aggregate_type != aggregate_type,
                existing.aggregate_id != aggregate_id,
                existing.payload != payload,
                existing.causation_event_id != causation_event_id,
            )
        ):
            raise EventConflict("The event idempotency key was reused for different data")
        return existing

    now = _now()
    request_correlation_id = correlation_id.get()
    event = DomainEvent(
        id=uuid.uuid4(),
        business_id=business_id,
        event_type=event_type,
        schema_version=schema_version,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        idempotency_key=idempotency_key,
        correlation_id=request_correlation_id if request_correlation_id != "-" else None,
        causation_event_id=causation_event_id,
        payload=payload,
        occurred_at=occurred_at or now,
        created_at=now,
    )
    database.add(event)
    await database.flush()
    database.add_all(
        [
            EventDelivery(
                id=uuid.uuid4(),
                event_id=event.id,
                consumer_name=consumer.name,
                status="pending",
                attempt_count=0,
                max_attempts=consumer.max_attempts,
                redrive_count=0,
                available_at=now,
                claimed_at=None,
                completed_at=None,
                dead_lettered_at=None,
                last_error_type=None,
                last_error_message=None,
                handler_result=None,
                created_at=now,
                updated_at=now,
            )
            for consumer in registered
        ]
    )
    await database.flush()
    return event


class EventBusService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def dashboard(
        self,
        context: AuthContext,
        *,
        limit: int = 100,
        offset: int = 0,
        delivery_status: str | None = None,
    ) -> EventDashboard:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            event_filter = [DomainEvent.business_id == business.id]
            if delivery_status is not None:
                event_filter.append(
                    DomainEvent.id.in_(
                        select(EventDelivery.event_id).where(
                            EventDelivery.status == delivery_status
                        )
                    )
                )
            total = int(
                await database.scalar(
                    select(func.count()).select_from(DomainEvent).where(*event_filter)
                )
                or 0
            )
            events = list(
                await database.scalars(
                    select(DomainEvent)
                    .where(*event_filter)
                    .order_by(desc(DomainEvent.occurred_at), desc(DomainEvent.id))
                    .limit(limit)
                    .offset(offset)
                )
            )
            event_ids = [event.id for event in events]
            deliveries = (
                list(
                    await database.scalars(
                        select(EventDelivery)
                        .where(EventDelivery.event_id.in_(event_ids))
                        .order_by(EventDelivery.consumer_name)
                    )
                )
                if event_ids
                else []
            )
            by_event: dict[uuid.UUID, list[EventDelivery]] = {
                event_id: [] for event_id in event_ids
            }
            for delivery in deliveries:
                by_event[delivery.event_id].append(delivery)
            return EventDashboard(
                business_id=business.id,
                events=[EventRecord(event, by_event[event.id]) for event in events],
                total_events=total,
                limit=limit,
                offset=offset,
            )

    async def redrive(
        self,
        context: AuthContext,
        delivery_id: uuid.UUID,
        *,
        expected_redrive_count: int,
    ) -> EventDelivery:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                delivery = await database.scalar(
                    select(EventDelivery)
                    .join(DomainEvent, DomainEvent.id == EventDelivery.event_id)
                    .where(
                        EventDelivery.id == delivery_id,
                        DomainEvent.business_id == business.id,
                    )
                    .with_for_update()
                )
                if delivery is None:
                    raise EventDeliveryNotFound
                if delivery.status != "dead_letter":
                    raise EventRedriveConflict("Only dead-letter deliveries can be redriven")
                if delivery.redrive_count != expected_redrive_count:
                    raise EventRedriveConflict("The delivery changed; reload before retrying")
                now = _now()
                delivery.status = "pending"
                delivery.attempt_count = 0
                delivery.redrive_count += 1
                delivery.available_at = now
                delivery.claimed_at = None
                delivery.completed_at = None
                delivery.dead_lettered_at = None
                delivery.last_error_type = None
                delivery.last_error_message = None
                delivery.handler_result = None
                delivery.updated_at = now
            return delivery


async def deliver_claimed_event(
    database: AsyncSession,
    delivery: EventDelivery,
    event: DomainEvent | None,
    consumer: EventConsumer | None,
    *,
    now: datetime | None = None,
) -> DeliveryOutcome:
    claimed_at = now or _now()
    if delivery.status not in {"pending", "retry_wait"}:
        return "ignored"
    if delivery.available_at > claimed_at or delivery.attempt_count >= delivery.max_attempts:
        return "ignored"
    delivery.status = "processing"
    delivery.attempt_count += 1
    delivery.claimed_at = claimed_at
    delivery.updated_at = claimed_at
    try:
        if event is None:
            raise EventDeliveryNotFound
        if consumer is None or event.event_type not in consumer.event_types:
            raise EventContractErrorForDelivery
        async with asyncio.timeout(consumer.timeout_seconds):
            async with database.begin_nested():
                result = await consumer.handler(database, event)
                serialized_result = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
                if len(serialized_result.encode("utf-8")) > 65_536:
                    raise EventContractErrorForDelivery
    except Exception as error:
        delivery.handler_result = None
        delivery.last_error_type = type(error).__name__[:80]
        delivery.last_error_message = "The registered event handler failed"
        delivery.completed_at = None
        if delivery.attempt_count >= delivery.max_attempts:
            delivery.status = "dead_letter"
            delivery.dead_lettered_at = claimed_at
            delivery.updated_at = claimed_at
            return "dead_letter"
        delay_seconds = min(2 ** (delivery.attempt_count - 1), 300)
        delivery.status = "retry_wait"
        delivery.available_at = claimed_at + timedelta(seconds=delay_seconds)
        delivery.updated_at = claimed_at
        return "retry_wait"
    delivery.status = "completed"
    delivery.handler_result = result
    delivery.last_error_type = None
    delivery.last_error_message = None
    delivery.completed_at = claimed_at
    delivery.dead_lettered_at = None
    delivery.updated_at = claimed_at
    return "completed"


async def dispatch_pending_events(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    consumers: Mapping[str, EventConsumer] = REGISTERED_CONSUMERS,
    limit: int = 100,
) -> DispatchSummary:
    factory = session_factory or get_session_factory()
    completed = 0
    retry_scheduled = 0
    dead_lettered = 0
    for _ in range(limit):
        processed = False
        async with factory() as database:
            async with database.begin():
                now = _now()
                delivery = await database.scalar(
                    select(EventDelivery)
                    .where(
                        EventDelivery.status.in_(("pending", "retry_wait")),
                        EventDelivery.available_at <= now,
                        EventDelivery.attempt_count < EventDelivery.max_attempts,
                    )
                    .order_by(EventDelivery.available_at, EventDelivery.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if delivery is None:
                    break
                processed = True
                event = await database.get(DomainEvent, delivery.event_id)
                consumer = consumers.get(delivery.consumer_name)
                outcome = await deliver_claimed_event(database, delivery, event, consumer, now=now)
                if outcome == "completed":
                    completed += 1
                elif outcome == "retry_wait":
                    retry_scheduled += 1
                elif outcome == "dead_letter":
                    dead_lettered += 1
        if not processed:
            break
    return DispatchSummary(
        completed=completed,
        retry_scheduled=retry_scheduled,
        dead_lettered=dead_lettered,
    )


class EventContractErrorForDelivery(Exception):
    pass
