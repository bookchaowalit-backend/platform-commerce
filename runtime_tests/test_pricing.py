"""Deterministic integer pricing: no floats, no rounding surprises, no negative totals."""
import pytest

from platform_commerce.pricing import quote


def line(sku, unit, quantity):
    return {'item_id': 'item-' + sku, 'sku': sku, 'name': 'Item ' + sku, 'unit_price_minor': unit, 'quantity': quantity}


def promo(**overrides):
    base = {'code': 'SAVE', 'percent_off': None, 'amount_off_minor': None, 'currency': 'THB',
            'min_subtotal_minor': 0, 'active': True}
    base.update(overrides)
    return base


def test_subtotal_and_lines_are_integer_minor_units_sorted_by_sku():
    result = quote('THB', [line('b', 250, 2), line('a', 1999, 1)])
    assert [x['sku'] for x in result['lines']] == ['a', 'b']
    assert [x['line_total_minor'] for x in result['lines']] == [1999, 500]
    assert result['subtotal_minor'] == 2499 and result['discount_minor'] == 0 and result['total_minor'] == 2499
    assert result['currency'] == 'THB' and result['promotion_applied'] is False
    assert all(type(result[k]) is int for k in ('subtotal_minor', 'discount_minor', 'total_minor'))


def test_percent_promotion_rounds_the_discount_down_to_the_minor_unit():
    result = quote('THB', [line('a', 333, 3)], promo(percent_off=10))
    assert result['subtotal_minor'] == 999 and result['discount_minor'] == 99 and result['total_minor'] == 900
    assert result['promotion_applied'] is True and result['promotion_code'] == 'SAVE'


def test_amount_promotion_is_capped_so_the_total_never_goes_negative():
    result = quote('THB', [line('a', 300, 1)], promo(amount_off_minor=500))
    assert result['discount_minor'] == 300 and result['total_minor'] == 0


@pytest.mark.parametrize('promotion', [
    promo(percent_off=10, min_subtotal_minor=1000),
    promo(percent_off=10, active=False),
    promo(amount_off_minor=100, currency='USD'),
])
def test_promotion_that_does_not_qualify_changes_nothing(promotion):
    result = quote('THB', [line('a', 999, 1)], promotion)
    assert result['discount_minor'] == 0 and result['total_minor'] == 999
    assert result['promotion_applied'] is False and result['promotion_code'] == 'SAVE'


def test_minimum_subtotal_is_inclusive():
    assert quote('THB', [line('a', 1000, 1)], promo(percent_off=50, min_subtotal_minor=1000))['total_minor'] == 500


def test_input_order_does_not_change_the_result():
    lines = [line('c', 7, 3), line('a', 11, 2), line('b', 13, 1)]
    assert quote('THB', lines, promo(percent_off=33)) == quote('THB', list(reversed(lines)), promo(percent_off=33))


def test_empty_cart_quotes_zero():
    result = quote('THB', [], promo(amount_off_minor=100))
    assert result['subtotal_minor'] == 0 and result['total_minor'] == 0 and result['lines'] == []


@pytest.mark.parametrize('bad', [
    [line('a', 1.5, 1)],
    [line('a', True, 1)],
    [line('a', -1, 1)],
    [line('a', 100, 0)],
    [line('a', 100, True)],
    [line('a', 100, 1001)],
])
def test_non_integer_or_out_of_range_lines_are_rejected(bad):
    with pytest.raises(ValueError):
        quote('THB', bad)


@pytest.mark.parametrize('currency', ['thb', 'BAHT', '', None])
def test_currency_must_be_an_iso_code(currency):
    with pytest.raises(ValueError):
        quote(currency, [line('a', 1, 1)])


@pytest.mark.parametrize('promotion', [
    promo(),
    promo(percent_off=10, amount_off_minor=10),
    promo(percent_off=0),
    promo(percent_off=101),
    promo(percent_off=12.5),
    promo(amount_off_minor=0),
])
def test_malformed_promotion_is_rejected(promotion):
    with pytest.raises(ValueError):
        quote('THB', [line('a', 100, 1)], promotion)
