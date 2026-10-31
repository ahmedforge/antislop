from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import Channel, Report
from app.rate_limit import bucket_keys, consume


def body():
    return {"install_id": str(uuid4()), "channel_id": "UC" + "a" * 22, "reason": "Synthetic test"}


def settings(**changes):
    return Settings(rate_limit_install_capacity=2, rate_limit_install_refill_seconds=60,
                    rate_limit_ip_capacity=3, rate_limit_ip_refill_seconds=60, **changes)


def test_install_and_ip_limits_are_independent_and_atomic(redis_state):
    config = settings()
    install = str(uuid4())
    assert consume(redis_state, config, install, "192.0.2.1") == 0
    assert consume(redis_state, config, install, "192.0.2.1") == 0
    assert 1 <= consume(redis_state, config, install, "192.0.2.2") <= 60
    # Rejected install does not consume or create the second IP's bucket.
    assert not redis_state.exists(bucket_keys(config, install, "192.0.2.2")[1])
    assert consume(redis_state, config, str(uuid4()), "192.0.2.1") == 0
    new_install = str(uuid4())
    assert consume(redis_state, config, new_install, "192.0.2.1") > 0
    assert not redis_state.exists(bucket_keys(config, new_install, "192.0.2.1")[0])


def test_refill_fraction_and_retry_after_uses_slowest_bucket(redis_state):
    config = settings()
    install = str(uuid4())
    keys = bucket_keys(config, install, "192.0.2.1")
    seconds, micros = redis_state.time()
    now = seconds + micros / 1e6
    # Install needs 30 seconds for a token; IP needs 45 seconds.
    redis_state.hset(keys[0], mapping={"tokens": 0, "updated": now - 30})
    redis_state.hset(keys[1], mapping={"tokens": 0, "updated": now - 15})
    assert 43 <= consume(redis_state, config, install, "192.0.2.1") <= 45
    for key in keys:
        redis_state.hset(key, mapping={"tokens": 0, "updated": now - 61})
    assert consume(redis_state, config, install, "192.0.2.1") == 0
    assert consume(redis_state, config, install, "192.0.2.1") > 0


def test_refill_caps_at_capacity_and_keys_expire(redis_state):
    config = settings()
    install = str(uuid4())
    keys = bucket_keys(config, install, "192.0.2.1")
    for key in keys:
        redis_state.hset(key, mapping={"tokens": 0, "updated": 1})
    assert consume(redis_state, config, install, "192.0.2.1") == 0
    assert float(redis_state.hget(keys[0], "tokens")) == 1
    assert 0 < redis_state.pttl(keys[0]) <= 120_000
    assert consume(redis_state, config, install, "192.0.2.1") == 0
    assert consume(redis_state, config, install, "192.0.2.1") > 0


def test_parallel_requests_cannot_overspend(redis_state):
    config = settings()
    install = str(uuid4())
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: consume(redis_state, config, install, "192.0.2.1"), range(24)))
    assert results.count(0) == 2


def test_ip_canonicalization(redis_state):
    config = settings()
    assert bucket_keys(config, "id", "::ffff:192.0.2.1")[1] == bucket_keys(config, "id", "192.0.2.1")[1]
    assert bucket_keys(config, "id", "2001:db8::1")[1] == bucket_keys(config, "id", "2001:0db8:0:0:0:0:0:1")[1]


def test_api_429_precedes_writes_and_limits_are_shared_between_routes(migrated_db, redis_state):
    engine, _ = migrated_db
    with Session(engine) as session:
        session.add(Channel(youtube_channel_id="UC" + "a" * 22, status="approved"))
        session.commit()
    payload = body()
    with TestClient(create_app(settings())) as client:
        assert client.post("/v1/reports", json=payload).status_code == 201
        assert client.post("/v1/appeals", json=payload).status_code == 201
        response = client.post("/v1/reports", json=payload)
        assert response.status_code == 429
        assert 1 <= int(response.headers["retry-after"]) <= 60
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/health").status_code == 200
        assert client.get("/v1/blocklist").status_code == 200
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Report)) == 1


def test_ip_quota_shared_across_app_instances_and_forwarded_header_cannot_bypass(migrated_db, redis_state):
    config = settings()
    with TestClient(create_app(config), client=("192.0.2.1", 1000)) as first, TestClient(create_app(config), client=("192.0.2.1", 1001)) as second:
        for index in range(3):
            assert first.post("/v1/reports", json=body()).status_code == 201
        response = second.post("/v1/reports", json=body(), headers={"X-Forwarded-For":"198.51.100.2", "Forwarded":"for=198.51.100.3"})
        assert response.status_code == 429
    with TestClient(create_app(config), client=("192.0.2.2", 1000)) as other:
        assert other.post("/v1/reports", json=body()).status_code == 201


def test_redis_failure_blocks_writes_but_not_reads(migrated_db):
    engine, _ = migrated_db
    config = Settings(redis_url="redis://127.0.0.1:1/0")
    with TestClient(create_app(config)) as client:
        response = client.post("/v1/reports", json=body())
        assert response.status_code == 503
        assert response.headers["retry-after"] == "5"
        assert client.get("/health").status_code == 200
        assert client.get("/v1/blocklist").status_code == 200
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Report)) == 0
        assert connection.scalar(select(func.count()).select_from(Channel)) == 0


@pytest.mark.parametrize("changes", [{"rate_limit_install_capacity":0}, {"rate_limit_ip_refill_seconds":0}, {"rate_limit_install_refill_seconds":float("nan")}])
def test_invalid_config_rejected(changes):
    with pytest.raises(ValueError):
        Settings(**changes)
