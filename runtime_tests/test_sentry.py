"""Sentry is off without SENTRY_DSN; with it: errors only, no PII, locals, bodies or secrets."""
import sys
from typing import Any

import pytest
import sentry_sdk

import platform_commerce
from platform_commerce import _sentry


def _clear_env(monkeypatch):
    for name in ('SENTRY_DSN', 'SENTRY_ENVIRONMENT', 'SENTRY_RELEASE', 'RAILWAY_GIT_COMMIT_SHA', 'RAILWAY_SERVICE_NAME'):
        monkeypatch.delenv(name, raising=False)


def test_package_import_initialises_sentry():
    # The package __init__ wires init_sentry, so `python -m platform_commerce serve` reports errors.
    assert platform_commerce._init_sentry is _sentry.init_sentry


def test_no_dsn_is_a_noop(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv('SENTRY_DSN', '   ')
    calls = []
    fake = type('Fake', (), {'init': staticmethod(lambda **kw: calls.append(kw))})
    monkeypatch.setitem(sys.modules, 'sentry_sdk', fake)
    _sentry.init_sentry()
    assert calls == []


def test_dsn_initialises_errors_only_without_pii(monkeypatch, capsys):
    _clear_env(monkeypatch)
    monkeypatch.setenv('SENTRY_DSN', 'https://public@o0.ingest.sentry.io/0')
    monkeypatch.setenv('RAILWAY_SERVICE_NAME', 'commerce-api')
    monkeypatch.setenv('RAILWAY_GIT_COMMIT_SHA', 'abc123')
    calls: list[dict[str, Any]] = []
    tags: dict[str, str] = {}
    monkeypatch.setattr(sentry_sdk, 'init', lambda **kw: calls.append(kw))
    monkeypatch.setattr(sentry_sdk, 'set_tag', lambda key, value: tags.__setitem__(key, value))
    _sentry.init_sentry()
    (kw,) = calls
    assert kw['environment'] == 'production'
    assert kw['release'] == 'abc123'
    assert kw['traces_sample_rate'] is None
    assert kw['send_default_pii'] is False
    assert kw['include_local_variables'] is False
    assert kw['max_request_body_size'] == 'never'
    assert kw['before_send'] is _sentry._scrub_event
    (logging_integration,) = kw['integrations']
    assert logging_integration._handler is None
    assert logging_integration._breadcrumb_handler is None
    assert logging_integration._sentry_logs_handler is None
    assert tags == {'service': 'commerce-api'}
    captured = capsys.readouterr()
    assert 'sentry: enabled for commerce-api' in captured.err
    assert captured.out == ''
    assert 'ingest.sentry.io' not in captured.err


def test_release_is_unset_without_a_git_sha(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv('SENTRY_DSN', 'https://public@o0.ingest.sentry.io/0')
    calls = []
    monkeypatch.setattr(sentry_sdk, 'init', lambda **kw: calls.append(kw))
    monkeypatch.setattr(sentry_sdk, 'set_tag', lambda key, value: None)
    _sentry.init_sentry()
    assert calls[0]['release'] is None


def test_scrub_removes_url_passwords_tokens_jwts_emails_and_ips():
    text = (
        'connect postgresql://svc:'
        's3cr%40t'  # split so secret scanners do not read a synthetic URL as a credential
        '@ep-x.neon.tech/db failed; '
        'password=hunter2 Authorization: Bearer abc.def-ghi '
        'eyJhbGciOiJSUzI1NiJ9' '.' 'eyJzdWIiOiJvd25lciJ9' '.' 'c2lnbmF0dXJl'
        ' for buyer.one+tag@example.co.th from 203.0.113.77 and 2001:db8:85a3:0:0:8a2e:370:7334'
    )  # split: not a secret
    out = _sentry.scrub(text)
    for secret in ('s3cr%40t', 'hunter2', 'abc.def-ghi', 'eyJhbGciOiJSUzI1NiJ9', 'buyer.one', 'example.co.th', '203.0.113.77', '8a2e:370:7334'):
        assert secret not in out
    assert 'postgresql://svc:***@ep-x.neon.tech/db' in out


def test_scrub_event_drops_request_details_user_and_extra():
    event = {
        'exception': {'values': [{'value': 'bad url postgres://u:pw@h/db for a@b.example'}]},
        'message': 'contact a@b.example',
        'request': {
            'method': 'POST',
            'url': 'https://x/api?token=t',
            'data': {'address': '1 Main Rd'},
            'headers': {'authorization': 'Bearer t', 'x-forwarded-for': '198.51.100.1'},
            'cookies': {'session': 's'},
            'query_string': 'token=t',
            'env': {'REMOTE_ADDR': '198.51.100.1'},
        },
        'user': {'ip_address': '198.51.100.1', 'email': 'a@b.example'},
        'breadcrumbs': {'values': [{'message': 'GET with Bearer abc', 'data': {'url': 'https://x?token=t'}}]},
        'extra': {'sys.argv': ['--token', 't']},
    }
    out = _sentry._scrub_event(event, {})
    assert out['exception']['values'][0]['value'] == 'bad url postgres://u:***@h/db for ***email***'
    assert out['message'] == 'contact ***email***'
    assert out['request'] == {'method': 'POST'}
    assert 'user' not in out
    assert 'data' not in out['breadcrumbs']['values'][0]
    assert 'abc' not in out['breadcrumbs']['values'][0]['message']
    assert 'extra' not in out
    for value in ('198.51.100.1', 'a@b.example', '1 Main Rd', 'token=t'):
        assert value not in str(out)


def test_scrub_event_keeps_only_scrubbed_formatted_log_text():
    token = 'opaque' + '-token-value'
    event = {
        'logentry': {
            'message': 'Authorization: Bearer %s',
            'params': [token],
            'formatted': 'Authorization: Bearer ' + token,
        }
    }
    out = _sentry._scrub_event(event, {})
    assert out['logentry'] == {'message': 'Authorization: Bearer ***'}
    assert token not in str(out)


def test_scrub_event_drops_dynamic_sampling_context():
    event = {'contexts': {'trace': {'trace_id': 't', 'dynamic_sampling_context': {'user_id': 'alice'}}}}
    out = _sentry._scrub_event(event, {})
    assert out['contexts']['trace'] == {'trace_id': 't'}


@pytest.mark.parametrize('value', [None, 42])
def test_scrub_event_tolerates_missing_or_odd_fields(value):
    event = {'exception': {'values': [{'value': value}]}, 'request': 'x', 'logentry': None}
    out = _sentry._scrub_event(event, {})
    assert out['exception']['values'][0]['value'] == value


@pytest.mark.parametrize('text, secret', [
    ('refresh failed: access_token=tok-AAA111 expired', 'tok-AAA111'),
    ('client_secret=cs-BBB222&grant_type=client_credentials', 'cs-BBB222'),
    ("bad config {'password': 'pw-CCC333', 'name': 'x'}", 'pw-CCC333'),
    ('bad body {"api_key": "ak-DDD444"}', 'ak-DDD444'),
    ('DB_PASSWORD="pw-EEE555" rejected', 'pw-EEE555'),
    ('GET https://h.example/cb?code=c-FFF666&state=s-GGG777 failed', 'c-FFF666'),
])
def test_scrub_catches_prefixed_quoted_and_query_string_secrets(text, secret):
    out = _sentry.scrub(text)
    assert secret not in out
    assert 's-GGG777' not in out


def test_scrub_is_bounded_on_long_hostile_input():
    import time

    n = _sentry.MAX_INPUT_CHARS - 64  # under the pre-cap, so every pattern really runs
    for hostile in ('a' * n, 'x_' * (n // 2), 'a://' * (n // 4), 'a.' * (n // 2), '%' * n, 'a://b:' * (n // 6), 'x@' + 'a-' * (n // 2), 'eyJ-' * (n // 4), 'a' * 200_000):
        start = time.perf_counter()
        out = _sentry.scrub(hostile + ' password')
        assert time.perf_counter() - start < 0.5
        assert len(out) <= _sentry.MAX_SCRUB_CHARS + len(_sentry.TRUNCATED)


@pytest.mark.parametrize('text, secret', [
    # a credential straddling the length cap must not survive as a partial token
    ('x ' * 4080 + 'postgresql://u:' + 'S' * 40 + '@h/db', 'SSSSSSSSSS'),
    # past the pattern bounds the whole URL token is redacted (fail closed)
    ('dial postgresql://' + 'u' * 300 + ':pw-HHH888@h/db', 'pw-HHH888'),
    ('GET https://h.example/' + 'p' * 3000 + '?code=c-III999 failed', 'c-III999'),
    ('dial postgresql://u:' + 'P' * 600 + '@h/db', 'PPPPPPPPPP'),
    ('from ' + 'L' * 100 + '@example.com', 'LLLLLLLLLL'),
    # one scrubbed URL must not vouch for an unscrubbed one in the same token
    ('a://x:pw-OK1@h/b://' + 'u' * 300 + ':pw-ZZZ000@h2', 'pw-ZZZ000'),
    ('https://h/?a=1&r=https://' + 'h' * 600 + '/p?code=c-YYY000', 'c-YYY000'),
    ('token eyJhbGciOiJSUzI1NiJ9.' + 'Q' * 5000 + '.sig-XXX000 rejected', 'sig-XXX000'),
    ('token eyJhbGciOiJSUzI1NiJ9' '.' 'eyJzdWIiOiJ4In0' '.' + 'S' * 4096 + 'TAIL-WWW000 rejected', 'TAIL-WWW000'),
])
def test_scrub_fails_closed_at_bounds_and_cap(text, secret):
    out = _sentry.scrub(text)
    assert secret not in out
    assert len(out) <= _sentry.MAX_SCRUB_CHARS + len(_sentry.TRUNCATED)


def test_a_server_500_reaches_sentry_scrubbed(monkeypatch):
    # The shared core's boundary turns unexpected exceptions into a redacted 500 before an outer
    # ASGI layer sees them, so the app must capture them itself (inside that boundary).
    from uuid import uuid4

    from fastapi.testclient import TestClient
    from test_http import auth

    from platform_commerce.app import create_app
    from platform_commerce.store import CommerceStore

    class _NoDatabase:
        def ready(self):
            return False

        def close(self):
            pass

        def transaction(self, workspace):
            raise AssertionError('database must not be reached')

    events: list[dict[str, Any]] = []

    class _Memory(sentry_sdk.transport.Transport):
        def capture_envelope(self, envelope):
            events.extend(item.payload.json for item in envelope.items if item.type == 'event')

    real_init = sentry_sdk.init
    # The production configuration, with only the transport swapped for memory.
    monkeypatch.setattr(sentry_sdk, 'init', lambda **kw: real_init(transport=_Memory, **kw))
    monkeypatch.setenv('SENTRY_DSN', 'https://k@o0.ingest.sentry.io/1')
    _sentry.init_sentry()
    # Built from parts so the source lines Sentry attaches do not contain the values either.
    message = 'db password=' + 'pw-' + 'SRV500' + ' at ' + '203.0' + '.113.9'
    try:
        def broken(*args, **kwargs):
            raise RuntimeError(message)
        monkeypatch.setattr(CommerceStore, 'list_items', broken)
        verifier, headers = auth()
        with TestClient(create_app(_NoDatabase(), verifier)) as c:
            r = c.get('/v1/catalog/items', headers=headers('catalog:read', uuid4()))
        assert r.status_code == 500 and r.json() == {'detail': 'internal server error'}
        sentry_sdk.flush()
        assert len(events) == 1
        text = str(events[0])
        assert 'RuntimeError' in text and 'pw-SRV500' not in text and '203.0' '.113.9' not in text
    finally:
        real_init(dsn=None)


@pytest.mark.parametrize('text, secret', [
    ("login password='correct horse battery staple' failed", 'battery staple'),
    ("cfg {'password': 'prefix,SECRET_SUFFIX'}", 'SECRET_SUFFIX'),
    ('cfg {"client_secret": "a\\"b SECRET_ESC"}', 'SECRET_ESC'),
    ('dial from 2001:db8::7334 refused', '2001:db8::7334'),
    ('peer fe80::1ff:fe23:4567:890a closed', 'fe80::1ff'),
    ('bind ::1 ok', '::1'),
])
def test_scrub_complete_quoted_values_and_compressed_ipv6(text, secret):
    assert secret not in _sentry.scrub(text)


@pytest.mark.parametrize('text', ['std::vec::Vec failed', 'at 12:30:45 UTC', 'Foo::bar() raised'])
def test_scrub_keeps_rust_paths_and_times(text):
    assert _sentry.scrub(text) == text
