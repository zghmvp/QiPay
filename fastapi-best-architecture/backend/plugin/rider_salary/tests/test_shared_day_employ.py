"""日状态和用工类型各只保留一份算法，反冲后的日汇总标成待补算。"""

import inspect

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch

import anyio

from backend.plugin.rider_salary.crud.payroll_daily import PENDING_RECALC_DAILY_VALUES
from backend.plugin.rider_salary.engine.segments import employ_type_on
from backend.plugin.rider_salary.enums import DayStatus, PeriodStatus
from backend.plugin.rider_salary.service import adjustment_service, calc_service, calendar_service
from backend.plugin.rider_salary.service.dashboard_service import DashboardService
from backend.plugin.rider_salary.service.payroll_service import payroll_service
from backend.plugin.rider_salary.service.period_service import period_service
from backend.plugin.rider_salary.utils.day_status import day_status_for


def _history(start: date, end: date | None, employ_type: str) -> SimpleNamespace:
    return SimpleNamespace(start_date=start, end_date=end, employ_type=employ_type)


def test_overlapping_employ_history_uses_latest_start() -> None:
    """多段重叠时，算薪切段和奖惩适用范围都取开始日最晚的一段。"""
    history = [
        _history(date(2026, 9, 1), date(2026, 9, 30), 'part_time'),
        _history(date(2026, 9, 10), date(2026, 9, 20), 'full_time'),
    ]
    assert employ_type_on(history, 'part_time', date(2026, 9, 15)) == 'full_time'
    assert employ_type_on(history, 'part_time', date(2026, 9, 21)) == 'part_time'
    source = inspect.getsource(adjustment_service)
    assert 'def _employ_type_on' not in source
    assert 'employ_type_on(' in source
    assert 'employ_type_on(' in inspect.getsource(calc_service)


def test_day_status_ignores_completed_orders_outside_employment() -> None:
    """无方案且在职有完成单才标无方案；离职日之后的完成单标成有数据。"""
    assert (
        day_status_for(
            plan_version_id=None,
            order_count=2,
            completed_order_count=2,
            employed=True,
            imported=True,
        )
        == DayStatus.no_plan.value
    )
    assert (
        day_status_for(
            plan_version_id=None,
            order_count=2,
            completed_order_count=2,
            employed=False,
            imported=True,
        )
        == DayStatus.has_data.value
    )
    calc_source = inspect.getsource(calc_service)
    calendar_source = inspect.getsource(calendar_service)
    assert 'day_status_for(' in calc_source
    assert 'day_status_for(' in calendar_source
    assert 'def resolve_day_status' not in calc_source
    assert 'def resolve_day_status' not in calendar_source


def test_pending_recalc_clears_cached_amounts() -> None:
    assert PENDING_RECALC_DAILY_VALUES['day_status'] == DayStatus.pending_recalc.value
    assert PENDING_RECALC_DAILY_VALUES['formula_amount'] == Decimal('0.00')
    assert PENDING_RECALC_DAILY_VALUES['manual_bonus'] == Decimal('0.00')
    assert PENDING_RECALC_DAILY_VALUES['manual_penalty'] == Decimal('0.00')
    assert PENDING_RECALC_DAILY_VALUES['net_adjust'] == Decimal('0.00')
    assert 'pending_recalc' in inspect.getsource(DashboardService._trend)


def test_reverse_marks_daily_cache_pending() -> None:
    period = SimpleNamespace(
        id=9,
        site_id=1,
        rider_id=0,
        cycle_type='month',
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        status=PeriodStatus.locked.value,
        remark=None,
        locked_by=1,
        locked_time=None,
        paid_by=None,
        paid_time=None,
        reopened_by=None,
        reopened_time=None,
    )
    payroll = SimpleNamespace(id=3, kind='normal', reversed=False, status='finalized')
    mark = AsyncMock()
    site = SimpleNamespace(id=1, name='测试站', code='S1')
    request = SimpleNamespace(user=SimpleNamespace(id=1, username='admin', nickname='管理员'))

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, site, None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.payroll_dao.select_models',
                AsyncMock(return_value=[payroll]),
            ),
            patch.object(
                payroll_service,
                'create_reversal',
                AsyncMock(return_value=SimpleNamespace(net=Decimal('-10.00'))),
            ),
            patch.object(period_service, 'set_locked_flags', AsyncMock()),
            patch(
                'backend.plugin.rider_salary.service.period_service.payroll_daily_dao.mark_period_pending_recalc',
                mark,
            ),
            patch('backend.plugin.rider_salary.service.period_service.audit_service.record', AsyncMock()),
        ):
            result = await period_service.reverse(db=AsyncMock(), request=request, pk=9, reason='纠错')
        mark.assert_awaited_once_with(ANY, 9)
        assert result.reversal_count == 1
        assert period.status == PeriodStatus.reopened.value

    anyio.run(_case)
