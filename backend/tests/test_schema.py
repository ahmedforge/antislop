"""Real PostgreSQL checks; each test uses its own temporary schema."""
import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Appeal, Channel, Install, ModerationAction, Report


@pytest.fixture
def migrated_db(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL migration tests")
    root = create_engine(url)
    schema = f"test_{uuid4().hex}"
    with root.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated_url = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    monkeypatch.setenv("DATABASE_URL", isolated_url.render_as_string(hide_password=False))
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    engine = create_engine(isolated_url)
    try:
        command.upgrade(config, "head")
        yield engine, config
    finally:
        engine.dispose()
        with root.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root.dispose()


def seed(session):
    channel = Channel(youtube_channel_id="UC" + "a" * 22, handle="@fixture")
    install = Install(id=uuid4())
    session.add_all([channel, install])
    session.flush()
    return channel, install


def test_migration_roundtrip_and_no_model_drift(migrated_db):
    engine, config = migrated_db
    assert set(inspect(engine).get_table_names()) == {
        "alembic_version", "channels", "installs", "reports", "appeals", "moderation_actions"
    }
    command.check(config)
    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT to_regproc('touch_channel_updated_at')")) is None
    command.upgrade(config, "head")
    command.check(config)


def test_defaults_relationships_and_database_timestamp(migrated_db):
    engine, _ = migrated_db
    with Session(engine) as session:
        channel, install = seed(session)
        assert channel.status == "unreviewed"
        assert channel.score == Decimal("0")
        assert install.reputation == Decimal("1")
        assert channel.created_at.utcoffset() is not None
        initial = channel.updated_at
        appeal = Appeal(channel_id=channel.id, reason="Mistaken classification")
        session.add(appeal)
        session.flush()
        session.add_all([
            Report(channel_id=channel.id, install_id=install.id, reason="Explicit report"),
            ModerationAction(channel_id=channel.id, appeal_id=appeal.id,
                             action="reject_appeal", actor="test-admin", reason="Reviewed"),
        ])
        session.flush()
        # Direct SQL exercises the trigger independently of ORM update hooks.
        session.execute(text("UPDATE channels SET status = 'approved' WHERE id = :id"), {"id": channel.id})
        session.refresh(channel)
        assert channel.updated_at > initial
        session.commit()


@pytest.mark.parametrize("case", ["duplicate_channel", "duplicate_report", "orphan_report",
    "negative_score", "nan_score", "negative_reputation", "bad_status", "bad_youtube_id",
    "empty_reason", "unresolved_accepted_appeal", "wrong_channel_appeal", "delete_referenced_channel"])
def test_database_rejects_invalid_data(migrated_db, case):
    engine, _ = migrated_db
    with Session(engine) as session:
        channel, install = seed(session)
        session.add(Report(channel_id=channel.id, install_id=install.id, reason="Original"))
        session.commit()
        with pytest.raises(IntegrityError):
            if case == "duplicate_channel":
                session.add(Channel(youtube_channel_id=channel.youtube_channel_id))
            elif case == "duplicate_report":
                session.add(Report(channel_id=channel.id, install_id=install.id, reason="Duplicate"))
            elif case == "orphan_report":
                session.add(Report(channel_id=uuid4(), install_id=install.id, reason="Orphan"))
            elif case == "negative_score":
                channel.score = Decimal("-1")
            elif case == "nan_score":
                channel.score = Decimal("NaN")
            elif case == "negative_reputation":
                install.reputation = Decimal("-1")
            elif case == "bad_status":
                channel.status = "unknown"
            elif case == "bad_youtube_id":
                channel.youtube_channel_id = "invalid"
            elif case == "empty_reason":
                session.add(Appeal(channel_id=channel.id, reason="   "))
            elif case == "unresolved_accepted_appeal":
                session.add(Appeal(channel_id=channel.id, reason="Appeal", status="accepted"))
            elif case == "wrong_channel_appeal":
                other = Channel(youtube_channel_id="UC" + "b" * 22)
                session.add(other)
                session.flush()
                appeal = Appeal(channel_id=other.id, reason="Appeal")
                session.add(appeal)
                session.flush()
                session.add(ModerationAction(channel_id=channel.id, appeal_id=appeal.id,
                    action="accept_appeal", actor="admin", reason="Wrong channel"))
            elif case == "delete_referenced_channel":
                session.delete(channel)
            session.flush()
        session.rollback()
