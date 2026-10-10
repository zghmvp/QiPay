"""P5-09：工资预估和月历只查结算周期，没有周期时在内存中合成，不写入 rs_settle_period。"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anyio

from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import object_session
from sqlalchemy.sql.dml import Delete, Insert, Update

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import PeriodStatus
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.service.calendar_service import calendar_service, resolve_period
from backend.plugin.rider_salary.service.me_service import me_service
from backend.utils.timezone import timezone


class _MemoryRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def delete(self, *keys: str) -> int:
        return 0


class _Result:
    def all(self) -> list[object]:
        return []

    def first(self) -> None:
        return None

    def scalars(self) -> '_Result':
        return self

    def scalar(self) -> None:
        return None


class _RecordingSession:
    """记下只读路径发出的语句和 add，用来确认没有插入结算周期。"""

    def __init__(self, *, scalar_result: object | None = None) -> None:
        self.scalar_result = scalar_result
        self.statements: list[object] = []
        self.added: list[object] = []

    async def scalar(self, stmt: object) -> object | None:
        self.statements.append(stmt)
        return self.scalar_result

    async def scalars(self, stmt: object) -> _Result:
        self.statements.append(stmt)
        return _Result()

    async def execute(self, stmt: object) -> _Result:
        self.statements.append(stmt)
        return _Result()

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def add_all(self, objs: list[object]) -> None:
        self.added.extend(objs)


def _sql(stmt: object) -> str:
    compiled = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    return ' '.join(compiled.split())


def _writes(db: _RecordingSession) -> list[object]:
    return [stmt for stmt in db.statements if isinstance(stmt, (Insert, Update, Delete))]


def _period_rows(db: _RecordingSession) -> list[object]:
    return [obj for obj in db.added if isinstance(obj, RiderSalarySettlePeriod)]


def _site() -> SimpleNamespace:
    return SimpleNamespace(id=3, settle_cycle='half_month', cycle_config=None)


def _forbid_create() -> AsyncMock:
    return AsyncMock(side_effect=AssertionError('只读路径不能创建结算周期'))


def test_estimate_without_period_synthesizes_and_does_not_insert() -> None:
    """没有结算周期时，预估使用内存周期，且不调用会写入的 get_or_create_period。"""
    db = _RecordingSession()
    rider = SimpleNamespace(id=41, site_id=3)
    calc = AsyncMock(
        return_value=SimpleNamespace(
            order_count=2,
            gross=Decimal('10.00'),
            deduction_total=Decimal('0.00'),
            advance_deductible=Decimal('0.00'),
            net=Decimal('10.00'),
        )
    )
    writer = _forbid_create()
    creator = _forbid_create()
    now = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.tz_info)

    async def _run() -> None:
        with (
            patch('backend.plugin.rider_salary.service.me_service.timezone.now', return_value=now),
            patch('backend.plugin.rider_salary.utils.recalc.redis_client', _MemoryRedis()),
            patch('backend.plugin.rider_salary.service.calendar_service.site_dao.get', AsyncMock(return_value=_site())),
            patch(
                'backend.plugin.rider_salary.service.calendar_service.rider_dao.get',
                AsyncMock(return_value=SimpleNamespace(settle_cycle_override=None, cycle_config_override=None)),
            ),
            patch('backend.plugin.rider_salary.service.me_service.calculate_rider_period', calc),
            patch('backend.plugin.rider_salary.service.period_service.period_service.get_or_create_period', writer),
            patch('backend.plugin.rider_salary.crud.settle_period.settle_period_dao.create', creator),
        ):
            data = await me_service.payroll_estimate(db=db, rider=rider)
        assert data.is_estimate is True
        assert data.period_range == '09-01~09-15'
        assert data.period_status == PeriodStatus.open.value
        assert data.net_estimate == Decimal('10.00')
        period = calc.await_args.kwargs['period']
        assert isinstance(period, RiderSalarySettlePeriod)
        assert period.id is None
        assert period.start_date == date(2026, 9, 1)
        assert period.end_date == date(2026, 9, 15)
        assert object_session(period) is None
        assert inspect(period).transient
        assert calc.await_args.kwargs['persist'] is False
        writer.assert_not_awaited()
        creator.assert_not_awaited()
        assert _writes(db) == []
        assert _period_rows(db) == []

    anyio.run(_run)


def test_resolve_period_returns_existing_row_without_insert() -> None:
    """已有覆盖该日的周期时直接返回该行，不再合成，也不写库。"""
    existing = SimpleNamespace(
        id=8,
        site_id=3,
        rider_id=41,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 15),
        status=PeriodStatus.locked.value,
    )
    db = _RecordingSession(scalar_result=existing)
    writer = _forbid_create()

    async def _run() -> None:
        with patch('backend.plugin.rider_salary.service.period_service.period_service.get_or_create_period', writer):
            period = await resolve_period(db, 3, 41, date(2026, 9, 4))
        assert period is existing
        writer.assert_not_awaited()
        assert _writes(db) == []
        assert db.added == []
        assert db.statements

    anyio.run(_run)


def test_rider_override_synthesizes_month_period_in_memory() -> None:
    """骑手覆盖为月结时，内存周期按自然月合成，仍然不落库。"""
    db = _RecordingSession()
    writer = _forbid_create()

    async def _run() -> None:
        with (
            patch('backend.plugin.rider_salary.service.calendar_service.site_dao.get', AsyncMock(return_value=_site())),
            patch(
                'backend.plugin.rider_salary.service.calendar_service.rider_dao.get',
                AsyncMock(
                    return_value=SimpleNamespace(
                        settle_cycle_override='month',
                        cycle_config_override=None,
                    )
                ),
            ),
            patch('backend.plugin.rider_salary.service.period_service.period_service.get_or_create_period', writer),
        ):
            period = await resolve_period(db, 3, 41, date(2026, 9, 20))
        assert period.id is None
        assert period.cycle_type == 'month'
        assert period.rider_id == 41
        assert period.start_date == date(2026, 9, 1)
        assert period.end_date == date(2026, 9, 30)
        assert object_session(period) is None
        writer.assert_not_awaited()
        assert _writes(db) == []
        assert _period_rows(db) == []

    anyio.run(_run)


def test_missing_site_does_not_insert_period() -> None:
    db = _RecordingSession()

    async def _run() -> None:
        with patch(
            'backend.plugin.rider_salary.service.calendar_service.site_dao.get',
            AsyncMock(return_value=None),
        ):
            try:
                await resolve_period(db, 3, None, date(2026, 9, 4))
            except errors.NotFoundError as exc:
                assert exc.msg == '站点不存在'
            else:
                raise AssertionError('站点不存在时应拒绝合成')
        assert _writes(db) == []
        assert db.added == []

    anyio.run(_run)


def test_calendar_month_and_day_do_not_insert_period() -> None:
    """月历和日详情只查询。没有周期时日格不带周期，也不创建行。"""
    db = _RecordingSession()
    rider = SimpleNamespace(id=7, site_id=3)
    writer = _forbid_create()
    creator = _forbid_create()

    async def _run() -> None:
        with (
            patch('backend.plugin.rider_salary.utils.recalc.redis_client', _MemoryRedis()),
            patch(
                'backend.plugin.rider_salary.service.calendar_service.rider_dao.get',
                AsyncMock(return_value=rider),
            ),
            patch(
                'backend.plugin.rider_salary.service.calendar_service.resolve_effective_plans',
                AsyncMock(return_value=[]),
            ),
            patch(
                'backend.plugin.rider_salary.service.calendar_service.day_flag_dao.get_by_site_date',
                AsyncMock(return_value=None),
            ),
            patch('backend.plugin.rider_salary.service.period_service.period_service.get_or_create_period', writer),
            patch('backend.plugin.rider_salary.crud.settle_period.settle_period_dao.create', creator),
        ):
            month = await calendar_service.build_month(db, rider.id, '2026-09', for_rider=True)
            day = await calendar_service.build_day(db, rider.id, date(2026, 9, 10), for_rider=True)
        assert month.month == '2026-09'
        assert all(item.period_id is None and item.period_status is None for item in month.days)
        assert month.summary.periods == []
        assert day.period is None
        writer.assert_not_awaited()
        creator.assert_not_awaited()
        assert _writes(db) == []
        assert _period_rows(db) == []
        period_sql = [_sql(stmt).lower() for stmt in db.statements if 'rs_settle_period' in _sql(stmt).lower()]
        assert period_sql
        assert all(sql.startswith('select') for sql in period_sql)

    anyio.run(_run)
