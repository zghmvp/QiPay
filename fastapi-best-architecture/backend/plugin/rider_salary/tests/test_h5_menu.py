from datetime import date, datetime
from decimal import Decimal

import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.schema.calendar import (
    CalendarAdjustmentItem,
    CalendarDailyItem,
    CalendarDayItem,
    CalendarDayOrder,
    CalendarDayTotals,
    CalendarHitDetail,
    CalendarMonthSummary,
    GetCalendarDayDetail,
    GetCalendarMonth,
)
from backend.plugin.rider_salary.schema.me import GetMeAdvanceLimit, GetMePayrollEstimate
from backend.plugin.rider_salary.service.h5_menu import (
    CLOSED_MESSAGE,
    assert_feature_open,
    builtin_flags,
    flags_from_values,
    is_feature_open,
    mask_advance_limit,
    mask_calendar_month,
    mask_day_detail,
    mask_payroll_estimate,
    resolve_h5_menu,
)


def _row(**overrides: bool):
    return flags_from_values(source='stored', **overrides)


def test_builtin_opens_every_switch() -> None:
    flags = builtin_flags()
    assert flags.source == 'builtin'
    assert flags.show_adjustments is True
    assert flags.show_home is True
    assert flags.show_home_pay is True
    assert flags.show_day_amount is True
    assert flags.show_estimate_net is True
    assert flags.show_advance_inflight is True


def test_site_row_overrides_global_as_a_whole() -> None:
    site = _row(show_advance=True, show_plan=False, show_home_pay=False, show_estimate_net=True)
    global_row = _row(
        show_advance=False,
        show_plan=True,
        show_notices=False,
        show_home_pay=True,
        show_estimate_net=False,
    )
    flags = resolve_h5_menu(site, global_row)
    assert flags.source == 'site'
    assert flags.show_advance is True
    assert flags.show_plan is False
    assert flags.show_notices is True
    assert flags.show_home_pay is False
    assert flags.show_estimate_net is True


def test_missing_site_uses_global() -> None:
    global_row = _row(show_adjustments=False, show_home=False, show_day_amount=False)
    flags = resolve_h5_menu(None, global_row)
    assert flags.source == 'global'
    assert flags.show_adjustments is False
    assert flags.show_home is False
    assert flags.show_day_amount is False
    assert flags.show_advance is True
    assert flags.show_home_pay is True


def test_no_rows_fall_back_to_builtin() -> None:
    assert resolve_h5_menu(None, None) == builtin_flags()


@pytest.mark.parametrize(
    ('feature', 'field'),
    [
        ('adjustments', 'show_adjustments'),
        ('advance', 'show_advance'),
        ('notices', 'show_notices'),
        ('plan', 'show_plan'),
        ('home', 'show_home'),
    ],
)
def test_closed_feature_is_rejected_and_others_stay_open(feature: str, field: str) -> None:
    flags = _row(**{field: False})
    assert is_feature_open(flags, feature) is False
    with pytest.raises(errors.ForbiddenError, match=CLOSED_MESSAGE):
        assert_feature_open(flags, feature)
    for other in ('adjustments', 'advance', 'notices', 'plan', 'home'):
        if other != feature:
            assert_feature_open(flags, other)


def test_home_closed_also_closes_calendar_day_and_payroll() -> None:
    flags = _row(show_home=False)
    for feature in ('home', 'day', 'calendar', 'payroll'):
        with pytest.raises(errors.ForbiddenError, match=CLOSED_MESSAGE):
            assert_feature_open(flags, feature)
    for feature in ('me', 'profile', 'advance'):
        assert_feature_open(flags, feature)


def test_unknown_feature_stays_open() -> None:
    flags = _row(show_home=False, show_advance=False, show_adjustments=False, show_notices=False, show_plan=False)
    assert_feature_open(flags, 'me')
    assert_feature_open(flags, 'profile')


def test_home_pay_off_clears_amounts_and_keeps_order_count() -> None:
    flags = _row(show_home_pay=False)
    row = GetMePayrollEstimate(
        period_range='2026-10-01 ~ 2026-10-31',
        period_status='open',
        order_count=12,
        gross=Decimal('100.00'),
        deduction_total=Decimal('5.00'),
        advance_deduction_estimate=Decimal('3.00'),
        net_estimate=Decimal('92.00'),
        is_estimate=True,
        updated_at=None,
    )
    masked = mask_payroll_estimate(flags, row)
    assert masked.order_count == 12
    assert masked.gross is None
    assert masked.deduction_total is None
    assert masked.advance_deduction_estimate is None
    assert masked.net_estimate is None
    assert mask_payroll_estimate(builtin_flags(), row).net_estimate == Decimal('92.00')


def test_day_amount_off_clears_calendar_and_day_money() -> None:
    flags = _row(show_day_amount=False)
    month = GetCalendarMonth(
        month='2026-10',
        summary=CalendarMonthSummary(
            order_count=4,
            valid_order_count=3,
            gross=Decimal('10'),
            bonus=Decimal('1'),
            penalty=Decimal('2'),
            deduction_total=Decimal('3'),
            advance_deduction=Decimal('4'),
            net=Decimal('5'),
        ),
        days=[
            CalendarDayItem(
                date=date(2026, 10, 1),
                order_count=2,
                valid_order_count=2,
                net_adjust=Decimal('8.00'),
                day_status='normal',
            )
        ],
    )
    masked_month = mask_calendar_month(flags, month)
    assert masked_month.summary.order_count == 4
    assert masked_month.summary.net is None
    assert masked_month.summary.gross is None
    assert masked_month.days[0].order_count == 2
    assert masked_month.days[0].net_adjust is None

    detail = GetCalendarDayDetail(
        date=date(2026, 10, 1),
        day_status='normal',
        orders=[
            CalendarDayOrder(
                id=1,
                order_no='A1',
                distance_km=Decimal('1'),
                weight_jin=Decimal('2'),
                order_time=datetime(2026, 10, 1, 8, 0),
                status='completed',
                amount=Decimal('9.50'),
                details=[CalendarHitDetail(subject='配送费', amount=Decimal('6'), calc_trace={'step': 1})],
            )
        ],
        daily_items=[CalendarDailyItem(subject='日奖', amount=Decimal('1'), calc_trace={'step': 2})],
        adjustments=[
            CalendarAdjustmentItem(id=7, subject='罚款', direction='penalty', amount=Decimal('-2'), remark='')
        ],
        totals=CalendarDayTotals(
            order_count=2,
            formula_amount=Decimal('6'),
            manual_bonus=Decimal('1'),
            manual_penalty=Decimal('-2'),
            net=Decimal('5'),
        ),
    )
    masked = mask_day_detail(flags, detail)
    assert masked.totals.order_count == 2
    assert masked.totals.net is None
    assert masked.orders[0].order_no == 'A1'
    assert masked.orders[0].amount is None
    assert masked.orders[0].details[0].amount is None
    assert masked.orders[0].details[0].calc_trace is None
    assert masked.daily_items[0].amount is None
    assert masked.daily_items[0].calc_trace is None
    assert masked.adjustments[0].subject == '罚款'
    assert masked.adjustments[0].amount is None
    assert_feature_open(flags, 'day')


def test_advance_fields_clear_independently_and_keep_available() -> None:
    flags = _row(show_estimate_net=False, show_advance_inflight=False)
    row = GetMeAdvanceLimit(
        limit=Decimal('100'),
        used_pending_amount=Decimal('20'),
        available=Decimal('80'),
        estimate_net=Decimal('200'),
        order_count=9,
        amount_mode='percent',
        percent=Decimal('50'),
        monthly_used_count=1,
        monthly_max_count=2,
        min_amount=Decimal('1'),
        eligible=True,
        reasons=[],
        basis_text='按当前周期预估实发的 50%',
        period_range='2026-10-01 ~ 2026-10-31',
        period_status='open',
    )
    masked = mask_advance_limit(flags, row)
    assert masked.estimate_net is None
    assert masked.used_pending_amount is None
    assert masked.available == Decimal('80')
    assert masked.order_count == 9
    assert masked.limit == Decimal('100')
    assert_feature_open(flags, 'advance')

    only_net = mask_advance_limit(_row(show_estimate_net=False), row)
    assert only_net.estimate_net is None
    assert only_net.used_pending_amount == Decimal('20')
    assert only_net.available == Decimal('80')
