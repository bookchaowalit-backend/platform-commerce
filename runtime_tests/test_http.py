"""HTTP surface: real RS256 tokens, workspace from the token, generic errors, readiness."""
import os
import time
from uuid import uuid4

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from platform_backend_core import Database, MigrationRunner, TokenVerifier
from platform_backend_core.testing import temporary_database
from psycopg import sql

from platform_commerce.app import create_app
from platform_commerce.migrations import MIGRATIONS
from platform_commerce.store import REQUIRED_PRIVILEGES, CommerceStore

ALL = 'catalog:read catalog:write promotions:read promotions:write cart:read cart:write orders:read orders:write'


def auth():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    verifier = TokenVerifier(issuer='fixture', audience='fixture', public_key=public)

    def headers(scopes, workspace=None, idempotency_key=None):
        now = int(time.time())
        token = jwt.encode({'iss': 'fixture', 'aud': 'fixture', 'sub': str(uuid4()), 'ws': str(workspace or uuid4()),
                            'iat': now, 'exp': now + 300, 'jti': str(uuid4()), 'scope': scopes}, key, algorithm='RS256')
        result = {'Authorization': 'Bearer ' + token}
        if idempotency_key is not None:
            result['Idempotency-Key'] = idempotency_key
        return result
    return verifier, headers


@pytest.fixture
def setup():
    dsn = os.environ.get('PLATFORM_TEST_DSN')
    if not dsn:
        pytest.skip('explicit PostgreSQL DSN required')
    with temporary_database(dsn, prefix='comh_') as temp:
        verifier, headers = auth()
        db = Database(temp.runtime_dsn)
        yield temp, db, verifier, headers
        db.close()


def migrated(temp):
    MigrationRunner(temp.admin_dsn, namespace='commerce').apply(MIGRATIONS)
    temp.grant_schema('public')


def test_missing_schema_is_not_ready(setup):
    _temp, db, verifier, _headers = setup
    with TestClient(create_app(db, verifier)) as c:
        assert c.get('/healthz').status_code == 200
        assert c.get('/readyz').status_code == 503


def test_catalog_to_order_flow_with_idempotent_placement(setup):
    temp, db, verifier, headers = setup
    migrated(temp)
    w = uuid4()
    h = headers(ALL, w)
    with TestClient(create_app(db, verifier)) as c:
        assert c.get('/readyz').status_code == 200
        r = c.post('/v1/catalog/items', headers=h, json={'sku': 'tea-01', 'name': 'Green tea', 'unit_price_minor': 12000, 'currency': 'THB'})
        assert r.status_code == 201
        item = r.json()
        assert c.post('/v1/catalog/items', headers=h, json={'sku': 'tea-01', 'name': 'Again', 'unit_price_minor': 1, 'currency': 'THB'}).status_code == 409
        assert c.get('/v1/catalog/items', headers=h).json()[0]['id'] == item['id']
        assert c.post('/v1/promotions', headers=h, json={'code': 'TENOFF', 'currency': 'THB', 'percent_off': 10}).status_code == 201
        assert [p['code'] for p in c.get('/v1/promotions', headers=h).json()] == ['TENOFF']

        cart = c.post('/v1/carts', headers=h, json={'currency': 'THB'})
        assert cart.status_code == 201
        cid = cart.json()['id']
        r = c.put(f'/v1/carts/{cid}/lines/{item["id"]}', headers=h, json={'quantity': 3})
        assert r.status_code == 200 and r.json()['subtotal_minor'] == 36000
        r = c.put(f'/v1/carts/{cid}/promotion', headers=h, json={'code': 'TENOFF'})
        assert r.status_code == 200 and r.json()['total_minor'] == 32400 and r.json()['promotion_applied'] is True
        assert c.get(f'/v1/carts/{cid}', headers=h).json()['total_minor'] == 32400

        body = {'cart_id': cid, 'expected_total_minor': 32400}
        first = c.post('/v1/orders', headers=headers(ALL, w, 'order-1'), json=body)
        assert first.status_code == 201 and first.json()['status'] == 'placed' and first.json()['total_minor'] == 32400
        replay = c.post('/v1/orders', headers=headers(ALL, w, 'order-1'), json=body)
        assert replay.status_code == 200 and replay.json() == first.json()
        changed = c.post('/v1/orders', headers=headers(ALL, w, 'order-1'), json={'cart_id': cid, 'expected_total_minor': 1})
        assert changed.status_code == 409
        assert c.post('/v1/orders', headers=headers(ALL, w, 'order-2'), json=body).status_code == 409
        assert c.post('/v1/orders', headers=h, json=body).status_code == 422

        oid = first.json()['id']
        assert c.get(f'/v1/orders/{oid}', headers=h).json()['lines'][0]['quantity'] == 3
        assert [o['id'] for o in c.get('/v1/orders', headers=h).json()] == [oid]
        r = c.post(f'/v1/orders/{oid}/cancel', headers=h)
        assert r.status_code == 200 and r.json()['status'] == 'cancelled'
        assert c.post(f'/v1/orders/{oid}/cancel', headers=h).json() == r.json()


def test_scopes_tokens_and_workspaces_are_enforced(setup):
    temp, db, verifier, headers = setup
    migrated(temp)
    w = uuid4()
    with TestClient(create_app(db, verifier)) as c:
        item = c.post('/v1/catalog/items', headers=headers(ALL, w),
                      json={'sku': 'tea-01', 'name': 'Green tea', 'unit_price_minor': 100, 'currency': 'THB'}).json()
        assert c.get('/v1/catalog/items').status_code == 401
        assert c.get('/v1/catalog/items', headers={'Authorization': 'Bearer not-a-token'}).status_code == 401
        assert c.post('/v1/catalog/items', headers=headers('catalog:read', w),
                      json={'sku': 'x', 'name': 'x', 'unit_price_minor': 1, 'currency': 'THB'}).status_code == 403
        assert c.post('/v1/orders', headers=headers('orders:read', w, 'k'), json={'cart_id': str(uuid4())}).status_code == 403
        assert c.get(f'/v1/catalog/items/{item["id"]}', headers=headers('catalog:read', w)).status_code == 200
        assert c.get(f'/v1/catalog/items/{item["id"]}', headers=headers(ALL)).status_code == 404
        cart = c.post('/v1/carts', headers=headers(ALL, w), json={'currency': 'THB'}).json()
        assert c.get(f'/v1/carts/{cart["id"]}', headers=headers(ALL)).status_code == 404
        assert c.put(f'/v1/carts/{cart["id"]}/lines/{item["id"]}', headers=headers(ALL), json={'quantity': 1}).status_code == 404


def test_validation_errors_are_generic_and_never_echo_input(setup):
    temp, db, verifier, headers = setup
    migrated(temp)
    h = headers(ALL)
    with TestClient(create_app(db, verifier)) as c:
        for body in ({'sku': 'ok', 'name': 'ok', 'unit_price_minor': 1, 'currency': 'THB', 'extra': 'SYNTHETIC_MARKER'},
                     {'sku': 'ok', 'name': 'ok', 'unit_price_minor': 1.5, 'currency': 'THB'},
                     {'sku': 'SYNTHETIC MARKER', 'name': 'ok', 'unit_price_minor': 1, 'currency': 'THB'}):
            r = c.post('/v1/catalog/items', headers=h, json=body)
            assert r.status_code == 422 and 'SYNTHETIC' not in r.text
        r = c.post('/v1/orders', headers={**h, 'Idempotency-Key': 'SYNTHETIC MARKER'}, json={'cart_id': str(uuid4())})
        assert r.status_code == 422 and 'SYNTHETIC' not in r.text
        r = c.put(f'/v1/carts/{uuid4()}/promotion', headers=h, json={'code': 'NOPE'})
        assert r.status_code == 404 and r.json() == {'detail': 'Not found'}


def test_payment_is_outside_this_boundary(setup):
    _temp, db, verifier, _headers = setup
    app = create_app(db, verifier)
    paths = ' '.join(app.openapi()['paths']).lower()
    assert all(word not in paths for word in ('pay', 'capture', 'refund', 'checkout'))


def test_applied_migration_checksum_required(setup):
    temp, db, verifier, _headers = setup
    migrated(temp)
    with psycopg.connect(temp.admin_dsn) as admin:
        admin.execute("UPDATE platform_schema_migrations SET checksum='0' WHERE namespace=%s", ('commerce',))
    with TestClient(create_app(db, verifier)) as c:
        assert c.get('/readyz').status_code == 503


@pytest.mark.parametrize('kind,target,privilege', [('TABLE', t, p) for t, p in REQUIRED_PRIVILEGES]
                         + [('SCHEMA', 'public', 'USAGE'), ('TABLE', 'platform_schema_migrations', 'SELECT')])
def test_readiness_requires_each_effective_privilege(setup, kind, target, privilege):
    temp, db, verifier, _headers = setup
    migrated(temp)
    with psycopg.connect(temp.admin_dsn) as admin:
        admin.execute('REVOKE USAGE ON SCHEMA public FROM PUBLIC')

    def change(verb, preposition):
        with psycopg.connect(temp.admin_dsn) as admin:
            admin.execute(sql.SQL('{} {} ON {} {} {} {}').format(sql.SQL(verb), sql.SQL(privilege), sql.SQL(kind),
                                                                sql.Identifier(target), sql.SQL(preposition),
                                                                sql.Identifier(temp.runtime_role)))
    with TestClient(create_app(db, verifier)) as c:
        assert c.get('/readyz').status_code == 200
        change('REVOKE', 'FROM')
        assert c.get('/readyz').status_code == 503
        change('GRANT', 'TO')
        assert c.get('/readyz').status_code == 200


def test_promotion_patch_deactivates_and_sets_an_expiry(setup):
    temp, db, verifier, headers = setup
    migrated(temp)
    w = uuid4()
    h = headers(ALL, w)
    with TestClient(create_app(db, verifier)) as c:
        item = c.post('/v1/catalog/items', headers=h, json={'sku': 'tea-01', 'name': 'Tea', 'unit_price_minor': 1000, 'currency': 'THB'}).json()
        promotion = c.post('/v1/promotions', headers=h, json={'code': 'TENOFF', 'currency': 'THB', 'percent_off': 10}).json()
        assert promotion['ends_at'] is None
        cid = c.post('/v1/carts', headers=h, json={'currency': 'THB'}).json()['id']
        c.put(f'/v1/carts/{cid}/lines/{item["id"]}', headers=h, json={'quantity': 1})
        assert c.put(f'/v1/carts/{cid}/promotion', headers=h, json={'code': 'TENOFF'}).json()['total_minor'] == 900
        path = f'/v1/promotions/{promotion["id"]}'

        r = c.patch(path, headers=h, json={'active': False})
        assert r.status_code == 200 and r.json()['active'] is False
        assert c.get(f'/v1/carts/{cid}', headers=h).json()['total_minor'] == 1000
        r = c.patch(path, headers=h, json={'active': True, 'ends_at': '2020-01-01T00:00:00Z'})
        assert r.status_code == 200 and r.json()['active'] is True and r.json()['ends_at'].startswith('2020-01-01')
        assert c.get(f'/v1/carts/{cid}', headers=h).json()['promotion_applied'] is False
        r = c.patch(path, headers=h, json={'ends_at': None})
        assert r.status_code == 200 and r.json()['ends_at'] is None
        assert c.get(f'/v1/carts/{cid}', headers=h).json()['total_minor'] == 900

        assert c.patch(path, headers=headers('promotions:read', w), json={'active': False}).status_code == 403
        assert c.patch(path, headers=headers(ALL), json={'active': False}).status_code == 404
        for body in ({}, {'active': 'no'}, {'ends_at': '2020-01-01T00:00:00'}, {'ends_at': 'SYNTHETIC_MARKER'},
                     {'active': False, 'code': 'OTHER'}):
            r = c.patch(path, headers=h, json=body)
            assert r.status_code == 422 and r.json() == {'detail': 'invalid request'} and 'SYNTHETIC' not in r.text

        order = c.post('/v1/orders', headers=headers(ALL, w, 'order-1'), json={'cart_id': cid}).json()
        cart = c.get(f'/v1/carts/{cid}', headers=h).json()
        assert cart['order_id'] == order['id'] and cart['total_minor'] == order['total_minor'] == 900


def test_unexpected_server_errors_are_500_not_validation_errors(setup, monkeypatch):
    temp, db, verifier, headers = setup
    migrated(temp)

    def bug(*_args, **_kwargs):
        raise ValueError('SYNTHETIC_MARKER server bug')
    monkeypatch.setattr(CommerceStore, 'list_items', bug)
    with TestClient(create_app(db, verifier)) as c:
        r = c.get('/v1/catalog/items', headers=headers(ALL))
        assert r.status_code == 500 and r.json() == {'detail': 'internal server error'} and 'SYNTHETIC' not in r.text
        r = c.get('/v1/promotions', headers=headers(ALL), params={'limit': 0})
        assert r.status_code == 422 and r.json() == {'detail': 'invalid request'}
        r = c.post('/v1/carts', headers=headers(ALL), json={'currency': 'thb'})
        assert r.status_code == 422 and r.json() == {'detail': 'invalid request'}
