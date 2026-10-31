from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import Appeal, Channel, Install, ModerationAction

KEY = "test-admin-key-" + "x" * 32
HEADERS = {"X-Admin-Key": KEY}
CHANNEL = "UC" + "m" * 22


@pytest.fixture
def api(migrated_db, redis_state):
    engine, _ = migrated_db
    settings = Settings(admin_api_key=KEY, rate_limit_ip_capacity=100, rate_limit_install_capacity=100)
    with TestClient(create_app(settings)) as client:
        yield client, engine


def report(client, install_id=None):
    return client.post('/v1/reports', json={"install_id": str(install_id or uuid4()),
                                          "channel_id": CHANNEL, "reason": "Generated narration"})


def channel(engine):
    with Session(engine) as session:
        return session.scalar(select(Channel))


def decision(client, identifier, action="approve"):
    return client.post(f'/v1/admin/channels/{identifier}/decision', headers=HEADERS,
                       json={"action": action, "reason": "Manually reviewed evidence"})


def appeal(client):
    response = client.post('/v1/appeals', json={"install_id": str(uuid4()), "channel_id": CHANNEL,
                                             "reason": "Original human work"})
    assert response.status_code == 201
    return response.json()['id']


def resolve(client, identifier, action="accept"):
    return client.post(f'/v1/admin/appeals/{identifier}/decision', headers=HEADERS,
                       json={"action": action, "reason": "Reviewed creator evidence"})


def test_weighted_threshold_duplicates_and_manual_status_are_preserved(api):
    client, engine = api
    trusted, zero = uuid4(), uuid4()
    with Session(engine) as session:
        session.add_all([Install(id=trusted, reputation=Decimal('4.5')), Install(id=zero, reputation=0)])
        session.commit()
    assert report(client, trusted).status_code == 201
    assert report(client, trusted).status_code == 200
    assert report(client, zero).status_code == 201
    assert channel(engine).score == Decimal('4.5')
    assert channel(engine).status == 'unreviewed'
    assert report(client).status_code == 201
    candidate = channel(engine)
    assert candidate.score == Decimal('5.5') and candidate.status == 'pending_review'
    assert client.get('/v1/blocklist').json()['channels'] == []
    assert decision(client, candidate.id, 'reject').status_code == 200
    assert report(client).status_code == 201
    assert channel(engine).status == 'rejected'
    assert channel(engine).score == Decimal('6.5')
    assert decision(client, candidate.id).status_code == 200
    assert report(client).status_code == 201
    assert channel(engine).status == 'approved'


def test_concurrent_unique_reports_count_once_without_lost_scores(api):
    client, engine = api
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: report(client), range(8)))
    assert all(response.status_code == 201 for response in responses)
    assert channel(engine).score == 8
    assert channel(engine).status == 'pending_review'


def test_admin_queues_decisions_audit_and_delta_removal(api):
    client, engine = api
    for _ in range(5):
        assert report(client).status_code == 201
    queue = client.get('/v1/admin/channels', headers=HEADERS)
    assert queue.status_code == 200 and queue.headers['cache-control'] == 'no-store'
    candidate = queue.json()['channels'][0]
    identifier = candidate['id']
    evidence = client.get(f'/v1/admin/channels/{identifier}/reports?limit=2', headers=HEADERS)
    assert len(evidence.json()['reports']) == 2
    assert evidence.json()['reports'][0]['reason'] == 'Generated narration'
    assert decision(client, identifier).json()['changed'] is True
    assert decision(client, identifier).json()['changed'] is False
    full = client.get('/v1/blocklist').json()
    assert full['channels'][0]['youtube_channel_id'] == CHANNEL
    appeal_id = appeal(client)
    assert client.get('/v1/admin/appeals', headers=HEADERS).json()['appeals'][0]['id'] == appeal_id
    assert resolve(client, appeal_id).json()['changed'] is True
    assert resolve(client, appeal_id).json()['changed'] is False
    assert resolve(client, appeal_id, 'reject').status_code == 409
    delta = client.get('/v1/blocklist', params={'since': full['next_since']}).json()
    assert delta['channels'] == [] and CHANNEL in delta['removed_channel_ids']
    with Session(engine) as session:
        record = session.get(Appeal, UUID(appeal_id))
        assert record.status == 'accepted' and record.resolved_at is not None
        actions = session.scalars(select(ModerationAction).order_by(ModerationAction.created_at)).all()
        assert [item.action for item in actions] == ['approve', 'accept_appeal']
        assert all(item.actor == 'admin-api' and KEY not in item.reason for item in actions)


def test_rejected_appeal_leaves_channel_status_alone(api):
    client, engine = api
    report(client)
    identifier = channel(engine).id
    decision(client, identifier)
    appeal_id = appeal(client)
    assert resolve(client, appeal_id, 'reject').status_code == 200
    assert channel(engine).status == 'approved'
    another = appeal(client)
    decision(client, identifier, 'reject')
    assert resolve(client, another, 'reject').status_code == 200
    assert channel(engine).status == 'rejected'


def test_concurrent_appeal_decisions_have_one_winner_and_audit(api):
    client, engine = api
    report(client)
    decision(client, channel(engine).id)
    appeal_id = appeal(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda action: resolve(client, appeal_id, action), ['accept', 'reject']))
    assert sorted(response.status_code for response in responses) == [200, 409]
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ModerationAction).where(
            ModerationAction.appeal_id == UUID(appeal_id))) == 1


@pytest.mark.parametrize('path', ['/channels', '/appeals', f'/channels/{uuid4()}/reports',
                                  f'/channels/{uuid4()}/decision', f'/appeals/{uuid4()}/decision'])
def test_all_admin_routes_require_key(api, path):
    client, _ = api
    for headers in [{}, {'X-Admin-Key': 'wrong'}]:
        if path.endswith('/decision'):
            response = client.post('/v1/admin'+path, headers=headers, json={'action':'reject','reason':'test'})
        else:
            response = client.get('/v1/admin'+path, headers=headers)
        assert response.status_code == 401
        assert response.headers['cache-control'] == 'no-store'
    assert client.get('/v1/admin/channels', params={'api_key':KEY}).status_code == 401


def test_unconfigured_admin_disabled_and_database_error_redacted():
    settings = Settings(admin_api_key='', database_url='postgresql+psycopg://user:secret@127.0.0.1:1/no_db')
    with TestClient(create_app(settings)) as client:
        assert client.get('/v1/admin/channels', headers=HEADERS).status_code == 503
        assert client.get('/health').status_code == 200
    settings.admin_api_key = Settings(admin_api_key=KEY).admin_api_key
    with TestClient(create_app(settings)) as client:
        response = client.get('/v1/admin/channels', headers=HEADERS)
        assert response.status_code == 503 and response.headers['retry-after'] == '5'
        assert 'secret' not in response.text


def test_validation_missing_targets_and_atomic_audit_failure(api):
    client, engine = api
    assert decision(client, uuid4()).status_code == 404
    assert resolve(client, uuid4()).status_code == 404
    report(client)
    identifier = channel(engine).id
    for payload in [{'action':'approve','reason':' '}, {'action':'unknown','reason':'why'},
                    {'action':'approve','reason':'why','actor':'spoof'}]:
        assert client.post(f'/v1/admin/channels/{identifier}/decision', headers=HEADERS, json=payload).status_code == 422
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE moderation_actions ADD CONSTRAINT test_fail CHECK (false)"))
    assert decision(client, identifier).status_code == 503
    assert channel(engine).status == 'unreviewed'


@pytest.mark.parametrize('settings', [{'admin_api_key':'short'}, {'admin_api_key':' '*32},
                                     {'review_threshold':'NaN'}, {'review_threshold':0}])
def test_invalid_moderation_settings(settings):
    with pytest.raises(ValueError):
        Settings(**settings)


def test_appeal_audit_failure_rolls_back_and_retry_does_not_reverse_later_approval(api):
    client, engine = api
    report(client)
    identifier = channel(engine).id
    decision(client, identifier)
    appeal_id = appeal(client)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE moderation_actions ADD CONSTRAINT test_fail CHECK (action = 'approve')"))
    assert resolve(client, appeal_id).status_code == 503
    assert channel(engine).status == 'approved'
    with Session(engine) as session:
        record = session.get(Appeal, UUID(appeal_id))
        assert record.status == 'open' and record.resolved_at is None
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE moderation_actions DROP CONSTRAINT test_fail'))
    assert resolve(client, appeal_id).status_code == 200
    assert decision(client, identifier).status_code == 200
    assert resolve(client, appeal_id).json()['changed'] is False
    assert channel(engine).status == 'approved'


def test_score_saturates_instead_of_overflowing(api):
    client, engine = api
    first, second = uuid4(), uuid4()
    with Session(engine) as session:
        session.add_all([Install(id=first, reputation=Decimal('99999999.9999')),
                         Install(id=second, reputation=Decimal('99999999.9999'))])
        session.commit()
    assert report(client, first).status_code == 201
    assert report(client, second).status_code == 201
    assert channel(engine).score == Decimal('99999999.9999')
    assert channel(engine).status == 'pending_review'


def test_review_lists_filter_paginate_and_reject_invalid_queries(api):
    client, engine = api
    with Session(engine) as session:
        for letter, status in [('a', 'pending_review'), ('b', 'pending_review'), ('c', 'rejected')]:
            session.add(Channel(youtube_channel_id='UC' + letter * 22, status=status))
        session.commit()
    first = client.get('/v1/admin/channels?limit=1', headers=HEADERS).json()['channels']
    second = client.get('/v1/admin/channels?limit=1&offset=1', headers=HEADERS).json()['channels']
    assert len(first) == len(second) == 1 and first[0]['id'] != second[0]['id']
    assert first[0]['status'] == second[0]['status'] == 'pending_review'
    rejected = client.get('/v1/admin/channels?status=rejected', headers=HEADERS).json()['channels']
    assert len(rejected) == 1 and rejected[0]['youtube_channel_id'] == 'UC' + 'c' * 22
    assert client.get('/v1/admin/channels?offset=3', headers=HEADERS).json()['channels'] == []
    assert client.get(f'/v1/admin/channels/{uuid4()}/reports', headers=HEADERS).status_code == 404
    for path in ['/channels?limit=101', '/channels?offset=-1', '/channels?status=unknown',
                 '/appeals?status=approved', '/appeals?limit=0']:
        assert client.get('/v1/admin'+path, headers=HEADERS).status_code == 422
