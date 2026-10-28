"""Explicit lifecycle: migrations are a separate command and startup errors never echo configuration."""
import os
import sys
from uuid import uuid4

import pytest
from platform_backend_core import Database
from platform_backend_core.testing import temporary_database

from platform_commerce import __main__ as cli
from platform_commerce.store import CommerceStore, Conflict


def run(monkeypatch, *args):
    monkeypatch.setattr(sys, 'argv', ['platform_commerce', *args])
    cli.main()


def test_serve_without_configuration_fails_generically(monkeypatch):
    for name in ('DATABASE_URL', 'JWT_ISSUER', 'JWT_AUDIENCE', 'JWT_PUBLIC_KEY', 'JWT_JWKS_URL'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://SYNTHETIC_MARKER@127.0.0.1:1/none')
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, 'serve')
    assert str(exc.value) == 'Service configuration or dependency unavailable'


def test_unknown_command_is_rejected(monkeypatch):
    with pytest.raises(SystemExit):
        run(monkeypatch, 'worker')


def test_migrate_command_applies_the_schema_once(monkeypatch):
    dsn = os.environ.get('PLATFORM_TEST_DSN')
    if not dsn:
        pytest.skip('explicit disposable PostgreSQL DSN required')
    with temporary_database(dsn, prefix='coml_') as temp:
        monkeypatch.setenv('DATABASE_URL', temp.admin_dsn)
        run(monkeypatch, 'migrate')
        run(monkeypatch, 'migrate')
        temp.grant_schema('public')
        db = Database(temp.runtime_dsn, max_size=1)
        try:
            store = CommerceStore(db)
            w = uuid4()
            store.create_item(w, 'tea-01', 'Green tea', 1, 'THB')
            # A failed transaction on the only pooled connection must not leak into the next one.
            with pytest.raises(Conflict):
                store.create_item(w, 'tea-01', 'Green tea', 1, 'THB')
            assert store.ready() is True and db.ready() is True
            assert store.list_items(w)[0]['sku'] == 'tea-01'
        finally:
            db.close()
