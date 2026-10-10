"""结算周期：同一范围不相交。跨范围整段覆盖只留给离职结算。"""

from datetime import date

from backend.plugin.rider_salary.service.period_service import (
    _same_scope_conflict,
    ranges_overlap,
    span_is_covered,
)


def test_ranges_overlap_ignores_adjacent_periods() -> None:
    """首尾相接不算相交。"""
    assert ranges_overlap(date(2026, 9, 1), date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 30)) is False
    assert ranges_overlap(date(2026, 9, 1), date(2026, 9, 30), date(2026, 9, 16), date(2026, 9, 30)) is True


def test_same_scope_conflict_ignores_other_riders_and_site_level() -> None:
    """不同骑手、站点级和骑手级之间日期相同也不冲突。"""
    site = (0, date(2026, 10, 1), date(2026, 10, 31))
    rider_a = (11, date(2026, 10, 1), date(2026, 10, 15))
    rider_b = (22, date(2026, 10, 1), date(2026, 10, 15))
    assert _same_scope_conflict(site, rider_a) is False
    assert _same_scope_conflict(rider_a, rider_b) is False
    assert _same_scope_conflict(rider_a, (11, date(2026, 10, 10), date(2026, 10, 20))) is True
    assert _same_scope_conflict(site, (0, date(2026, 10, 16), date(2026, 10, 31))) is True


def test_span_is_covered_requires_every_day() -> None:
    """两段半月结盖住整月；只盖下半月不行。骑手月结可以伸出站点半月结之外。"""
    month_start, month_end = date(2026, 10, 1), date(2026, 10, 31)
    halves = [
        (date(2026, 10, 1), date(2026, 10, 15)),
        (date(2026, 10, 16), date(2026, 10, 31)),
    ]
    assert span_is_covered(month_start, month_end, halves) is True
    assert span_is_covered(month_start, month_end, [halves[1]]) is False
    assert span_is_covered(date(2026, 10, 1), date(2026, 10, 15), [(month_start, month_end)]) is True
    assert span_is_covered(date(2026, 10, 16), date(2026, 10, 31), [(month_start, month_end)]) is True
