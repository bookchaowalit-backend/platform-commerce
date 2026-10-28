"""Deterministic pricing in integer minor units of one currency.

No floats and no currency conversion. A percent discount is rounded down to the
minor unit; an amount discount is capped at the subtotal, so a total is never
negative. Lines are priced in SKU order, so input order never changes a result.
"""
import re

CURRENCY = re.compile(r'[A-Z]{3}')
MAX_UNIT_PRICE_MINOR = 10**10
MAX_QUANTITY = 1000
MAX_SUBTOTAL_MINOR = 10**12


def is_int(value):
    return type(value) is int


def valid_currency(value):
    return isinstance(value, str) and CURRENCY.fullmatch(value) is not None


def _discount(subtotal, currency, promotion):
    if promotion is None:
        return 0, False
    percent, amount = promotion.get('percent_off'), promotion.get('amount_off_minor')
    if (percent is None) == (amount is None):
        raise ValueError('Invalid promotion')
    if percent is not None and not (is_int(percent) and 1 <= percent <= 100):
        raise ValueError('Invalid promotion')
    if amount is not None and not (is_int(amount) and 1 <= amount <= MAX_UNIT_PRICE_MINOR):
        raise ValueError('Invalid promotion')
    minimum = promotion.get('min_subtotal_minor', 0)
    if not (is_int(minimum) and 0 <= minimum <= MAX_SUBTOTAL_MINOR):
        raise ValueError('Invalid promotion')
    if promotion.get('active') is not True or promotion.get('currency') != currency or subtotal < minimum:
        return 0, False
    discount = subtotal * percent // 100 if percent is not None else min(amount, subtotal)
    return discount, True


def quote(currency, lines, promotion=None):
    """Price ``lines`` (dicts with item_id, sku, name, unit_price_minor, quantity)."""
    if not valid_currency(currency):
        raise ValueError('Invalid currency')
    priced = []
    for line in sorted(lines, key=lambda x: (x['sku'], str(x['item_id']))):
        unit, quantity = line['unit_price_minor'], line['quantity']
        if not (is_int(unit) and 0 <= unit <= MAX_UNIT_PRICE_MINOR):
            raise ValueError('Invalid price')
        if not (is_int(quantity) and 1 <= quantity <= MAX_QUANTITY):
            raise ValueError('Invalid quantity')
        priced.append({'item_id': line['item_id'], 'sku': line['sku'], 'name': line['name'],
                       'unit_price_minor': unit, 'quantity': quantity, 'line_total_minor': unit * quantity})
    subtotal = sum(x['line_total_minor'] for x in priced)
    discount, applied = _discount(subtotal, currency, promotion)
    return {'currency': currency, 'lines': priced, 'subtotal_minor': subtotal, 'discount_minor': discount,
            'total_minor': subtotal - discount, 'promotion_code': None if promotion is None else promotion.get('code'),
            'promotion_applied': applied}
