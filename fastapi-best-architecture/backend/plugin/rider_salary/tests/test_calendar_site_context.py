"""换站后按订单和周期快照选择每天的站点，不看骑手当前站点。"""

from datetime import date

from backend.plugin.rider_salary.service.calendar_service import assign_site_by_day, dominant_site


def test_dominant_site_prefers_count_then_smaller_id() -> None:
    assert dominant_site([2, 2, 1]) == 2
    assert dominant_site([2, 1]) == 1


def test_blank_days_stay_on_old_site_until_first_new_snapshot() -> None:
    """9/15 第一次出现乙站订单时，9/1–9/14 仍归甲站，含没有订单的空白日。"""
    mapping = assign_site_by_day(
        date(2026, 9, 1),
        date(2026, 9, 30),
        order_points=[
            (date(2026, 9, 1), 1),
            (date(2026, 9, 14), 1),
            (date(2026, 9, 15), 2),
        ],
        fallback_site_id=2,
    )
    assert [mapping[date(2026, 9, day)] for day in range(1, 15)] == [1] * 14
    assert [mapping[date(2026, 9, day)] for day in range(15, 31)] == [2] * 16


def test_orders_override_adjustments_on_the_same_day() -> None:
    mapping = assign_site_by_day(
        date(2026, 9, 1),
        date(2026, 9, 1),
        order_points=[(date(2026, 9, 1), 1)],
        adjustment_points=[(date(2026, 9, 1), 2)],
        fallback_site_id=2,
    )
    assert mapping[date(2026, 9, 1)] == 1


def test_adjustment_snapshot_fills_days_without_orders() -> None:
    mapping = assign_site_by_day(
        date(2026, 9, 1),
        date(2026, 9, 30),
        order_points=[(date(2026, 9, 20), 2)],
        adjustment_points=[(date(2026, 9, 10), 1)],
        fallback_site_id=2,
    )
    assert mapping[date(2026, 9, 1)] == 1
    assert mapping[date(2026, 9, 10)] == 1
    assert mapping[date(2026, 9, 19)] == 1
    assert mapping[date(2026, 9, 20)] == 2


def test_edge_before_month_fills_days_before_first_order() -> None:
    mapping = assign_site_by_day(
        date(2026, 9, 1),
        date(2026, 9, 30),
        order_points=[(date(2026, 9, 15), 2)],
        edges=[(date(2026, 8, 20), 1)],
        fallback_site_id=2,
    )
    assert mapping[date(2026, 9, 1)] == 1
    assert mapping[date(2026, 9, 14)] == 1
    assert mapping[date(2026, 9, 15)] == 2


def test_rider_level_period_used_when_no_order_snapshot() -> None:
    mapping = assign_site_by_day(
        date(2026, 9, 1),
        date(2026, 9, 30),
        order_points=[],
        ranges=[
            (date(2026, 9, 15), date(2026, 9, 30), 2),
            (date(2026, 9, 1), date(2026, 9, 14), 1),
        ],
        fallback_site_id=2,
    )
    assert mapping[date(2026, 9, 14)] == 1
    assert mapping[date(2026, 9, 15)] == 2


def test_no_snapshot_falls_back_to_current_site() -> None:
    mapping = assign_site_by_day(
        date(2026, 9, 1),
        date(2026, 9, 3),
        order_points=[],
        fallback_site_id=8,
    )
    assert list(mapping.values()) == [8, 8, 8]
