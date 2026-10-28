"""Workspace-scoped catalog, promotion, cart and order state.

Every method opens ``Database.transaction(workspace)``, so forced row-level security
limits each statement to the verified workspace. Errors carry fixed messages only.
"""
import hashlib
import json
import re
import unicodedata
from datetime import datetime
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from .migrations import MIGRATIONS, TABLES
from .pricing import (
    MAX_SUBTOTAL_MINOR,
    MAX_UNIT_PRICE_MINOR,
    is_int,
    quote,
    valid_currency,
)


class Conflict(Exception):
    """A state conflict; ``reason`` is one fixed, payload-free string."""

    def __init__(self, reason='Conflict'):
        super().__init__(reason)
        self.reason = reason


class NotFound(Exception):
    pass


class InvalidInput(ValueError):
    """Client input the service refuses (HTTP 422). Any other error is a server fault (500)."""


_UNSET = object()


SKU = re.compile(r'[A-Za-z0-9._-]{1,64}')
CODE = re.compile(r'[A-Z0-9_-]{1,32}')
KEY = re.compile(r'[A-Za-z0-9_.:-]{1,128}')
MAX_CART_LINES = 100
ITEM = 'id,sku,name,unit_price_minor,currency,active,created_at,updated_at'
PROMOTION = 'id,code,currency,percent_off,amount_off_minor,min_subtotal_minor,active,ends_at,created_at'
# A promotion prices a cart only while active and before its optional expiry.
LIVE_PROMOTION = 'active AND (ends_at IS NULL OR ends_at > clock_timestamp())'
ORDER = 'id,cart_id,status,currency,subtotal_minor,discount_minor,total_minor,promotion_code,created_at,cancelled_at'
ORDER_LINE = 'item_id,sku,name,unit_price_minor,quantity,line_total_minor'

# Runtime grants the service needs, each checked on its own by readiness.
REQUIRED_PRIVILEGES = (
    ('catalog_item', 'SELECT'), ('catalog_item', 'INSERT'), ('catalog_item', 'UPDATE'),
    ('promotion', 'SELECT'), ('promotion', 'INSERT'), ('promotion', 'UPDATE'),
    ('cart', 'SELECT'), ('cart', 'INSERT'), ('cart', 'UPDATE'),
    ('cart_line', 'SELECT'), ('cart_line', 'INSERT'), ('cart_line', 'UPDATE'), ('cart_line', 'DELETE'),
    ('commerce_order', 'SELECT'), ('commerce_order', 'INSERT'), ('commerce_order', 'UPDATE'),
    ('order_line', 'SELECT'), ('order_line', 'INSERT'),
)


def valid_name(value):
    return (isinstance(value, str) and 1 <= len(value) <= 200 and bool(value.strip())
            and not any(unicodedata.category(x)[0] == 'C' or unicodedata.category(x) in ('Zl', 'Zp') for x in value))


def valid_price(value):
    return is_int(value) and 0 <= value <= MAX_UNIT_PRICE_MINOR


def order_fingerprint(cart_id, expected_total_minor):
    return hashlib.sha256(json.dumps([str(cart_id), expected_total_minor], separators=(',', ':')).encode()).hexdigest()


class CommerceStore:
    def __init__(self, database):
        self.db = database

    def _tx(self, workspace):
        return self.db.transaction(workspace)

    # catalog

    def create_item(self, workspace, sku, name, unit_price_minor, currency):
        if not isinstance(sku, str) or not SKU.fullmatch(sku):
            raise InvalidInput('Invalid sku')
        if not valid_name(name) or not valid_price(unit_price_minor) or not valid_currency(currency):
            raise InvalidInput('Invalid item')
        with self._tx(workspace) as conn, conn.cursor(row_factory=dict_row) as c:
            row = c.execute(f'INSERT INTO catalog_item(workspace_id,id,sku,name,unit_price_minor,currency) '
                            f'VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(workspace_id,sku) DO NOTHING RETURNING {ITEM}',
                            (workspace, uuid4(), sku, name, unit_price_minor, currency)).fetchone()
        if row is None:
            raise Conflict('Duplicate')
        return row

    def update_item(self, workspace, item_id, *, name=None, unit_price_minor=None, active=None):
        if name is not None and not valid_name(name):
            raise InvalidInput('Invalid item')
        if unit_price_minor is not None and not valid_price(unit_price_minor):
            raise InvalidInput('Invalid item')
        if active is not None and type(active) is not bool:
            raise InvalidInput('Invalid item')
        with self._tx(workspace) as conn, conn.cursor(row_factory=dict_row) as c:
            row = c.execute(f'UPDATE catalog_item SET name=coalesce(%s,name),unit_price_minor=coalesce(%s,unit_price_minor),'
                            f'active=coalesce(%s,active),updated_at=clock_timestamp() WHERE id=%s RETURNING {ITEM}',
                            (name, unit_price_minor, active, item_id)).fetchone()
        if row is None:
            raise NotFound()
        return row

    def get_item(self, workspace, item_id):
        with self._tx(workspace) as conn, conn.cursor(row_factory=dict_row) as c:
            return c.execute(f'SELECT {ITEM} FROM catalog_item WHERE id=%s', (item_id,)).fetchone()

    def list_items(self, workspace, limit=100, after=None):
        if not is_int(limit) or not 1 <= limit <= 100:
            raise InvalidInput('Invalid limit')
        with self._tx(workspace) as conn, conn.cursor(row_factory=dict_row) as c:
            return c.execute(f'SELECT {ITEM} FROM catalog_item WHERE (%s::uuid IS NULL OR id>%s::uuid) ORDER BY id LIMIT %s',
                             (after, after, limit)).fetchall()

    # promotions

    def create_promotion(self, workspace, code, currency, *, percent_off=None, amount_off_minor=None, min_subtotal_minor=0):
        if not isinstance(code, str) or not CODE.fullmatch(code) or not valid_currency(currency):
            raise InvalidInput('Invalid promotion')
        if (percent_off is None) == (amount_off_minor is None):
            raise InvalidInput('Invalid promotion')
        if percent_off is not None and not (is_int(percent_off) and 1 <= percent_off <= 100):
            raise InvalidInput('Invalid promotion')
        if amount_off_minor is not None and not (is_int(amount_off_minor) and 1 <= amount_off_minor <= MAX_UNIT_PRICE_MINOR):
            raise InvalidInput('Invalid promotion')
        if not (is_int(min_subtotal_minor) and 0 <= min_subtotal_minor <= MAX_SUBTOTAL_MINOR):
            raise InvalidInput('Invalid promotion')
        with self._tx(workspace) as conn, conn.cursor(row_factory=dict_row) as c:
            row = c.execute(f'INSERT INTO promotion(workspace_id,id,code,currency,percent_off,amount_off_minor,min_subtotal_minor) '
                            f'VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(workspace_id,code) DO NOTHING RETURNING {PROMOTION}',
                            (workspace, uuid4(), code, currency, percent_off, amount_off_minor, min_subtotal_minor)).fetchone()
        if row is None:
            raise Conflict('Duplicate')
        return row

    def update_promotion(self, workspace, promotion_id, *, active=None, ends_at=_UNSET):
        """Withdraw or restore a promotion, or set (``None`` clears) its expiry.

        Carts that carry the code price without it from then on; placing an order re-checks.
        """
        if active is None and ends_at is _UNSET:
            raise InvalidInput('Invalid promotion')
        if active is not None and type(active) is not bool:
            raise InvalidInput('Invalid promotion')
        if ends_at is not _UNSET and ends_at is not None and not (
                isinstance(ends_at, datetime) and ends_at.utcoffset() is not None):
            raise InvalidInput('Invalid promotion')
        with self._tx(workspace) as conn, conn.cursor(row_factory=dict_row) as c:
            row = c.execute(f'UPDATE promotion SET active=coalesce(%s,active),'
                            f'ends_at=CASE WHEN %s THEN %s ELSE ends_at END WHERE id=%s RETURNING {PROMOTION}',
                            (active, ends_at is not _UNSET, None if ends_at is _UNSET else ends_at,
                             promotion_id)).fetchone()
        if row is None:
            raise NotFound()
        return row

    def list_promotions(self, workspace, limit=100, after=None):
        if not is_int(limit) or not 1 <= limit <= 100:
            raise InvalidInput('Invalid limit')
        with self._tx(workspace) as conn, conn.cursor(row_factory=dict_row) as c:
            return c.execute(f'SELECT {PROMOTION} FROM promotion WHERE (%s::uuid IS NULL OR id>%s::uuid) ORDER BY id LIMIT %s',
                             (after, after, limit)).fetchall()

    # carts

    def create_cart(self, workspace, currency):
        if not valid_currency(currency):
            raise InvalidInput('Invalid currency')
        cart_id = uuid4()
        with self._tx(workspace) as conn:
            conn.execute('INSERT INTO cart(workspace_id,id,currency) VALUES (%s,%s,%s)', (workspace, cart_id, currency))
            return self._priced_cart(conn, cart_id)

    def get_cart(self, workspace, cart_id):
        with self._tx(workspace) as conn:
            return self._priced_cart(conn, cart_id)

    def set_line(self, workspace, cart_id, item_id, quantity):
        """Set an item's quantity in an open cart; 0 removes the line."""
        if not (is_int(quantity) and 0 <= quantity <= 1000):
            raise InvalidInput('Invalid quantity')
        with self._tx(workspace) as conn, conn.cursor(row_factory=dict_row) as c:
            cart = self._lock_open_cart(c, cart_id)
            if quantity == 0:
                c.execute('DELETE FROM cart_line WHERE cart_id=%s AND item_id=%s', (cart_id, item_id))
            else:
                item = c.execute('SELECT currency,active FROM catalog_item WHERE id=%s', (item_id,)).fetchone()
                if item is None:
                    raise NotFound()
                if item['currency'] != cart['currency']:
                    raise InvalidInput('Invalid currency')
                if not item['active']:
                    raise Conflict('Item unavailable')
                c.execute('INSERT INTO cart_line(workspace_id,cart_id,item_id,quantity) VALUES (%s,%s,%s,%s) '
                          'ON CONFLICT(workspace_id,cart_id,item_id) DO UPDATE SET quantity=excluded.quantity',
                          (workspace, cart_id, item_id, quantity))
                if c.execute('SELECT count(*) AS n FROM cart_line WHERE cart_id=%s', (cart_id,)).fetchone()['n'] > MAX_CART_LINES:
                    raise InvalidInput('Too many lines')
            c.execute('UPDATE cart SET updated_at=clock_timestamp() WHERE id=%s', (cart_id,))
            return self._priced_cart(conn, cart_id)

    def set_promotion(self, workspace, cart_id, code):
        """Attach a promotion code to an open cart, or detach it with ``None``."""
        if code is not None and (not isinstance(code, str) or not CODE.fullmatch(code)):
            raise InvalidInput('Invalid promotion')
        with self._tx(workspace) as conn, conn.cursor(row_factory=dict_row) as c:
            self._lock_open_cart(c, cart_id)
            if code is not None and c.execute('SELECT 1 FROM promotion WHERE code=%s', (code,)).fetchone() is None:
                raise NotFound()
            c.execute('UPDATE cart SET promotion_code=%s,updated_at=clock_timestamp() WHERE id=%s', (code, cart_id))
            return self._priced_cart(conn, cart_id)

    @staticmethod
    def _lock_open_cart(c, cart_id):
        cart = c.execute('SELECT currency,status FROM cart WHERE id=%s FOR UPDATE', (cart_id,)).fetchone()
        if cart is None:
            raise NotFound()
        if cart['status'] != 'open':
            raise Conflict('Cart is not open')
        return cart

    @staticmethod
    def _priced_cart(conn, cart_id, *, for_order=False):
        """An open cart at current prices; an ordered cart as its order's snapshot.

        ``for_order`` (inside ``place_order``) refuses withdrawn items and share-locks the
        catalog and promotion rows it prices, so no price or promotion change can commit
        between pricing and the order commit.
        """
        lock = ' FOR SHARE' if for_order else ''
        with conn.cursor(row_factory=dict_row) as c:
            cart = c.execute('SELECT id,currency,status,promotion_code,created_at,updated_at FROM cart WHERE id=%s',
                             (cart_id,)).fetchone()
            if cart is None:
                return None
            if cart['status'] == 'ordered':
                order_id = c.execute('SELECT id FROM commerce_order WHERE cart_id=%s', (cart_id,)).fetchone()['id']
                order = CommerceStore._order(c, order_id)
                return {**cart, 'order_id': order_id, 'lines': order['lines'],
                        **{k: order[k] for k in ('currency', 'subtotal_minor', 'discount_minor', 'total_minor')},
                        'promotion_applied': order['promotion_code'] is not None}
            lines = c.execute('SELECT l.item_id,i.sku,i.name,i.unit_price_minor,l.quantity,i.active FROM cart_line l '
                              'JOIN catalog_item i ON i.workspace_id=l.workspace_id AND i.id=l.item_id '
                              'WHERE l.cart_id=%s ORDER BY i.id' + (' FOR SHARE OF i' if for_order else ''),
                              (cart_id,)).fetchall()
            if for_order and not all(x['active'] for x in lines):
                raise Conflict('Item unavailable')
            for x in lines:
                del x['active']
            promotion = None
            if cart['promotion_code'] is not None:
                promotion = c.execute(f'SELECT {PROMOTION},{LIVE_PROMOTION} AS live FROM promotion WHERE code=%s{lock}',
                                      (cart['promotion_code'],)).fetchone()
                if promotion is not None:
                    promotion['active'] = promotion.pop('live')
        priced = quote(cart['currency'], lines, promotion)
        priced['promotion_code'] = cart['promotion_code']
        return {**cart, 'order_id': None, **priced}

    # orders

    def place_order(self, workspace, actor, key, cart_id, expected_total_minor=None):
        """Place the order for ``cart_id`` once. Returns ``(order, created)``.

        The same key with the same request replays the first order; the same key with a
        different request, or a second order for one cart, raises Conflict. With
        ``expected_total_minor`` the order is placed only at that total.
        """
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise InvalidInput('Invalid key')
        if expected_total_minor is not None and not (is_int(expected_total_minor) and expected_total_minor >= 0):
            raise InvalidInput('Invalid total')
        if not isinstance(actor, UUID) or not isinstance(cart_id, UUID):
            raise TypeError('actor and cart_id must be UUIDs')
        fingerprint = order_fingerprint(cart_id, expected_total_minor)
        with self._tx(workspace) as conn, conn.cursor(row_factory=dict_row) as c:
            # Serialize every request for this key, then every order for this cart.
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f'commerce-order-key:{workspace}:{key}',))
            existing = c.execute('SELECT id,fingerprint FROM commerce_order WHERE idempotency_key=%s', (key,)).fetchone()
            if existing is not None:
                if existing['fingerprint'] != fingerprint:
                    raise Conflict('Idempotency conflict')
                return self._order(c, existing['id']), False
            self._lock_open_cart(c, cart_id)
            priced = self._priced_cart(conn, cart_id, for_order=True)
            if not priced['lines']:
                raise InvalidInput('Empty cart')
            if expected_total_minor is not None and priced['total_minor'] != expected_total_minor:
                raise Conflict('Price changed')
            order_id = uuid4()
            applied = priced['promotion_code'] if priced['promotion_applied'] else None
            c.execute('INSERT INTO commerce_order(workspace_id,id,cart_id,idempotency_key,fingerprint,currency,'
                      'subtotal_minor,discount_minor,total_minor,promotion_code,placed_by) '
                      'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                      (workspace, order_id, cart_id, key, fingerprint, priced['currency'], priced['subtotal_minor'],
                       priced['discount_minor'], priced['total_minor'], applied, actor))
            c.executemany('INSERT INTO order_line(workspace_id,order_id,item_id,sku,name,unit_price_minor,quantity,line_total_minor) '
                          'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                          [(workspace, order_id, x['item_id'], x['sku'], x['name'], x['unit_price_minor'], x['quantity'],
                            x['line_total_minor']) for x in priced['lines']])
            c.execute("UPDATE cart SET status='ordered',updated_at=clock_timestamp() WHERE id=%s", (cart_id,))
            return self._order(c, order_id), True

    def cancel_order(self, workspace, order_id):
        """placed -> cancelled; cancelling a cancelled order returns it unchanged."""
        with self._tx(workspace) as conn, conn.cursor(row_factory=dict_row) as c:
            c.execute("UPDATE commerce_order SET status='cancelled',cancelled_at=clock_timestamp() "
                      "WHERE id=%s AND status='placed'", (order_id,))
            order = self._order(c, order_id)
        if order is None:
            raise NotFound()
        return order

    def get_order(self, workspace, order_id):
        with self._tx(workspace) as conn, conn.cursor(row_factory=dict_row) as c:
            return self._order(c, order_id)

    def list_orders(self, workspace, limit=100, after=None):
        if not is_int(limit) or not 1 <= limit <= 100:
            raise InvalidInput('Invalid limit')
        with self._tx(workspace) as conn, conn.cursor(row_factory=dict_row) as c:
            ids = c.execute('SELECT id FROM commerce_order WHERE (%s::uuid IS NULL OR id>%s::uuid) ORDER BY id LIMIT %s',
                            (after, after, limit)).fetchall()
            return [self._order(c, x['id']) for x in ids]

    @staticmethod
    def _order(c, order_id):
        order = c.execute(f'SELECT {ORDER} FROM commerce_order WHERE id=%s', (order_id,)).fetchone()
        if order is not None:
            order['lines'] = c.execute(f'SELECT {ORDER_LINE} FROM order_line WHERE order_id=%s ORDER BY sku,item_id',
                                       (order_id,)).fetchall()
        return order

    # readiness

    def ready(self):
        with self._tx(UUID(int=0)) as c:
            checks = ["has_schema_privilege(current_user,'public','USAGE')",
                      "has_table_privilege(current_user,'public.platform_schema_migrations','SELECT')"]
            # One call per privilege: a comma-separated privilege list means ANY of them.
            checks += [f"has_table_privilege(current_user,'public.{t}','{p}')" for t, p in REQUIRED_PRIVILEGES]
            if not c.execute('SELECT ' + ' AND '.join(checks)).fetchone()[0]:
                return False
            history = c.execute('SELECT version,checksum FROM platform_schema_migrations WHERE namespace=%s ORDER BY version',
                                ('commerce',)).fetchall()
            if history != [(m.version, m.checksum) for m in MIGRATIONS]:
                return False
            row = c.execute('SELECT count(*)=%s AND bool_and(relrowsecurity AND relforcerowsecurity) FROM pg_class '
                            'WHERE oid IN (SELECT to_regclass(t) FROM unnest(%s::text[]) t)',
                            (len(TABLES), list(TABLES))).fetchone()
            return bool(row and row[0])
