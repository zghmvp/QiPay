from datetime import date
from decimal import Decimal

from backend.plugin.rider_salary.enums import PeriodStatus
from backend.plugin.rider_salary.service.advance_quote import builtin_rule, quote_advance


def _quote(**overrides: object):
    rule = builtin_rule()
    params = {
        'rule': rule,
        'estimate_net': Decimal('2000.00'),
        'order_count': 10,
        'period_status': PeriodStatus.open.value,
        'period_range': '2026-10-01 ~ 2026-10-31',
        'hire_date': date(2026, 1, 1),
        'today': date(2026, 10, 15),
        'on_job': True,
        'rider_limit': None,
        'site_limit': None,
        'in_flight_amount': Decimal('0'),
        'in_flight_count': 0,
        'monthly_count': 0,
    }
    params.update(overrides)
    return quote_advance(**params)  # type: ignore[arg-type]


def test_percent_of_estimate_net() -> None:
    quote = _quote()
    assert quote.limit == Decimal('1000.00')
    assert quote.available == Decimal('1000.00')
    assert quote.eligible is True
    assert '50' in quote.basis_text


def test_in_flight_reduces_available_but_does_not_hide_remainder() -> None:
    quote = _quote(in_flight_amount=Decimal('200.00'), in_flight_count=1)
    assert quote.available == Decimal('800.00')
    assert quote.eligible is False
    assert quote.reasons


def test_fixed_amount_is_capped_by_rider_limit() -> None:
    rule = builtin_rule()
    rule = type(rule)(
        amount_mode='fixed',
        percent=rule.percent,
        fixed_amount=Decimal('3000.00'),
        max_amount=None,
        monthly_max_count=rule.monthly_max_count,
        min_tenure_days=rule.min_tenure_days,
        min_completed_orders=rule.min_completed_orders,
        min_amount=rule.min_amount,
    )
    quote = _quote(rule=rule, rider_limit=Decimal('500'))
    assert quote.limit == Decimal('500.00')
    assert quote.eligible is True


def test_tenure_blocks_new_hire() -> None:
    quote = _quote(hire_date=date(2026, 10, 14))
    assert quote.available == Decimal('0.00')
    assert quote.eligible is False
    assert any('入职' in item for item in quote.reasons)


def test_locked_period_does_not_block() -> None:
    quote = _quote(period_status=PeriodStatus.locked.value)
    assert quote.eligible is True
    assert quote.available == Decimal('1000.00')


def test_monthly_count_blocks() -> None:
    quote = _quote(monthly_count=2)
    assert quote.available == Decimal('0.00')
    assert any('次数' in item for item in quote.reasons)


def test_negative_net_has_no_percent_quota() -> None:
    quote = _quote(estimate_net=Decimal('-20.00'), order_count=3)
    assert quote.available == Decimal('0.00')
    assert quote.eligible is False
