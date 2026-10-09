"""离职结算周期：盖住离职日所在站点周期，并整段盖住碰到的站点级周期。"""

from datetime import date

from backend.plugin.rider_salary.service.period_service import (
    expand_leave_settlement_span,
    leave_settlement_hint,
    leave_settlement_remark,
)


def test_monthly_cycle_stays_the_full_month_when_site_period_matches() -> None:
    """月中离职不能把骑手级周期截到离职日，否则会部分覆盖整月站点周期。"""
    start, end = expand_leave_settlement_span(
        cycle_start=date(2026, 10, 1),
        cycle_end=date(2026, 10, 31),
        site_spans=[(date(2026, 10, 1), date(2026, 10, 31))],
    )
    assert (start, end) == (date(2026, 10, 1), date(2026, 10, 31))


def test_empty_site_periods_still_cover_the_canonical_cycle() -> None:
    """还没有站点级周期时，也按整段站点周期生成，避免以后生成当月失败。"""
    start, end = expand_leave_settlement_span(
        cycle_start=date(2026, 10, 1),
        cycle_end=date(2026, 10, 31),
        site_spans=[],
    )
    assert (start, end) == (date(2026, 10, 1), date(2026, 10, 31))


def test_half_month_does_not_swallow_the_other_half() -> None:
    """上半月和已有的下半月只是相邻，离职结算停在上半月。"""
    start, end = expand_leave_settlement_span(
        cycle_start=date(2026, 10, 1),
        cycle_end=date(2026, 10, 15),
        site_spans=[
            (date(2026, 10, 1), date(2026, 10, 15)),
            (date(2026, 10, 16), date(2026, 10, 31)),
        ],
    )
    assert (start, end) == (date(2026, 10, 1), date(2026, 10, 15))


def test_custom_site_period_expands_until_fully_covered() -> None:
    """自然月碰到更长的站点级周期时，两端都要扩到盖住。"""
    start, end = expand_leave_settlement_span(
        cycle_start=date(2026, 10, 1),
        cycle_end=date(2026, 10, 31),
        site_spans=[(date(2026, 9, 20), date(2026, 10, 19))],
    )
    assert (start, end) == (date(2026, 9, 20), date(2026, 10, 31))


def test_hint_explains_end_after_leave_date() -> None:
    """结束日晚于离职日时，说明计薪仍截至离职日。"""
    hint = leave_settlement_hint(
        date(2026, 10, 15),
        date(2026, 10, 1),
        date(2026, 10, 31),
        reused=False,
    )
    assert '2026-10-01至2026-10-31' in hint
    assert '计薪截至2026-10-15' in hint
    assert '整段覆盖' in hint
    assert leave_settlement_remark(date(2026, 10, 15)) == '离职结算，计薪截至2026-10-15'
