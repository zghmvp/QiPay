from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from backend.plugin.rider_salary.enums import BindingType, DayStatus
from backend.plugin.rider_salary.service.calendar_service import (
    clip_plan_bands,
    merge_day_with_live_plan,
    resolve_day_status,
    summarize_subjects,
)
from backend.plugin.rider_salary.service.rider_service import Segment, resolve_effective_plans_from_bindings
from backend.plugin.rider_salary.tests.test_master_data import _binding


def test_plan_bands_clip_month_and_split_on_switch() -> None:
    segments = [
        Segment(plan_version_id=12, start=date(2026, 8, 20), end=date(2026, 9, 14)),
        Segment(plan_version_id=15, start=date(2026, 9, 15), end=date(2026, 10, 5)),
        Segment(plan_version_id=None, start=date(2026, 10, 6), end=date(2026, 10, 10)),
    ]
    meta = {12: ('底薪A', '#1677ff'), 15: ('阶梯B', '#fa8c16')}
    bands = clip_plan_bands(segments, date(2026, 9, 1), date(2026, 9, 30), meta)
    assert [(b.plan_version_id, b.start, b.end, b.short_name) for b in bands] == [
        (12, date(2026, 9, 1), date(2026, 9, 14), '底薪A'),
        (15, date(2026, 9, 15), date(2026, 9, 30), '阶梯B'),
    ]


def test_plan_bands_disconnect_on_override_switch() -> None:
    bindings = [
        _binding(BindingType.default, date(2026, 9, 1), date(2026, 9, 30), 11, pk=1),
        _binding(BindingType.override, date(2026, 9, 15), date(2026, 9, 30), 22, pk=2),
    ]
    segments = resolve_effective_plans_from_bindings(bindings, date(2026, 9, 1), date(2026, 9, 30))
    bands = clip_plan_bands(segments, date(2026, 9, 1), date(2026, 9, 30), {11: ('A', '#1'), 22: ('B', '#2')})
    assert len(bands) == 2
    assert bands[0].end == date(2026, 9, 14)
    assert bands[1].start == date(2026, 9, 15)
    assert bands[0].plan_version_id != bands[1].plan_version_id


def test_day_status_four_states() -> None:
    assert (
        resolve_day_status(has_plan=False, order_count=5, valid_order_count=5, imported=True) == DayStatus.no_plan.value
    )
    assert (
        resolve_day_status(has_plan=True, order_count=3, valid_order_count=3, imported=True) == DayStatus.has_data.value
    )
    assert (
        resolve_day_status(has_plan=True, order_count=0, valid_order_count=0, imported=True)
        == DayStatus.no_orders.value
    )
    assert (
        resolve_day_status(has_plan=True, order_count=0, valid_order_count=0, imported=False)
        == DayStatus.not_imported.value
    )
    assert (
        resolve_day_status(has_plan=False, order_count=0, valid_order_count=0, imported=False)
        == DayStatus.not_imported.value
    )


def test_subjects_summary_truncate() -> None:
    assert summarize_subjects(['夜间补贴', '超时']) == ['夜间补贴', '超时']
    assert summarize_subjects(['夜间补贴', '超时', '全勤奖']) == ['夜间补贴', '超时', '全勤奖']
    assert summarize_subjects(['夜间补贴', '超时', '全勤奖', '好评奖']) == ['夜间补贴', '超时', '全勤奖', '等1项']
    assert summarize_subjects(['夜间补贴', '夜间补贴', '超时']) == ['夜间补贴', '超时']
    assert summarize_subjects(['a', 'b', 'c', 'd', 'e']) == ['a', 'b', 'c', '等2项']


def test_merge_day_cache_must_not_mask_binding_gap() -> None:
    """有 rs_payroll_daily(has_data+plan) 但 live 无绑 → 强制 no_plan，方案空。"""
    cache = SimpleNamespace(
        order_count=5,
        valid_order_count=5,
        net_adjust=Decimal('0.00'),
        day_status=DayStatus.has_data.value,
        plan_version_id=1,
        period_id=99,
    )
    order_count, valid_count, net_adjust, day_status, plan_vid, period_id = merge_day_with_live_plan(
        live_plan_vid=None,
        cache=cache,
        live_order_count=5,
        live_valid_count=5,
        live_net_adjust=Decimal('0.00'),
        imported=True,
    )
    assert order_count == 5
    assert valid_count == 5
    assert net_adjust == Decimal('0.00')
    assert day_status == DayStatus.no_plan.value
    assert plan_vid is None
    assert period_id == 99


def test_merge_day_live_plan_wins_over_cache_plan() -> None:
    """live 有方案时用 live plan_vid，状态按 live has_plan 重算（不用 cache.day_status）。"""
    cache = SimpleNamespace(
        order_count=3,
        valid_order_count=3,
        net_adjust=Decimal('10.00'),
        day_status=DayStatus.no_plan.value,
        plan_version_id=None,
        period_id=7,
    )
    _oc, _vc, _na, day_status, plan_vid, _pid = merge_day_with_live_plan(
        live_plan_vid=42,
        cache=cache,
        live_order_count=0,
        live_valid_count=0,
        live_net_adjust=Decimal('0.00'),
        imported=True,
    )
    assert plan_vid == 42
    assert day_status == DayStatus.has_data.value


def test_binding_gap_plan_bands_leave_hole() -> None:
    """09-01~14 + 09-18~30 → 色带断开，缺口不入带。"""
    bindings = [
        _binding(BindingType.default, date(2026, 9, 1), date(2026, 9, 14), 11, pk=1),
        _binding(BindingType.default, date(2026, 9, 18), date(2026, 9, 30), 22, pk=2),
    ]
    segments = resolve_effective_plans_from_bindings(bindings, date(2026, 9, 1), date(2026, 9, 30))
    bands = clip_plan_bands(segments, date(2026, 9, 1), date(2026, 9, 30), {11: ('A', '#1'), 22: ('B', '#2')})
    assert [(b.start, b.end) for b in bands] == [
        (date(2026, 9, 1), date(2026, 9, 14)),
        (date(2026, 9, 18), date(2026, 9, 30)),
    ]
    gap_days = {date(2026, 9, d) for d in (15, 16, 17)}
    for day in gap_days:
        assert any(seg.start <= day <= seg.end and seg.plan_version_id is None for seg in segments)
