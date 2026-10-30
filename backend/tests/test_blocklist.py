from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import Channel, ModerationAction
from app.seed import seed_channels


@pytest.fixture
def api(migrated_db):
    engine, _ = migrated_db
    with TestClient(create_app()) as client:
        yield client, engine


def add_channel(engine, letter="a", status="approved", handle="@fixture"):
    with Session(engine) as session:
        channel = Channel(youtube_channel_id="UC" + letter * 22, handle=handle, status=status)
        session.add(channel)
        session.commit()
        return channel.id, channel.youtube_channel_id


def test_full_snapshot_contains_only_approved_and_no_reporter_data(api):
    client, engine = api
    _, approved = add_channel(engine)
    for letter, status in [("b", "pending_review"), ("c", "rejected"), ("d", "unreviewed")]:
        add_channel(engine, letter, status)
    result = client.get("/v1/blocklist")
    assert result.status_code == 200
    data = result.json()
    assert data["full_sync"] is True
    assert [c["youtube_channel_id"] for c in data["channels"]] == [approved]
    assert set(data["channels"][0]) == {"youtube_channel_id", "handle", "updated_at"}
    assert data["removed_channel_ids"] == []
    assert datetime.fromisoformat(data["next_since"]).tzinfo is not None


def test_empty_list_has_stable_cursor_and_conditional_response(api):
    client, _ = api
    first = client.get("/v1/blocklist")
    assert first.json() == {"full_sync": True, "channels": [], "removed_channel_ids": [], "next_since": "1970-01-01T00:00:00Z"}
    second = client.get("/v1/blocklist", headers={"If-None-Match": first.headers["etag"]})
    assert second.status_code == 304
    assert second.content == b""
    assert second.headers["etag"] == first.headers["etag"]
    assert second.headers["cache-control"] == "public, no-cache"


@pytest.mark.parametrize("header_kind", ["exact", "weak", "list", "wildcard"])
def test_etag_revalidation_and_invalidation(api, header_kind):
    client, engine = api
    channel_id, _ = add_channel(engine)
    first = client.get("/v1/blocklist")
    tag = first.headers["etag"]
    header = {"exact": tag, "weak": "W/" + tag, "list": '"unrelated", W/' + tag, "wildcard": "*"}[header_kind]
    assert client.get("/v1/blocklist", headers={"If-None-Match": header}).status_code == 304
    with Session(engine) as session:
        session.get(Channel, channel_id).handle = "@renamed"
        session.commit()
    changed = client.get("/v1/blocklist", headers={"If-None-Match": tag})
    assert changed.status_code == 200
    assert changed.headers["etag"] != tag
    assert changed.json()["channels"][0]["handle"] == "@renamed"


def test_delta_applies_updates_removals_and_inclusive_boundary(api):
    client, engine = api
    first_id, first_youtube_id = add_channel(engine)
    second_id, second_youtube_id = add_channel(engine, "b")
    snapshot = client.get("/v1/blocklist").json()
    # Boundary replay is intentional, so precision loss and timestamp ties don't
    # cause exclusions. Clients upsert/delete by stable YouTube channel ID.
    boundary = client.get("/v1/blocklist", params={"since": snapshot["next_since"]}).json()
    assert second_youtube_id in [c["youtube_channel_id"] for c in boundary["channels"]]
    with Session(engine) as session:
        session.get(Channel, first_id).status = "rejected"
        session.get(Channel, second_id).handle = "@renamed"
        session.commit()
    _, added_id = add_channel(engine, "c")
    delta = client.get("/v1/blocklist", params={"since": snapshot["next_since"]})
    assert delta.status_code == 200
    body = delta.json()
    assert body["full_sync"] is False
    assert body["removed_channel_ids"] == [first_youtube_id]
    assert {c["youtube_channel_id"] for c in body["channels"]} == {second_youtube_id, added_id}
    cache = {c["youtube_channel_id"]: c for c in snapshot["channels"]}
    for _ in range(2):
        for channel in body["channels"]:
            cache[channel["youtube_channel_id"]] = channel
        for removed in body["removed_channel_ids"]:
            cache.pop(removed, None)
    assert cache == {c["youtube_channel_id"]: c for c in client.get("/v1/blocklist").json()["channels"]}
    repeat = client.get("/v1/blocklist", params={"since": snapshot["next_since"]}, headers={"If-None-Match": delta.headers["etag"]})
    assert repeat.status_code == 304


@pytest.mark.parametrize("since", ["garbage", "2026-01-01T00:00:00", "1969-12-31T00:00:00Z", "9999-01-01T00:00:00Z"])
def test_invalid_cursor_is_rejected(api, since):
    client, _ = api
    assert client.get("/v1/blocklist", params={"since": since}).status_code == 422


def test_timezone_offsets_are_equivalent_and_unchanged_rows_are_excluded(api):
    client, engine = api
    add_channel(engine)
    with engine.connect() as connection:
        later = connection.scalar(select(func.clock_timestamp()))
    utc_result = client.get("/v1/blocklist", params={"since": later.isoformat()})
    assert utc_result.json()["channels"] == []
    from datetime import timezone
    other = later.astimezone(timezone(timedelta(hours=5)))
    offset_result = client.get("/v1/blocklist", params={"since": other.isoformat()})
    assert utc_result.content == offset_result.content
    assert utc_result.headers["etag"] == offset_result.headers["etag"]


def test_transaction_started_before_sync_cannot_backdate_an_insert(api):
    client, engine = api
    with engine.begin() as long_transaction:
        started = long_transaction.scalar(select(func.now()))
        add_channel(engine)
        cursor = client.get("/v1/blocklist").json()["next_since"]
        assert datetime.fromisoformat(cursor) > started
        from uuid import uuid4
        long_transaction.execute(text("INSERT INTO channels (id, youtube_channel_id, status) VALUES (:id, :youtube_id, 'approved')"),
                                 {"id": uuid4(), "youtube_id": "UC" + "z" * 22})
    result = client.get("/v1/blocklist", params={"since": cursor})
    assert "UC" + "z" * 22 in [c["youtube_channel_id"] for c in result.json()["channels"]]


def test_snapshot_waits_for_pending_writer_and_includes_commit(api):
    client, engine = api
    channel_id, youtube_id = add_channel(engine)
    started = Event()
    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if statement == "LOCK TABLE channels IN SHARE MODE":
            started.set()
    event.listen(client.app.state.engine, "before_cursor_execute", before_execute)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with engine.begin() as writer:
                writer.execute(text("UPDATE channels SET handle='@committed' WHERE id=:id"), {"id": channel_id})
                future = executor.submit(client.get, "/v1/blocklist")
                assert started.wait(2)
                deadline = time.monotonic() + 2
                # Verify PostgreSQL is actually waiting for this table, not merely
                # that the Python request happened to be slow.
                with engine.connect() as probe:
                    while not probe.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE relation = 'channels'::regclass AND mode = 'ShareLock' AND NOT granted)")):
                        assert time.monotonic() < deadline
                        time.sleep(0.01)
                assert not future.done()
            response = future.result(timeout=5)
        assert response.status_code == 200
        assert response.json()["channels"][0]["youtube_channel_id"] == youtube_id
        assert response.json()["channels"][0]["handle"] == "@committed"
    finally:
        event.remove(client.app.state.engine, "before_cursor_execute", before_execute)


def test_database_failure_returns_retryable_error_without_secrets():
    settings = Settings(database_url="postgresql+psycopg://nobody:secret-password@127.0.0.1:1/missing")
    with TestClient(create_app(settings)) as client:
        response = client.get("/v1/blocklist")
        assert response.status_code == 503
        assert response.headers["retry-after"] == "5"
        assert "secret-password" not in response.text
        assert client.get("/health").status_code == 200


def test_seed_is_idempotent_and_does_not_override_moderation(migrated_db, tmp_path):
    engine, _ = migrated_db
    source = Path(__file__).resolve().parents[1] / "app" / "seed.demo.json"
    assert seed_channels(engine, source) == 1
    assert seed_channels(engine, source) == 0
    with Session(engine) as session:
        channel = session.scalar(select(Channel))
        assert channel.status == "approved"
        assert session.scalar(select(func.count()).select_from(ModerationAction)) == 1
        channel.status = "rejected"
        session.commit()
    assert seed_channels(engine, source) == 0
    with Session(engine) as session:
        assert session.scalar(select(Channel.status)) == "rejected"


@pytest.mark.parametrize("bad_entry", [{"youtube_channel_id": "invalid", "reason": "test"}, {"youtube_channel_id": "UC" + "b" * 22, "reason": " "}])
def test_invalid_seed_file_is_atomic(migrated_db, tmp_path, bad_entry):
    engine, _ = migrated_db
    source = tmp_path / "seed.json"
    source.write_text(json.dumps([{"youtube_channel_id": "UC" + "a" * 22, "reason": "Reviewed"}, bad_entry]))
    with pytest.raises(ValueError):
        seed_channels(engine, source)
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Channel)) == 0
        assert connection.scalar(select(func.count()).select_from(ModerationAction)) == 0
