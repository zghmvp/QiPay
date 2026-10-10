"""P5-04：日汇总按区间一次取出，查询次数不随天数增长。

用记录语句的假会话计数，不往共享库灌数据。
"""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Self
from unittest.mock import AsyncMock, patch

import anyio

from backend.plugin.rider_salary.model.payroll_daily import RiderSalaryPayrollDaily
from backend.plugin.rider_salary.service import calc_service, calendar_service
from backend.plugin.rider_salary.service.calc_service import CalcDaily, CalcResult, _persist_result

ZERO = Decimal('0.00')
_SHORT = 3
_LONG = 31


def _compact(sql: str) -> str:
    return ' '.join(sql.lower().split())


def _sql_of(stmt: object) -> str:
    compile_ = getattr(stmt, 'compile', None)
    if compile_ is None:
        return _compact(str(stmt))
    try:
        rendered = str(compile_(compile_kwargs={'literal_binds': True}))
    except Exception:
        rendered = str(compile_())
    return _compact(rendered)


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = list(rows)

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> Self:
        return self

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _Session:
    """记下语句。日汇总查询返回预先放好的行，其余查询为空。"""

    def __init__(self, dailies: list[Any] | None = None) -> None:
        self.dailies = list(dailies or [])
        self.statements: list[str] = []
        self.added: list[Any] = []

    def _record(self, stmt: object) -> str:
        sql = _sql_of(stmt)
        self.statements.append(sql)
        return sql

    def _rows(self, sql: str) -> list[Any]:
        if 'rs_payroll_daily' in sql:
            return list(self.dailies)
        return []

    async def scalar(self, stmt: object) -> int:
        self._record(stmt)
        return 0

    async def scalars(self, stmt: object) -> _Rows:
        return _Rows(self._rows(self._record(stmt)))

    async def execute(self, stmt: object, *_args: object, **_kwargs: object) -> _Rows:
        return _Rows(self._rows(self._record(stmt)))

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def add_all(self, objs: object) -> None:
        return None

    async def flush(self) -> None:
        return None


def _daily_sql(statements: list[str]) -> list[str]:
    return [sql for sql in statements if 'rs_payroll_daily' in sql]


def _daily(day: date, *, order_count: int) -> CalcDaily:
    return CalcDaily(
        rider_id=7,
        biz_date=day,
        plan_version_id=11,
        order_count=order_count,
        valid_order_count=order_count,
        formula_amount=ZERO,
        manual_bonus=ZERO,
        manual_penalty=ZERO,
        net_adjust=ZERO,
        day_status='has_data',
    )


def _result(dailies: list[CalcDaily]) -> CalcResult:
    return CalcResult(
        rider_id=7,
        period_id=3,
        payroll_id=None,
        order_count=0,
        valid_order_count=0,
        per_order_total=ZERO,
        daily_total=ZERO,
        period_total=ZERO,
        bonus_total=ZERO,
        penalty_total=ZERO,
        gross=ZERO,
        deduction_total=ZERO,
        advance_deduction=ZERO,
        advance_deductible=ZERO,
        net=ZERO,
        plan_version_ids=[],
        warnings=[],
        details=[],
        dailies=dailies,
    )


def test_persist_daily_queries_stay_flat() -> None:
    """落库 3 天和 31 天都只查一次日汇总区间；已有行更新，缺的行补插。"""

    async def _run() -> None:
        counts: list[int] = []
        payroll = SimpleNamespace(id=9, calc_version=0)
        period = SimpleNamespace(id=3, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
        rider = SimpleNamespace(id=7, job_no='J007', site_id=1)

        def _prepare(_db: object, *, rider: object, period: object) -> tuple[object, SimpleNamespace]:
            return period, payroll

        for size in (_SHORT, _LONG):
            start = date(2026, 1, 1)
            dailies = [_daily(start + timedelta(days=offset), order_count=offset + 1) for offset in range(size)]
            kept = SimpleNamespace(
                biz_date=start,
                period_id=None,
                plan_version_id=None,
                order_count=0,
                valid_order_count=0,
                formula_amount=ZERO,
                manual_bonus=ZERO,
                manual_penalty=ZERO,
                net_adjust=ZERO,
                day_status='not_imported',
            )
            session = _Session([kept])
            with (
                patch.object(calc_service, '_prepare_payroll_for_persist', AsyncMock(side_effect=_prepare)),
                patch.object(calc_service.payroll_detail_dao, 'logical_delete_by_payroll', AsyncMock()),
            ):
                await _persist_result(
                    session,  # type: ignore[arg-type]
                    rider=rider,  # type: ignore[arg-type]
                    period=period,  # type: ignore[arg-type]
                    result=_result(dailies),
                    operator=None,
                )
            matched = _daily_sql(session.statements)
            counts.append(len(matched))
            assert len(matched) == 1
            assert 'biz_date >=' in matched[0]
            assert 'biz_date <=' in matched[0]
            assert 'biz_date =' not in matched[0].replace('biz_date >=', '').replace('biz_date <=', '')
            assert kept.order_count == 1
            assert kept.period_id == 3
            dailies_added = [row for row in session.added if isinstance(row, RiderSalaryPayrollDaily)]
            assert len(dailies_added) == size - 1
        assert counts == [1, 1]
        assert counts[1] < _LONG

    anyio.run(_run)


def test_calendar_month_daily_query_stays_flat() -> None:
    """2 月 28 天和 1 月 31 天的月历都只查一次日汇总区间。"""

    async def _run() -> None:
        rider = SimpleNamespace(id=7, site_id=1, job_no='J007', name='骑手')
        counts: list[int] = []
        lengths: list[int] = []
        for month in ('2026-02', '2026-01'):
            session = _Session()
            with (
                patch.object(calendar_service.rider_dao, 'get', AsyncMock(return_value=rider)),
                patch.object(calendar_service, 'resolve_effective_plans', AsyncMock(return_value=[])),
            ):
                page = await calendar_service.calendar_service.build_month(session, rider.id, month)  # type: ignore[arg-type]
            matched = _daily_sql(session.statements)
            counts.append(len(matched))
            lengths.append(len(page.days))
            assert len(matched) == 1
            assert 'biz_date >=' in matched[0]
            assert 'biz_date <=' in matched[0]
        assert lengths == [28, 31]
        assert counts == [1, 1]

    anyio.run(_run)
