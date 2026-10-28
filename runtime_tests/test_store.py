"""Store behaviour on real PostgreSQL with a NOSUPERUSER NOBYPASSRLS runtime role."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from platform_backend_core import Database, MigrationRunner
from platform_backend_core.testing import temporary_database

from platform_commerce.migrations import MIGRATIONS
from platform_commerce.store import CommerceStore, Conflict, NotFound


@pytest.fixture
def store():
    dsn = os.environ.get('PLATFORM_TEST_DSN')
    if not dsn:
        pytest.skip('explicit disposable PostgreSQL DSN required')
    with temporary_database(dsn, prefix='com_') as temp:
        MigrationRunner(temp.admin_dsn, namespace='commerce').apply(MIGRATIONS)
        temp.grant_schema('public')
        db = Database(temp.runtime_dsn)
        yield CommerceStore(db), db, temp
        db.close()


def stocked(s, w, currency='THB'):
    a = s.create_item(w, 'tea-01', 'Green tea', 12000, currency)
    b = s.create_item(w, 'cup-01', 'Cup', 4550, currency)
    return a, b


def filled_cart(s, w):
    a, b = stocked(s, w)
    cart = s.create_cart(w, 'THB')
    s.set_line(w, cart['id'], a['id'], 2)
    s.set_line(w, cart['id'], b['id'], 1)
    return cart, a, b


# catalog

def test_catalog_items_are_workspace_scoped_and_sku_unique(store):
    s, _db, _ = store
    w, other = uuid4(), uuid4()
    item = s.create_item(w, 'tea-01', 'Green tea', 12000, 'THB')
    assert item['unit_price_minor'] == 12000 and item['currency'] == 'THB' and item['active'] is True
    assert s.get_item(w, item['id'])['sku'] == 'tea-01'
    assert s.get_item(other, item['id']) is None and s.list_items(other) == []
    with pytest.raises(Conflict):
        s.create_item(w, 'tea-01', 'Other tea', 1, 'THB')
    assert s.create_item(other, 'tea-01', 'Same sku, other workspace', 1, 'THB')['sku'] == 'tea-01'


@pytest.mark.parametrize('sku,name,price,currency', [
    ('bad sku', 'Name', 1, 'THB'),
    ('ok', '', 1, 'THB'),
    ('ok', 'Line\nbreak', 1, 'THB'),
    ('ok', 'Name', -1, 'THB'),
    ('ok', 'Name', 1.0, 'THB'),
    ('ok', 'Name', 10**10 + 1, 'THB'),
    ('ok', 'Name', 1, 'thb'),
])
def test_invalid_catalog_items_are_rejected(store, sku, name, price, currency):
    s, _db, _ = store
    with pytest.raises(ValueError):
        s.create_item(uuid4(), sku, name, price, currency)


def test_item_update_changes_price_and_availability(store):
    s, _db, _ = store
    w = uuid4()
    item = s.create_item(w, 'tea-01', 'Green tea', 12000, 'THB')
    updated = s.update_item(w, item['id'], unit_price_minor=9900, active=False)
    assert updated['unit_price_minor'] == 9900 and updated['active'] is False
    with pytest.raises(NotFound):
        s.update_item(uuid4(), item['id'], active=True)


def test_list_items_pages_by_id(store):
    s, _db, _ = store
    w = uuid4()
    for i in range(3):
        s.create_item(w, f'sku-{i}', 'Item', 100, 'THB')
    first = s.list_items(w, limit=2)
    rest = s.list_items(w, limit=2, after=first[-1]['id'])
    assert len(first) == 2 and len(rest) == 1
    assert sorted(str(x['id']) for x in first + rest) == [str(x['id']) for x in first + rest]


# cart and promotion

def test_cart_lines_are_priced_from_the_catalog(store):
    s, _db, _ = store
    w = uuid4()
    cart, a, b = filled_cart(s, w)
    priced = s.get_cart(w, cart['id'])
    assert priced['status'] == 'open' and priced['subtotal_minor'] == 2 * 12000 + 4550
    assert [x['sku'] for x in priced['lines']] == ['cup-01', 'tea-01']
    s.set_line(w, cart['id'], a['id'], 1)
    assert s.get_cart(w, cart['id'])['subtotal_minor'] == 12000 + 4550
    s.set_line(w, cart['id'], b['id'], 0)
    assert [x['sku'] for x in s.get_cart(w, cart['id'])['lines']] == ['tea-01']


def test_cart_rejects_foreign_currency_inactive_and_unknown_items(store):
    s, _db, _ = store
    w = uuid4()
    usd = s.create_item(w, 'usd-01', 'Priced in USD', 100, 'USD')
    off = s.create_item(w, 'off-01', 'Withdrawn', 100, 'THB')
    s.update_item(w, off['id'], active=False)
    cart = s.create_cart(w, 'THB')
    with pytest.raises(ValueError):
        s.set_line(w, cart['id'], usd['id'], 1)
    with pytest.raises(Conflict):
        s.set_line(w, cart['id'], off['id'], 1)
    with pytest.raises(NotFound):
        s.set_line(w, cart['id'], uuid4(), 1)
    with pytest.raises(ValueError):
        s.set_line(w, cart['id'], usd['id'], 1001)


def test_carts_are_invisible_to_other_workspaces(store):
    s, _db, _ = store
    w, other = uuid4(), uuid4()
    cart, a, _b = filled_cart(s, w)
    assert s.get_cart(other, cart['id']) is None
    with pytest.raises(NotFound):
        s.set_line(other, cart['id'], a['id'], 1)


def test_promotion_applies_by_code_and_follows_its_rules(store):
    s, _db, _ = store
    w = uuid4()
    cart, _a, _b = filled_cart(s, w)
    s.create_promotion(w, 'TENOFF', 'THB', percent_off=10)
    s.create_promotion(w, 'BIGSPEND', 'THB', amount_off_minor=5000, min_subtotal_minor=10**6)
    with pytest.raises(Conflict):
        s.create_promotion(w, 'TENOFF', 'THB', percent_off=20)
    with pytest.raises(NotFound):
        s.set_promotion(w, cart['id'], 'MISSING')
    priced = s.set_promotion(w, cart['id'], 'TENOFF')
    assert priced['promotion_applied'] is True and priced['discount_minor'] == 28550 // 10
    priced = s.set_promotion(w, cart['id'], 'BIGSPEND')
    assert priced['promotion_applied'] is False and priced['total_minor'] == 28550
    assert s.set_promotion(w, cart['id'], None)['promotion_code'] is None
    with pytest.raises(NotFound):
        s.set_promotion(uuid4(), cart['id'], 'TENOFF')


@pytest.mark.parametrize('kwargs', [
    {},
    {'percent_off': 10, 'amount_off_minor': 10},
    {'percent_off': 0},
    {'amount_off_minor': -5},
    {'percent_off': 10, 'min_subtotal_minor': -1},
])
def test_invalid_promotions_are_rejected(store, kwargs):
    s, _db, _ = store
    with pytest.raises(ValueError):
        s.create_promotion(uuid4(), 'CODE', 'THB', **kwargs)


# orders: duplicate order protection

def test_concurrent_replays_of_one_key_create_one_order(store):
    s, _db, _ = store
    w, actor = uuid4(), uuid4()
    cart, _a, _b = filled_cart(s, w)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: s.place_order(w, actor, 'order-1', cart['id']), range(4)))
    assert len({r[0]['id'] for r in results}) == 1
    assert sorted(created for _order, created in results) == [False, False, False, True]
    assert len(s.list_orders(w)) == 1


def test_changed_request_for_a_key_is_a_conflict(store):
    s, _db, _ = store
    w, actor = uuid4(), uuid4()
    cart, _a, _b = filled_cart(s, w)
    other_cart = s.create_cart(w, 'THB')
    order, created = s.place_order(w, actor, 'order-1', cart['id'])
    assert created and s.place_order(w, actor, 'order-1', cart['id']) == (order, False)
    with pytest.raises(Conflict):
        s.place_order(w, actor, 'order-1', other_cart['id'])
    with pytest.raises(Conflict):
        s.place_order(w, actor, 'order-1', cart['id'], expected_total_minor=1)


def test_a_cart_becomes_at_most_one_order_even_under_different_keys(store):
    s, _db, _ = store
    w, actor = uuid4(), uuid4()
    cart, a, _b = filled_cart(s, w)

    def place(i):
        try:
            return s.place_order(w, actor, f'key-{i}', cart['id'])[0]['id']
        except Conflict:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(place, range(4)))
    assert len([x for x in ids if x is not None]) == 1
    assert s.get_cart(w, cart['id'])['status'] == 'ordered'
    with pytest.raises(Conflict):
        s.set_line(w, cart['id'], a['id'], 5)
    with pytest.raises(Conflict):
        s.set_promotion(w, cart['id'], None)


def test_order_snapshots_prices_and_rejects_a_stale_expected_total(store):
    s, _db, _ = store
    w, actor = uuid4(), uuid4()
    cart, a, _b = filled_cart(s, w)
    s.create_promotion(w, 'TENOFF', 'THB', percent_off=10)
    s.set_promotion(w, cart['id'], 'TENOFF')
    quoted = s.get_cart(w, cart['id'])['total_minor']
    s.update_item(w, a['id'], unit_price_minor=13000)
    with pytest.raises(Conflict):
        s.place_order(w, actor, 'stale', cart['id'], expected_total_minor=quoted)
    fresh = s.get_cart(w, cart['id'])['total_minor']
    order, created = s.place_order(w, actor, 'fresh', cart['id'], expected_total_minor=fresh)
    assert created and order['total_minor'] == fresh and order['status'] == 'placed'
    assert order['discount_minor'] == (2 * 13000 + 4550) // 10 and order['promotion_code'] == 'TENOFF'
    s.update_item(w, a['id'], unit_price_minor=1)
    assert s.get_order(w, order['id'])['total_minor'] == fresh
    assert s.place_order(w, actor, 'fresh', cart['id'], expected_total_minor=fresh) == (order, False)


def test_empty_or_unavailable_cart_cannot_be_ordered(store):
    s, _db, _ = store
    w, actor = uuid4(), uuid4()
    with pytest.raises(ValueError):
        s.place_order(w, actor, 'empty', s.create_cart(w, 'THB')['id'])
    cart, a, _b = filled_cart(s, w)
    s.update_item(w, a['id'], active=False)
    with pytest.raises(Conflict):
        s.place_order(w, actor, 'withdrawn', cart['id'])
    with pytest.raises(NotFound):
        s.place_order(uuid4(), actor, 'foreign', cart['id'])


@pytest.mark.parametrize('key', ['', 'has space', 'x' * 129])
def test_idempotency_key_shape_is_enforced(store, key):
    s, _db, _ = store
    w = uuid4()
    cart, _a, _b = filled_cart(s, w)
    with pytest.raises(ValueError):
        s.place_order(w, uuid4(), key, cart['id'])


# orders: state and payment boundary

def test_cancel_is_a_terminal_idempotent_transition(store):
    s, _db, _ = store
    w, actor = uuid4(), uuid4()
    cart, _a, _b = filled_cart(s, w)
    order, _ = s.place_order(w, actor, 'order-1', cart['id'])
    cancelled = s.cancel_order(w, order['id'])
    assert cancelled['status'] == 'cancelled' and cancelled['cancelled_at'] is not None
    assert s.cancel_order(w, order['id']) == cancelled
    with pytest.raises(NotFound):
        s.cancel_order(uuid4(), order['id'])
    assert s.get_order(uuid4(), order['id']) is None


def test_no_order_can_reach_a_payment_state(store):
    s, db, _ = store
    w = uuid4()
    cart, _a, _b = filled_cart(s, w)
    order, _ = s.place_order(w, uuid4(), 'order-1', cart['id'])
    for status in ('paid', 'captured', 'refunded'):
        with db.transaction(w) as c, pytest.raises(psycopg.errors.CheckViolation):
            c.execute('UPDATE commerce_order SET status=%s WHERE id=%s', (status, order['id']))


def test_forced_rls_rejects_writes_for_another_workspace(store):
    _s, db, _ = store
    w = uuid4()
    with db.transaction(w) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("INSERT INTO catalog_item(workspace_id,id,sku,name,unit_price_minor,currency) "
                  "VALUES (%s,%s,'x','x',1,'THB')", (uuid4(), uuid4()))


def test_ready_requires_current_schema(store):
    s, _db, temp = store
    assert s.ready() is True
    with psycopg.connect(temp.admin_dsn) as admin:
        admin.execute('ALTER TABLE commerce_order NO FORCE ROW LEVEL SECURITY')
    assert s.ready() is False
