from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import Appeal, Channel, Install, ModerationAction, Report

CHANNEL = "UC" + "a" * 22


@pytest.fixture
def api(migrated_db, redis_state):
    engine, _ = migrated_db
    with TestClient(create_app()) as client:
        yield client, engine


def payload(**changes):
    return {"install_id": str(uuid4()), "channel_id": CHANNEL, "reason": "Explicit user reason", **changes}


def approved(engine):
    with Session(engine) as session:
        session.add(Channel(youtube_channel_id=CHANNEL, status="approved", handle="@fixture", score=Decimal("7")))
        session.commit()


def count(engine, model):
    with engine.connect() as connection:
        return connection.scalar(select(func.count()).select_from(model))


def test_report_creates_unreviewed_channel_install_and_report_atomically(api):
    client, engine = api
    body = payload(reason="  Repetitive generated narration  ")
    response = client.post("/v1/reports", json=body)
    assert response.status_code == 201
    assert response.json()["created"] is True
    assert response.headers["cache-control"] == "no-store"
    with Session(engine) as session:
        channel = session.scalar(select(Channel))
        assert channel.youtube_channel_id == CHANNEL
        assert channel.status == "unreviewed" and channel.score == Decimal("1")
        assert session.scalar(select(Install)).reputation == Decimal("1")
        report = session.scalar(select(Report))
        assert report.reason == "Repetitive generated narration"
        assert report.channel_id == channel.id
    assert client.get("/v1/blocklist").json()["channels"] == []
    assert count(engine, ModerationAction) == 0


def test_report_retry_keeps_original_reason_and_moderation(api):
    client, engine = api
    approved(engine)
    body = payload()
    first = client.post("/v1/reports", json=body)
    retry = client.post("/v1/reports", json={**body, "reason": "Changed reason"})
    assert first.status_code == 201 and retry.status_code == 200
    assert retry.json() == {"id": first.json()["id"], "created": False}
    assert count(engine, Report) == 1
    with Session(engine) as session:
        assert session.scalar(select(Report.reason)) == body["reason"]
        channel = session.scalar(select(Channel))
        assert channel.status == "approved" and channel.score == Decimal("1")
        assert channel.handle == "@fixture"


@pytest.mark.parametrize("path", ["reports", "appeals"])
def test_concurrent_duplicates_create_exactly_one_submission(api, path):
    client, engine = api
    approved(engine)
    body = payload()
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post(f"/v1/{path}", json=body), range(4)))
    assert sorted(response.status_code for response in responses) == [200, 200, 200, 201]
    assert len({response.json()["id"] for response in responses}) == 1
    assert count(engine, Report if path == "reports" else Appeal) == 1
    assert count(engine, Install) == 1


@pytest.mark.parametrize("changes", [
    {"install_id": "not-a-uuid"}, {"install_id": "00000000-0000-0000-0000-000000000000"},
    {"channel_id": "@handle"}, {"channel_id": str(uuid4())}, {"reason": " \n\t "},
    {"reason": "x" * 2001}, {"reason": 123}, {"video_url": "https://youtube.com/watch?v=private"},
])
@pytest.mark.parametrize("path", ["reports", "appeals"])
def test_invalid_input_writes_nothing(api, path, changes):
    client, engine = api
    response = client.post(f"/v1/{path}", json=payload(**changes))
    assert response.status_code == 422
    assert count(engine, Channel) == count(engine, Install) == count(engine, Report) == count(engine, Appeal) == 0


def test_separate_installs_can_report_same_channel(api):
    client, engine = api
    assert client.post("/v1/reports", json=payload()).status_code == 201
    assert client.post("/v1/reports", json=payload()).status_code == 201
    assert count(engine, Channel) == 1
    assert count(engine, Report) == count(engine, Install) == 2


def test_appeal_stays_open_without_unblocking_and_can_follow_a_resolved_appeal(api):
    client, engine = api
    approved(engine)
    body = payload()
    first = client.post("/v1/appeals", json=body)
    assert first.status_code == 201
    assert len(client.get("/v1/blocklist").json()["channels"]) == 1
    with Session(engine) as session:
        appeal = session.scalar(select(Appeal))
        assert appeal.status == "open" and appeal.resolved_at is None
        assert session.scalar(select(Channel.status)) == "approved"
        appeal.status = "rejected"
        appeal.resolved_at = datetime.now(UTC)
        session.commit()
    second = client.post("/v1/appeals", json=body)
    assert second.status_code == 201 and second.json()["id"] != first.json()["id"]
    assert count(engine, Appeal) == 2
    assert count(engine, ModerationAction) == 0


def test_unknown_or_nonapproved_appeal_creates_no_install(api):
    client, engine = api
    assert client.post("/v1/appeals", json=payload()).status_code == 404
    with Session(engine) as session:
        session.add(Channel(youtube_channel_id=CHANNEL, status="rejected"))
        session.commit()
    assert client.post("/v1/appeals", json=payload()).status_code == 409
    assert count(engine, Install) == count(engine, Appeal) == 0


@pytest.mark.parametrize("path", ["reports", "appeals"])
def test_unavailable_database_is_retryable_and_does_not_expose_credentials(path, redis_state):
    with TestClient(create_app(Settings(database_url="postgresql+psycopg://user:secret@127.0.0.1:1/missing"))) as client:
        response = client.post(f"/v1/{path}", json=payload())
        assert response.status_code == 503
        assert response.headers["retry-after"] == "5"
        assert "secret" not in response.text
