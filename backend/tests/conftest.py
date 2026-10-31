import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

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



@pytest.fixture
def redis_state(monkeypatch):
    from redis import Redis
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("Set TEST_REDIS_URL to run submission/rate-limit tests")
    client = Redis.from_url(url, decode_responses=True)
    client.ping()
    prefix = f"antislop-test:{uuid4().hex}"
    monkeypatch.setenv("REDIS_URL", url)
    monkeypatch.setenv("RATE_LIMIT_NAMESPACE", prefix)
    try:
        yield client
    finally:
        keys = list(client.scan_iter(match=f"{prefix}:*"))
        if keys:
            client.delete(*keys)
        client.close()
