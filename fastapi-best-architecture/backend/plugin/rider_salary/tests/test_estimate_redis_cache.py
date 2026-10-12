"""P5-02：同一骑手第二次预估命中 Redis；mark_stale 后重算。覆盖日按站点与月份缓存。"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anyio

from sqlalchemy.dialects import postgresql

from backend.plugin.rider_salary.service.calendar_service import _import_coverage_by_sites
from backend.plugin.rider_salary.service.me_service import me_service
from backend.plugin.rider_salary.utils.recalc import coverage_cache_key, estimate_cache_key, mark_stale


class _MemoryRedis:
    """进程内 Redis，只覆盖本用例用到的命令。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                removed += 1
        return removed

    async def delete_by_prefix(self, key_prefix: str) -> None:
        doomed = [key for key in self.store if key == key_prefix or key.startswith(f'{key_prefix}:')]
        for key in doomed:
            del self.store[key]


class _Rows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


def _period() -> SimpleNamespace:
    return SimpleNamespace(
        id=5,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 15),
        status='open',
    )


def _calc_result() -> SimpleNamespace:
    return SimpleNamespace(
        order_count=4,
        gross=Decimal('20.00'),
        deduction_total=Decimal('0.00'),
        advance_deductible=Decimal('0.00'),
        net=Decimal('20.00'),
    )


def _sql(stmt: object) -> str:
    compiled = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    return ' '.join(compiled.split())


def _select_clause(sql: str) -> str:
    return sql.split(' FROM ', maxsplit=1)[0]


def _selected_names(stmt: object) -> list[str]:
    return [column.name for column in stmt.selected_columns]


def test_second_estimate_hits_redis_until_mark_stale() -> None:
    """第一次整期预估写入 Redis；第二次不再重算；mark_stale 后下一次重新计算。"""
    redis = _MemoryRedis()
    rider = SimpleNamespace(id=41, site_id=3)
    calc = AsyncMock(return_value=_calc_result())
    payroll_rows = _Rows([])
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=payroll_rows)
    executed = MagicMock()
    executed.rowcount = 0
    db.execute = AsyncMock(return_value=executed)

    async def _run() -> None:
        with (
            patch('backend.plugin.rider_salary.utils.recalc.redis_client', redis),
            patch('backend.plugin.rider_salary.service.me_service.resolve_period', AsyncMock(return_value=_period())),
            patch('backend.plugin.rider_salary.service.me_service.calculate_rider_period', calc),
        ):
            first = await me_service.payroll_estimate(db=db, rider=rider)
            second = await me_service.payroll_estimate(db=db, rider=rider)
            assert calc.await_count == 1
            assert estimate_cache_key(rider.id) in redis.store
            assert second.net_estimate == first.net_estimate
            assert second.is_estimate is True
            assert second.updated_at == first.updated_at

            await mark_stale(db, rider_ids=[rider.id], date_from=date(2026, 9, 4), date_to=date(2026, 9, 4))
            assert estimate_cache_key(rider.id) not in redis.store

            third = await me_service.payroll_estimate(db=db, rider=rider)
            assert calc.await_count == 2
            assert third.net_estimate == Decimal('20.00')
            assert third.is_estimate is True

    anyio.run(_run)


def test_stored_payroll_skips_estimate_cache() -> None:
    """已有未过期薪资单时直接用库里的数，不读预估缓存，也不重算。"""
    redis = _MemoryRedis()
    rider = SimpleNamespace(id=42, site_id=3)
    redis.store[estimate_cache_key(rider.id)] = (
        '{"period_range":"09-01~09-15","period_status":"open","order_count":1,"gross":"1.00","deduction_total":"0.00","advance_deduction_estimate":"0.00","net_estimate":"1.00","is_estimate":true,"updated_at":"2026-09-01T00:00:00Z"}'
    )
    stored = SimpleNamespace(
        id=9,
        status='draft',
        stale=False,
        kind='normal',
        order_count=8,
        gross=Decimal('80.00'),
        deduction_total=Decimal('0.00'),
        advance_deduction=Decimal('0.00'),
        net=Decimal('80.00'),
        calc_time=None,
        updated_time=None,
    )
    payroll_rows = _Rows([stored])
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=payroll_rows)
    calc = AsyncMock()

    async def _run() -> None:
        with (
            patch('backend.plugin.rider_salary.utils.recalc.redis_client', redis),
            patch('backend.plugin.rider_salary.service.me_service.resolve_period', AsyncMock(return_value=_period())),
            patch('backend.plugin.rider_salary.service.me_service.calculate_rider_period', calc),
        ):
            data = await me_service.payroll_estimate(db=db, rider=rider)
        assert data.is_estimate is False
        assert data.net_estimate == Decimal('80.00')
        calc.assert_not_awaited()

    anyio.run(_run)


def test_import_coverage_distinct_biz_date_cached_by_site_month() -> None:
    """订单覆盖日是 select distinct biz_date，并按站点加自然月缓存；mark_stale 后重查。"""
    redis = _MemoryRedis()
    statements: list[object] = []
    batch = SimpleNamespace(site_id=3, date_from=date(2026, 8, 20), date_to=date(2026, 9, 5))

    def _scalars(stmt: object) -> _Rows:
        statements.append(stmt)
        names = _selected_names(stmt)
        if names == ['biz_date']:
            return _Rows([date(2026, 9, 2), date(2026, 9, 2), date(2026, 9, 16)])
        return _Rows([batch])

    db = AsyncMock()
    db.scalars = AsyncMock(side_effect=_scalars)
    executed = MagicMock()
    executed.rowcount = 1
    db.execute = AsyncMock(return_value=executed)

    async def _run() -> None:
        with patch('backend.plugin.rider_salary.utils.recalc.redis_client', redis):
            first = await _import_coverage_by_sites(db, {3}, date(2026, 9, 5), date(2026, 9, 5))
            queried = len(statements)
            assert queried == 2
            day = first[3]
            assert date(2026, 9, 5) in day[0]
            assert date(2026, 8, 20) not in day[0]
            assert day[1] == set()

            again = await _import_coverage_by_sites(db, {3}, date(2026, 9, 1), date(2026, 9, 30))
            assert len(statements) == queried
            assert again[3][0] == {date(2026, 9, day) for day in range(1, 6)}
            assert again[3][1] == {date(2026, 9, 2), date(2026, 9, 16)}
            assert coverage_cache_key(3, date(2026, 9, 1)) in redis.store

            other_site = await _import_coverage_by_sites(db, {8}, date(2026, 9, 1), date(2026, 9, 30))
            assert len(statements) == queried + 2
            assert other_site[8][1] == {date(2026, 9, 2), date(2026, 9, 16)}

            await mark_stale(db, rider_ids=[41], date_from=date(2026, 9, 2), date_to=date(2026, 9, 2))
            assert coverage_cache_key(3, date(2026, 9, 1)) not in redis.store
            assert estimate_cache_key(41) not in redis.store

            await _import_coverage_by_sites(db, {3}, date(2026, 9, 1), date(2026, 9, 30))
            assert len(statements) == queried + 4

    anyio.run(_run)

    order_sql = [_sql(stmt) for stmt in statements if _selected_names(stmt) == ['biz_date']]
    batch_sql = [_sql(stmt) for stmt in statements if _selected_names(stmt) != ['biz_date']]
    assert order_sql
    assert all('DISTINCT' in sql.upper() for sql in order_sql)
    assert all('biz_date' in _select_clause(sql) for sql in order_sql)
    assert all('site_id' not in _select_clause(sql) for sql in order_sql)
    assert any('2026-09-01' in sql and '2026-09-30' in sql for sql in order_sql)
    assert batch_sql
    assert all('date_from' in sql and 'date_to' in sql for sql in batch_sql)
    assert any('2026-09-01' in sql and '2026-09-30' in sql for sql in batch_sql)
