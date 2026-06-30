"""Escalation policies: the engine (due steps, ordering, ack/delay) and the API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.models.host import Host, Item, ItemValueType
from app.core.models.notification_channel import ChannelType, NotificationChannel
from app.core.models.problem_event import ProblemEvent
from app.core.models.trigger import Severity, Trigger, TriggerOperator
from app.core.schemas.escalation import EscalationPolicyCreate, EscalationStepCreate
from app.core.services.escalation_service import EscalationService

NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
_FORM_HEADERS = {"content-type": "application/x-www-form-urlencoded"}


async def _channel(session: Any, owner_id: Any, name: str) -> NotificationChannel:
    ch = NotificationChannel(
        name=name,
        type=ChannelType.WEBHOOK,
        config={"url": f"https://hook.invalid/{name}"},
        owner_id=owner_id,
        min_severity=Severity.INFO,
    )
    session.add(ch)
    await session.flush()
    return ch


async def _trigger(session: Any, owner_id: Any) -> Trigger:
    host = Host(name="h", owner_id=owner_id)
    session.add(host)
    await session.flush()
    item = Item(host_id=host.id, key="cpu", name="CPU", value_type=ItemValueType.FLOAT, interval=60)
    session.add(item)
    await session.flush()
    trig = Trigger(
        item_id=item.id,
        name="hot",
        operator=TriggerOperator.GT,
        threshold=80.0,
        severity=Severity.HIGH,
    )
    session.add(trig)
    await session.flush()
    return trig


async def _problem(
    session: Any, owner_id: Any, trigger_id: Any, started_at: datetime, **kw: Any
) -> ProblemEvent:
    pe = ProblemEvent(
        trigger_id=trigger_id,
        owner_id=owner_id,
        subject="h / cpu",
        trigger_name="hot",
        severity=Severity.HIGH,
        value=95.0,
        started_at=started_at,
        **kw,
    )
    session.add(pe)
    await session.flush()
    return pe


async def _policy(session: Any, owner_id: Any, steps: list[tuple[int, int, Any]]) -> None:
    await EscalationService(session).create(
        owner_id,
        EscalationPolicyCreate(
            name="oncall",
            steps=[
                EscalationStepCreate(step_order=o, delay_minutes=d, channel_id=c)
                for o, d, c in steps
            ],
        ),
    )


async def test_due_escalations_fire_in_order_then_stop(session: Any, user: Any) -> None:
    ch_a = await _channel(session, user.id, "team")
    ch_b = await _channel(session, user.id, "oncall")
    trig = await _trigger(session, user.id)
    await _policy(session, user.id, [(1, 0, ch_a.id), (2, 5, ch_b.id)])
    pe = await _problem(session, user.id, trig.id, NOW - timedelta(minutes=6))
    await session.commit()

    svc = EscalationService(session)
    deliveries = await svc.due_escalations(NOW)
    assert sorted(d[0].step_order for d in deliveries) == [1, 2]
    assert {d[1].name for d in deliveries} == {"team", "oncall"}
    await session.refresh(pe)
    assert pe.escalated_step == 2
    # Already escalated → nothing new.
    assert await svc.due_escalations(NOW) == []


async def test_due_escalations_respect_step_delays(session: Any, user: Any) -> None:
    ch_a = await _channel(session, user.id, "team")
    ch_b = await _channel(session, user.id, "oncall")
    trig = await _trigger(session, user.id)
    await _policy(session, user.id, [(1, 0, ch_a.id), (2, 5, ch_b.id)])
    pe = await _problem(session, user.id, trig.id, NOW - timedelta(minutes=2))
    await session.commit()

    svc = EscalationService(session)
    first = await svc.due_escalations(NOW)  # elapsed 2m → step 1 only
    assert [d[0].step_order for d in first] == [1]
    await session.refresh(pe)
    assert pe.escalated_step == 1

    later = await svc.due_escalations(NOW + timedelta(minutes=4))  # elapsed 6m → step 2
    assert [d[0].step_order for d in later] == [2]


async def test_acknowledged_problem_is_not_escalated(session: Any, user: Any) -> None:
    ch_a = await _channel(session, user.id, "team")
    trig = await _trigger(session, user.id)
    await _policy(session, user.id, [(1, 0, ch_a.id)])
    await _problem(
        session,
        user.id,
        trig.id,
        NOW - timedelta(minutes=30),
        acknowledged_at=NOW - timedelta(minutes=20),
    )
    await session.commit()
    assert await EscalationService(session).due_escalations(NOW) == []


async def test_escalation_api_crud_and_channel_validation(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: Any, user: Any
) -> None:
    ch = await _channel(session, user.id, "team")
    await session.commit()

    created = await client.post(
        "/api/escalation-policies",
        headers=auth_headers,
        json={
            "name": "oncall",
            "steps": [{"step_order": 1, "delay_minutes": 0, "channel_id": str(ch.id)}],
        },
    )
    assert created.status_code == 201, created.text
    policy_id = created.json()["id"]
    assert created.json()["steps"][0]["channel_id"] == str(ch.id)

    # A channel the caller does not own is rejected.
    foreign = await client.post(
        "/api/escalation-policies",
        headers=auth_headers,
        json={
            "name": "bad",
            "steps": [{"step_order": 1, "delay_minutes": 0, "channel_id": str(uuid.uuid4())}],
        },
    )
    assert foreign.status_code == 422

    listed = await client.get("/api/escalation-policies", headers=auth_headers)
    assert [p["id"] for p in listed.json()] == [policy_id]

    deleted = await client.delete(f"/api/escalation-policies/{policy_id}", headers=auth_headers)
    assert deleted.status_code == 204


async def test_escalation_web_create_list_delete(
    web_client: httpx.AsyncClient, session: Any, user: Any
) -> None:
    ch = await _channel(session, user.id, "team")
    await session.commit()

    body = urlencode(
        [
            ("name", "oncall"),
            ("is_enabled", "on"),
            ("delay_minutes", "0"),
            ("channel_id", str(ch.id)),
            ("delay_minutes", "5"),
            ("channel_id", ""),  # empty channel row is ignored
        ]
    )
    created = await web_client.post("/escalation/new", content=body, headers=_FORM_HEADERS)
    assert created.status_code in (200, 303)

    policies = list(await EscalationService(session).list_for_owner(user.id))
    assert [p.name for p in policies] == ["oncall"]
    assert len(policies[0].steps) == 1  # only the row with a channel

    page = await web_client.get("/escalation")
    assert "oncall" in page.text
    assert "team" in page.text

    deleted = await web_client.post(f"/escalation/{policies[0].id}/delete")
    assert deleted.status_code in (200, 303)
    assert list(await EscalationService(session).list_for_owner(user.id)) == []


async def test_escalation_web_requires_a_step(
    web_client: httpx.AsyncClient, session: Any, user: Any
) -> None:
    body = urlencode([("name", "empty"), ("delay_minutes", "0"), ("channel_id", "")])
    resp = await web_client.post("/escalation/new", content=body, headers=_FORM_HEADERS)
    assert resp.status_code == 422
    assert "at least one step" in resp.text.lower()


async def test_remediation_step_emits_remediation_event(session: Any, user: Any) -> None:
    hook = await _channel(session, user.id, "automation")  # webhook
    trig = await _trigger(session, user.id)
    await EscalationService(session).create(
        user.id,
        EscalationPolicyCreate(
            name="auto",
            steps=[
                EscalationStepCreate(
                    step_order=1,
                    delay_minutes=0,
                    channel_id=hook.id,
                    action_command="restart nginx",
                )
            ],
        ),
    )
    await _problem(session, user.id, trig.id, NOW - timedelta(minutes=1))
    await session.commit()

    deliveries = await EscalationService(session).due_escalations(NOW)
    assert len(deliveries) == 1
    event, _channel_obj = deliveries[0]
    assert event.is_remediation
    assert event.action_command == "restart nginx"
    payload = event.payload()
    assert payload["event"] == "remediation"
    assert payload["action"]["command"] == "restart nginx"


async def test_remediation_step_skipped_for_non_webhook_channel(session: Any, user: Any) -> None:
    email = NotificationChannel(
        name="inbox",
        type=ChannelType.EMAIL,
        config={"to": "ops@x.io"},
        owner_id=user.id,
        min_severity=Severity.INFO,
    )
    session.add(email)
    await session.flush()
    trig = await _trigger(session, user.id)
    await EscalationService(session).create(
        user.id,
        EscalationPolicyCreate(
            name="bad-auto",
            steps=[
                EscalationStepCreate(
                    step_order=1, delay_minutes=0, channel_id=email.id, action_command="rm -rf"
                )
            ],
        ),
    )
    pe = await _problem(session, user.id, trig.id, NOW - timedelta(minutes=1))
    await session.commit()

    # The engine refuses to send a remediation to an inbox, but still advances the
    # step so it is not retried every minute.
    assert await EscalationService(session).due_escalations(NOW) == []
    await session.refresh(pe)
    assert pe.escalated_step == 1


async def test_api_rejects_remediation_on_non_webhook(
    client: httpx.AsyncClient, auth_headers: dict[str, str], session: Any, user: Any
) -> None:
    email = NotificationChannel(
        name="inbox",
        type=ChannelType.EMAIL,
        config={"to": "ops@x.io"},
        owner_id=user.id,
        min_severity=Severity.INFO,
    )
    session.add(email)
    await session.commit()

    resp = await client.post(
        "/api/escalation-policies",
        headers=auth_headers,
        json={
            "name": "bad",
            "steps": [
                {
                    "step_order": 1,
                    "delay_minutes": 0,
                    "channel_id": str(email.id),
                    "action_command": "restart",
                }
            ],
        },
    )
    assert resp.status_code == 422
    assert "webhook" in resp.text.lower()


async def test_due_escalations_skip_foreign_owner_channel(session: Any, user: Any) -> None:
    from app.core.models.user import AuthProvider, User
    from app.core.security.passwords import hash_password

    bob = User(
        email="bob@example.com",
        full_name="Bob",
        auth_provider=AuthProvider.LOCAL,
        password_hash=hash_password("bob-secret-password"),
        is_active=True,
    )
    session.add(bob)
    await session.flush()
    bob_channel = NotificationChannel(
        name="bob-hook",
        type=ChannelType.WEBHOOK,
        config={"url": "https://hook.invalid/bob"},
        owner_id=bob.id,
        min_severity=Severity.INFO,
    )
    session.add(bob_channel)
    await session.flush()

    trig = await _trigger(session, user.id)
    # Force a policy that targets another owner's channel (the API would reject this).
    await EscalationService(session).create(
        user.id,
        EscalationPolicyCreate(
            name="leaky",
            steps=[EscalationStepCreate(step_order=1, delay_minutes=0, channel_id=bob_channel.id)],
        ),
    )
    await _problem(session, user.id, trig.id, NOW - timedelta(minutes=1))
    await session.commit()

    # The engine must not route user A's problem through user B's channel.
    assert await EscalationService(session).due_escalations(NOW) == []
