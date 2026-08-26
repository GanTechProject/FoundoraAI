from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from foundora.api.auth import require_auth
from foundora.auth.service import AuthContext
from foundora.events.contracts import (
    AUDIT_CONSUMER,
    EventConsumer,
    EventContractError,
    consumers_for,
    validate_event,
)
from foundora.events.service import EventDashboard, EventRecord, deliver_claimed_event
from foundora.main import app
from foundora.models import DomainEvent, EventDelivery, Owner, OwnerSession


def event_records() -> tuple[AuthContext, EventRecord]:
    now = datetime.now(UTC)
    owner = Owner(
        id=uuid.uuid4(),
        singleton_key=1,
        email="owner@example.com",
        password_hash="hash",
        created_at=now,
        updated_at=now,
        password_changed_at=now,
    )
    business_id = uuid.uuid4()
    context = AuthContext(
        owner=owner,
        session=OwnerSession(
            id=uuid.uuid4(),
            owner_id=owner.id,
            token_hash="a" * 64,
            csrf_hash="b" * 64,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(minutes=30),
            expires_at=now + timedelta(hours=8),
            revoked_at=None,
            user_agent="test",
            selected_business_id=business_id,
        ),
    )
    event = DomainEvent(
        id=uuid.uuid4(),
        business_id=business_id,
        event_type="business.created",
        schema_version=1,
        aggregate_type="business",
        aggregate_id=str(business_id),
        idempotency_key=f"business:{business_id}:created",
        correlation_id="request-01",
        causation_event_id=None,
        payload={"business_id": str(business_id), "name": "Foundora Test"},
        occurred_at=now,
        created_at=now,
    )
    delivery = EventDelivery(
        id=uuid.uuid4(),
        event_id=event.id,
        consumer_name=AUDIT_CONSUMER.name,
        status="pending",
        attempt_count=0,
        max_attempts=5,
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
    return context, EventRecord(event=event, deliveries=[delivery])


def database_mock() -> MagicMock:
    database = MagicMock()
    savepoint = MagicMock()
    savepoint.__aenter__ = AsyncMock(return_value=None)
    savepoint.__aexit__ = AsyncMock(return_value=False)
    database.begin_nested.return_value = savepoint
    return database


def test_contract_registry_rejects_unknown_version_aggregate_and_payload() -> None:
    business_id = str(uuid.uuid4())
    contract = validate_event(
        "business.created",
        1,
        "business",
        {"business_id": business_id, "name": "Foundora Test"},
    )
    assert contract.event_type == "business.created"
    assert [item.name for item in consumers_for(contract.event_type)] == [AUDIT_CONSUMER.name]

    with pytest.raises(EventContractError, match="type"):
        validate_event("unknown.created", 1, "unknown", {})
    with pytest.raises(EventContractError, match="version"):
        validate_event(
            "business.created",
            2,
            "business",
            {"business_id": business_id, "name": "Foundora Test"},
        )
    with pytest.raises(EventContractError, match="aggregate"):
        validate_event(
            "business.created",
            1,
            "goal",
            {"business_id": business_id, "name": "Foundora Test"},
        )
    with pytest.raises(EventContractError, match="payload"):
        validate_event("business.created", 1, "business", {"business_id": business_id})
    with pytest.raises(EventContractError, match="payload"):
        validate_event(
            "business.created",
            1,
            "business",
            {"business_id": "not-a-uuid", "name": "Foundora Test"},
        )


@pytest.mark.asyncio
async def test_completed_delivery_is_idempotent() -> None:
    _, record = event_records()
    handler = AsyncMock(return_value={"observed": True})
    consumer = EventConsumer(
        name="test.consumer.v1",
        event_types=frozenset({record.event.event_type}),
        handler=handler,
        max_attempts=3,
    )
    now = datetime.now(UTC)
    record.deliveries[0].consumer_name = consumer.name
    record.deliveries[0].available_at = now

    outcome = await deliver_claimed_event(
        database_mock(), record.deliveries[0], record.event, consumer, now=now
    )
    replay = await deliver_claimed_event(
        database_mock(), record.deliveries[0], record.event, consumer, now=now
    )

    assert outcome == "completed"
    assert replay == "ignored"
    assert record.deliveries[0].status == "completed"
    assert record.deliveries[0].attempt_count == 1
    assert record.deliveries[0].handler_result == {"observed": True}
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_delivery_retries_then_enters_dead_letter() -> None:
    _, record = event_records()
    handler = AsyncMock(side_effect=RuntimeError("raw provider-like secret must not persist"))
    consumer = EventConsumer(
        name="test.failure.v1",
        event_types=frozenset({record.event.event_type}),
        handler=handler,
        max_attempts=2,
    )
    delivery = record.deliveries[0]
    delivery.consumer_name = consumer.name
    delivery.max_attempts = 2
    first = datetime.now(UTC)
    delivery.available_at = first

    first_outcome = await deliver_claimed_event(
        database_mock(), delivery, record.event, consumer, now=first
    )
    assert first_outcome == "retry_wait"
    assert delivery.available_at == first + timedelta(seconds=1)
    assert delivery.last_error_type == "RuntimeError"
    assert "secret" not in (delivery.last_error_message or "")

    second_outcome = await deliver_claimed_event(
        database_mock(),
        delivery,
        record.event,
        consumer,
        now=first + timedelta(seconds=1),
    )
    assert second_outcome == "dead_letter"
    assert delivery.status == "dead_letter"
    assert delivery.attempt_count == 2
    assert delivery.dead_lettered_at == first + timedelta(seconds=1)
    assert handler.await_count == 2


@pytest.mark.asyncio
async def test_handler_timeout_is_a_retryable_sanitized_failure() -> None:
    _, record = event_records()

    async def slow_handler(*_: object) -> dict[str, object]:
        await asyncio.sleep(0.05)
        return {"too_late": True}

    consumer = EventConsumer(
        name="test.timeout.v1",
        event_types=frozenset({record.event.event_type}),
        handler=slow_handler,
        max_attempts=2,
        timeout_seconds=0.001,
    )
    delivery = record.deliveries[0]
    delivery.consumer_name = consumer.name
    delivery.max_attempts = 2
    now = datetime.now(UTC)
    delivery.available_at = now

    outcome = await deliver_claimed_event(
        database_mock(), delivery, record.event, consumer, now=now
    )

    assert outcome == "retry_wait"
    assert delivery.last_error_type == "TimeoutError"
    assert delivery.last_error_message == "The registered event handler failed"


def test_event_dashboard_exposes_registered_contract_and_delivery_state() -> None:
    context, record = event_records()
    dashboard = EventDashboard(
        business_id=record.event.business_id,
        events=[record],
        total_events=1,
        limit=25,
        offset=0,
    )
    app.dependency_overrides[require_auth] = lambda: context
    try:
        with (
            patch(
                "foundora.api.events.EventBusService.dashboard",
                new=AsyncMock(return_value=dashboard),
            ) as load,
            TestClient(app) as client,
        ):
            response = client.get("/events?limit=25&offset=0")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.json()
    assert payload["business_id"] == str(record.event.business_id)
    assert payload["contracts"][0]["consumer_names"] == [AUDIT_CONSUMER.name]
    assert payload["events"][0]["id"] == str(record.event.id)
    assert payload["events"][0]["deliveries"][0]["status"] == "pending"
    load.assert_awaited_once_with(context, limit=25, offset=0, delivery_status=None)


def test_event_dashboard_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.get("/events")
    assert response.status_code == 401
