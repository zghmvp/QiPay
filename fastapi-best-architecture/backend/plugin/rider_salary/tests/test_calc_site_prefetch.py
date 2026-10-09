"""P5-03：周期算薪整期预取站点覆盖日，明细一次批量写入。"""

import asyncio
import re

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import anyio
import pytest

from backend.plugin.rider_salary.engine.segments import Segment
from backend.plugin.rider_salary.enums import DayStatus
from backend.plugin.rider_salary.model.payroll_detail import RiderSalaryPayrollDetail
from backend.plugin.rider_salary.service import calc_service
from backend.plugin.rider_salary.service.calc_service import (
    CalcDetail,
    CalcResult,
    _batch_overlap_dates,
    _calc_held_riders,
    _load_calc_input,
    _load_site_period_coverage,
    _persist_result,
)

START = date(2026, 9, 1)
END = date(2026, 9, 3)
SITE_ID = 3
RIDER_COUNT = 100
ZERO = Decimal('0.00')


def _compact(sql: str) -> str:
    return ' '.join(sql.lower().split())


def _sql_of(stmt: object) -> str:
    compile_ = getattr(stmt, 'compile', None)
    if compile_ is None:
        return str(stmt)
    try:
        return str(compile_(compile_kwargs={'literal_binds': True}))
    except Exception:
        return str(compile_())


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _CoverageSession:
    """记录语句，并按表返回覆盖日夹具。不算真库。"""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def _record(self, stmt: object) -> str:
        sql = _sql_of(stmt)
        self.statements.append(sql)
        return _compact(sql)

    async def scalars(self, stmt: object) -> _Rows:
        sql = self._record(stmt)
        if 'rs_import_batch' in sql:
            return _Rows([
                SimpleNamespace(date_from=START, date_to=START, site_id=SITE_ID),
                SimpleNamespace(date_from=None, date_to=END, site_id=SITE_ID),
                SimpleNamespace(date_from=date(2026, 10, 1), date_to=date(2026, 10, 2), site_id=SITE_ID),
            ])
        if 'rs_order' in sql and 'rider_id' not in sql:
            return _Rows([date(2026, 9, 2), None])
        return _Rows([])

    async def scalar(self, stmt: object) -> Any:
        sql = self._record(stmt)
        matched = re.search(r'rs_rider\.id = (\d+)', sql)
        if matched is None or 'employ_history' in sql:
            return None
        return _rider(int(matched.group(1)))

    async def execute(self, stmt: object, *_args: object, **_kwargs: object) -> _Rows:
        self._record(stmt)
        return _Rows([])

    def batch_sql(self) -> list[str]:
        return [item for item in self.statements if 'rs_import_batch' in item.lower()]

    def site_date_sql(self) -> list[str]:
        return [item for item in self.statements if 'rs_order' in item.lower() and 'rider_id' not in item.lower()]


class _Lock:
    async def owned(self) -> bool:
        return False

    async def release(self) -> None:
        return None


def _rider(rider_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=rider_id,
        site_id=SITE_ID,
        deleted=0,
        hire_date=None,
        leave_date=None,
        employ_type='full_time',
        job_no=f'J{rider_id}',
        name=f'骑手{rider_id}',
    )


def _period() -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        site_id=SITE_ID,
        start_date=START,
        end_date=END,
        status='open',
        rider_id=0,
    )


def _held(period_id: int) -> calc_service._HeldCalcLock:
    return calc_service._HeldCalcLock(
        lock=_Lock(),
        stop=asyncio.Event(),
        loop=asyncio.get_running_loop(),
        period_id=period_id,
    )


def _detail(index: int) -> CalcDetail:
    return CalcDetail(
        rider_id=1,
        subject_id=2,
        amount=Decimal(index),
        stage='per_order',
        include_in_gross=True,
        source='formula',
        biz_date=START,
        plan_version_id=1,
        plan_item_id=index,
        order_id=index,
        calc_trace={'序号': index},
    )


def _result(details: list[CalcDetail]) -> CalcResult:
    return CalcResult(
        rider_id=1,
        period_id=42,
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
        details=details,
        dailies=[],
    )


class _PersistDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.batches: list[list[object]] = []
        self.flushed = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def add_all(self, objs: object) -> None:
        self.batches.append(list(objs))  # type: ignore[arg-type]

    async def flush(self) -> None:
        self.flushed += 1

    async def scalar(self, _stmt: object) -> None:
        return None


def _statuses(result: CalcResult) -> dict[date, str]:
    return {row.biz_date: row.day_status for row in result.dailies}


def test_batch_overlap_dates_skip_null_and_clip() -> None:
    """空日期、不相交、起止颠倒都不产生覆盖日；相交部分裁进周期。"""
    assert _batch_overlap_dates(None, END, START, END) == set()
    assert _batch_overlap_dates(START, None, START, END) == set()
    assert _batch_overlap_dates(None, None, START, END) == set()
    assert _batch_overlap_dates(date(2026, 8, 1), date(2026, 8, 31), START, END) == set()
    assert _batch_overlap_dates(date(2026, 9, 4), date(2026, 9, 10), START, END) == set()
    assert _batch_overlap_dates(END, START, START, END) == set()
    assert _batch_overlap_dates(date(2026, 8, 20), date(2026, 9, 2), START, END) == {
        date(2026, 9, 1),
        date(2026, 9, 2),
    }
    assert _batch_overlap_dates(END, date(2026, 9, 10), START, END) == {END}


def test_site_coverage_query_filters_range_and_nulls() -> None:
    """批次语句带区间和空值条件；空值和不相交批次不进入覆盖日。"""

    async def _run() -> None:
        db = _CoverageSession()
        coverage = await _load_site_period_coverage(db, site_id=SITE_ID, start=START, end=END)  # type: ignore[arg-type]
        assert coverage.covered_dates == {START}
        assert coverage.site_order_dates == {date(2026, 9, 2)}
        assert len(db.batch_sql()) == 1
        assert len(db.site_date_sql()) == 1
        batch = _compact(db.batch_sql()[0])
        assert 'date_from is not null' in batch
        assert 'date_to is not null' in batch
        assert 'date_from <=' in batch
        assert 'date_to >=' in batch
        assert '2026-09-01' in batch
        assert '2026-09-03' in batch
        site_dates = _compact(db.site_date_sql()[0])
        assert site_dates.startswith('select distinct')
        assert 'rs_order' in site_dates
        assert 'biz_date >=' in site_dates
        assert 'biz_date <=' in site_dates
        assert 'rider_id' not in site_dates

    anyio.run(_run)


def _segment(_db: object, _rider_id: int, start: date, end: date, **_kwargs: object) -> list[Segment]:
    return [Segment(plan_version_id=1, start_date=start, end_date=end)]


def _keep_result(_db: object, **kwargs: object) -> object:
    return kwargs['result']


def _prepare_payroll(version: int) -> Callable[..., tuple[object, SimpleNamespace]]:
    def _prepare(_db: object, **kwargs: object) -> tuple[object, SimpleNamespace]:
        return kwargs['period'], SimpleNamespace(id=9, calc_version=version)

    return _prepare


def _delete_payroll(_db: object, payroll_id: int) -> None:
    assert payroll_id == 9


def test_single_rider_load_uses_ranged_coverage_once() -> None:
    """单骑手试算路径也会走带区间的覆盖查询，且只查一次。"""

    async def _run() -> None:
        db = _CoverageSession()
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(calc_service, 'resolve_segments', AsyncMock(side_effect=_segment))
            data = await _load_calc_input(
                db,  # type: ignore[arg-type]
                rider=_rider(7),  # type: ignore[arg-type]
                period=_period(),  # type: ignore[arg-type]
                forced_plan_version=None,
                persist_advance=False,
            )
        assert len(db.batch_sql()) == 1
        assert len(db.site_date_sql()) == 1
        assert 'date_from is not null' in _compact(db.batch_sql()[0])
        assert data.covered_dates == {START}
        assert data.site_order_dates == {date(2026, 9, 2)}
        assert data.persist_advance is False

    anyio.run(_run)


def test_hundred_rider_period_prefetches_site_queries_once() -> None:
    """100 人周期算薪只查一次导入批次和一次站点订单日，查询数比按人查低一个数量级。"""

    async def _run() -> None:
        db = _CoverageSession()
        period = _period()
        rider_ids = list(range(1, RIDER_COUNT + 1))
        held = [_held(period.id) for _ in rider_ids]
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(calc_service, 'resolve_segments', AsyncMock(side_effect=_segment))
            patcher.setattr(calc_service, '_refresh_period_calculating', AsyncMock())
            patcher.setattr(calc_service, '_persist_result', AsyncMock(side_effect=_keep_result))
            results, skipped = await _calc_held_riders(
                db,  # type: ignore[arg-type]
                period=period,  # type: ignore[arg-type]
                rider_ids=rider_ids,
                held=held,
                operator=None,
            )
        site_queries = len(db.batch_sql()) + len(db.site_date_sql())
        assert skipped == []
        assert len(results) == RIDER_COUNT
        assert len(db.batch_sql()) == 1
        assert len(db.site_date_sql()) == 1
        assert site_queries * 10 <= RIDER_COUNT
        expected = {
            START: DayStatus.no_orders.value,
            date(2026, 9, 2): DayStatus.no_orders.value,
            END: DayStatus.not_imported.value,
        }
        assert _statuses(results[0]) == expected
        assert _statuses(results[-1]) == expected

    anyio.run(_run)


def test_empty_rider_list_skips_site_coverage_query() -> None:
    """没有骑手时不预取站点覆盖。"""

    async def _run() -> None:
        db = _CoverageSession()
        results, skipped = await _calc_held_riders(
            db,  # type: ignore[arg-type]
            period=_period(),  # type: ignore[arg-type]
            rider_ids=[],
            held=[],
            operator=None,
        )
        assert results == []
        assert skipped == []
        assert db.batch_sql() == []
        assert db.site_date_sql() == []

    anyio.run(_run)


def test_persist_inserts_details_in_one_batch() -> None:
    """多条明细一次 add_all，不再逐条 add。"""

    async def _run() -> None:
        db = _PersistDb()
        details = [_detail(index) for index in range(1, 5)]
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(calc_service, '_prepare_payroll_for_persist', AsyncMock(side_effect=_prepare_payroll(0)))
            patcher.setattr(
                calc_service.payroll_detail_dao, 'logical_delete_by_payroll', AsyncMock(side_effect=_delete_payroll)
            )
            result = await _persist_result(
                db,  # type: ignore[arg-type]
                rider=_rider(1),  # type: ignore[arg-type]
                period=_period(),  # type: ignore[arg-type]
                result=_result(details),
                operator=None,
            )
        assert not any(isinstance(row, RiderSalaryPayrollDetail) for row in db.added)
        assert len(db.batches) == 1
        assert len(db.batches[0]) == 4
        assert all(isinstance(row, RiderSalaryPayrollDetail) for row in db.batches[0])
        assert {row.payroll_id for row in db.batches[0]} == {9}  # type: ignore[attr-defined]
        assert [row.order_id for row in db.batches[0]] == [1, 2, 3, 4]  # type: ignore[attr-defined]
        assert db.flushed == 1
        assert result.payroll_id == 9
        assert result.calc_version == 1

    anyio.run(_run)


def test_persist_skips_detail_insert_when_empty() -> None:
    """没有明细时不发空的批量插入。"""

    async def _run() -> None:
        db = _PersistDb()
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(calc_service, '_prepare_payroll_for_persist', AsyncMock(side_effect=_prepare_payroll(2)))
            patcher.setattr(
                calc_service.payroll_detail_dao, 'logical_delete_by_payroll', AsyncMock(side_effect=_delete_payroll)
            )
            await _persist_result(
                db,  # type: ignore[arg-type]
                rider=_rider(1),  # type: ignore[arg-type]
                period=_period(),  # type: ignore[arg-type]
                result=_result([]),
                operator=None,
            )
        assert db.batches == []
        assert not any(isinstance(row, RiderSalaryPayrollDetail) for row in db.added)
        assert db.flushed == 1

    anyio.run(_run)
