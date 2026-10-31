from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import Channel


def value(body, name, **labels):
    samples = [sample for family in text_string_to_metric_families(body) for sample in family.samples
               if sample.name == name and sample.labels == labels]
    assert len(samples) == 1, (name, labels)
    return samples[0].value


def scrape(client):
    response = client.get('/metrics')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/plain')
    assert response.headers['cache-control'] == 'no-store'
    return response.text


def test_submission_sync_and_rate_limit_metrics(migrated_db, redis_state):
    settings = Settings(rate_limit_install_capacity=2, rate_limit_ip_capacity=10)
    payload = {'install_id':str(uuid4()), 'channel_id':'UC'+'x'*22, 'reason':'Private explicit reason'}
    with TestClient(create_app(settings)) as client:
        assert client.post('/v1/reports', json=payload).status_code == 201
        assert client.post('/v1/reports', json=payload).status_code == 200
        assert client.post('/v1/reports', json=payload).status_code == 429
        assert client.post('/v1/appeals', json=payload).status_code == 429
        assert client.post('/v1/reports', json={}).status_code == 422
        full = client.get('/v1/blocklist')
        assert full.status_code == 200
        assert client.get('/v1/blocklist', headers={'If-None-Match':full.headers['etag']}).status_code == 304
        assert client.get('/v1/blocklist?since=invalid').status_code == 422
        body = scrape(client)
        assert value(body, 'antislop_reports_created_total') == 1
        for route in ('/v1/reports', '/v1/appeals'):
            assert value(body, 'antislop_rate_limit_rejections_total', route=route) == 1
        for status in ('200', '304', '422'):
            assert value(body, 'antislop_blocklist_sync_requests_total', status=status) == 1
        assert value(body, 'antislop_http_request_duration_seconds_count', method='POST', route='/v1/reports') == 4
        assert value(body, 'antislop_http_request_duration_seconds_sum', method='POST', route='/v1/reports') > 0
        assert value(body, 'antislop_http_requests_total', method='POST', route='/v1/reports', status='429') == 1
        assert 'route="/metrics"' not in scrape(client)
        assert all(secret not in body for secret in payload.values())


def test_metrics_labels_do_not_contain_raw_identifiers_or_unknown_paths(migrated_db):
    settings = Settings(admin_api_key='private-admin-key-'+'z'*32)
    identifier = str(uuid4())
    with TestClient(create_app(settings)) as client:
        client.get(f'/v1/admin/channels/{identifier}/reports?secret=private-query',
                   headers={'X-Admin-Key':'private-incorrect-key', 'X-Forwarded-For':'198.51.100.99'})
        for raw in ('private-unknown-path', 'another-private-path'):
            assert client.get('/'+raw).status_code == 404
        assert client.request('CUSTOMMETHOD', '/health').status_code == 405
        body = scrape(client)
        assert value(body, 'antislop_http_requests_total', method='GET',
                     route='/v1/admin/channels/{channel_id}/reports', status='401') == 1
        assert value(body, 'antislop_http_requests_total', method='GET', route='unmatched', status='404') == 2
        assert value(body, 'antislop_http_requests_total', method='OTHER', route='/health', status='405') == 1
        for secret in (identifier, 'private-query', 'private-incorrect-key', '198.51.100.99',
                       'private-unknown-path', 'another-private-path', 'CUSTOMMETHOD', settings.admin_api_key.get_secret_value()):
            assert secret not in body


def test_approved_count_tracks_database_and_is_omitted_on_failure(migrated_db):
    engine, _ = migrated_db
    with Session(engine) as session:
        for index, status in enumerate(('approved', 'pending_review', 'rejected', 'unreviewed')):
            session.add(Channel(youtube_channel_id='UC'+str(index)*22, status=status))
        session.commit()
    with TestClient(create_app()) as client:
        body = scrape(client)
        assert value(body, 'antislop_approved_channels') == 1
        assert value(body, 'antislop_metrics_database_up') == 1
        with engine.begin() as connection:
            connection.execute(text("UPDATE channels SET status = 'rejected' WHERE status = 'approved'"))
        assert value(scrape(client), 'antislop_approved_channels') == 0
        with engine.begin() as connection:
            connection.execute(text('ALTER TABLE channels RENAME TO temporarily_unavailable'))
        try:
            body = scrape(client)
            assert value(body, 'antislop_metrics_database_up') == 0
            assert 'antislop_approved_channels' not in body
            assert client.get('/health').status_code == 200
        finally:
            with engine.begin() as connection:
                connection.execute(text('ALTER TABLE temporarily_unavailable RENAME TO channels'))
        assert value(scrape(client), 'antislop_metrics_database_up') == 1


def test_metrics_registries_are_isolated_and_collectors_survive_lifespan_restart(migrated_db):
    app = create_app()
    with TestClient(app) as first, TestClient(create_app()) as second:
        first.get('/health')
        assert value(scrape(first), 'antislop_http_requests_total', method='GET', route='/health', status='200') == 1
        assert 'route="/health"' not in scrape(second)
    with TestClient(app) as reopened:
        assert value(scrape(reopened), 'antislop_metrics_database_up') == 1


def test_unhandled_exception_is_counted_without_swallowing_it(migrated_db):
    app = create_app()

    @app.get('/test-error')
    def fail():
        raise RuntimeError('private-error-content')

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get('/test-error').status_code == 500
        body = scrape(client)
        assert value(body, 'antislop_http_requests_total', method='GET', route='/test-error', status='500') == 1
        assert 'private-error-content' not in body


@pytest.mark.parametrize('failure', ['database', 'redis'])
def test_unavailable_dependencies_do_not_count_successful_reports(migrated_db, redis_state, failure):
    changes = {'database_url':'postgresql+psycopg://user:private-password@127.0.0.1:1/missing'} if failure == 'database' else {'redis_url':'redis://127.0.0.1:1/0'}
    with TestClient(create_app(Settings(**changes))) as client:
        response = client.post('/v1/reports', json={
            'install_id':str(uuid4()), 'channel_id':'UC'+'x'*22, 'reason':'Private reason'})
        assert response.status_code == 503
        body = scrape(client)
        assert value(body, 'antislop_reports_created_total') == 0
        assert value(body, 'antislop_rate_limit_rejections_total', route='/v1/reports') == 0
        assert 'private-password' not in body
