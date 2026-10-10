"""P6-03：周期列表按需重算草稿做服务端过滤，深链同时包含 open 与 reopened。"""

import inspect
import re

from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import anyio
import pytest

from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from backend.core.conf import settings
from backend.database.db import get_database_url
from backend.plugin.rider_salary.crud.settle_period import settle_period_dao
from backend.plugin.rider_salary.enums import CycleType, PayrollKind, PayrollStatus, PeriodStatus
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.service.dashboard_service import STALE_PERIODS_LINK, DashboardService

_SCHEMA_RE = re.compile(r'^rs_p603_[0-9a-f]{8}$')
_BASE_DAY = date(2024, 1, 1)
_PERIOD_COUNT = 30


def test_stale_periods_link_includes_open_and_reopened() -> None:
    """工作台深链不能只钉 status=open。"""
    parsed = urlsplit(STALE_PERIODS_LINK)
    query = parse_qs(parsed.query)
    statuses: list[str] = []
    for raw in query.get('status', []):
        statuses.extend(part.strip() for part in raw.split(',') if part.strip())
    assert parsed.path == '/rider-salary/period'
    assert statuses == ['open', 'reopened']
    assert query.get('stale') == ['1']
    assert 'STALE_PERIODS_LINK' in inspect.getsource(DashboardService._stale_periods)


def test_stale_select_uses_draft_exists() -> None:
    """stale=true 用 exists 限定草稿；不传则不加这段条件。"""

    async def _run() -> None:
        matched = await settle_period_dao.get_select(
            site_id=None,
            rider_id=None,
            status='open,reopened',
            month_start=None,
            month_end=None,
            site_ids=None,
            stale=True,
        )
        sql = str(matched.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True})).lower()
        assert 'exists' in sql
        assert "status = 'draft'" in sql
        assert 'stale' in sql
        assert "'open'" in sql and "'reopened'" in sql
        plain = await settle_period_dao.get_select(
            site_id=None,
            rider_id=None,
            status=None,
            month_start=None,
            month_end=None,
            site_ids=None,
            stale=None,
        )
        plain_sql = str(plain.compile(dialect=postgresql.dialect())).lower()
        assert 'exists' not in plain_sql

    anyio.run(_run)


@pytest.mark.integration
def test_thirty_periods_filter_to_three_stale_across_pages() -> None:
    """30 个可见周期里 3 个有需重算草稿，筛选后总数为 3，翻页不丢不重。"""
    anyio.run(_thirty_periods)


async def _page(
    db: AsyncSession,
    *,
    stale: bool | None,
    status: str | None,
    page: int,
    size: int,
) -> tuple[int, list[RiderSalarySettlePeriod]]:
    stmt = await settle_period_dao.get_select(
        site_id=None,
        rider_id=None,
        status=status,
        month_start=None,
        month_end=None,
        site_ids=None,
        stale=stale,
    )
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = list((await db.scalars(stmt.limit(size).offset((page - 1) * size))).all())
    return int(total or 0), rows


async def _thirty_periods() -> None:
    schema = f'rs_p603_{uuid4().hex[:8]}'
    if _SCHEMA_RE.fullmatch(schema) is None or schema == 'public':
        raise RuntimeError(f'临时 schema 名称不安全：{schema}')
    engine = create_async_engine(get_database_url(), pool_pre_ping=True).execution_options(
        schema_translate_map={None: schema},
    )
    try:
        async with engine.begin() as conn:
            current_db = await conn.scalar(text('select current_database()'))
            if current_db != settings.DATABASE_SCHEMA:
                raise RuntimeError(
                    f'拒绝在非配置库建临时 schema，当前库是 {current_db}，只允许 {settings.DATABASE_SCHEMA}'
                )
            await conn.execute(text(f'CREATE SCHEMA {schema}'))
            await conn.run_sync(_create_tables)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as db:
            async with db.begin():
                stale_ids, decoy_ids = await _seed(db)
            total, _rows = await _page(db, stale=None, status=None, page=1, size=50)
            assert total == _PERIOD_COUNT
            filtered, page1 = await _page(db, stale=True, status=None, page=1, size=2)
            _, page2 = await _page(db, stale=True, status=None, page=2, size=2)
            _, page3 = await _page(db, stale=True, status=None, page=3, size=2)
            assert filtered == 3
            assert [row.id for row in page1] == stale_ids[:2]
            assert [row.id for row in page2] == stale_ids[2:]
            assert page3 == []
            seen = [row.id for row in page1 + page2]
            assert seen == stale_ids
            assert not set(seen) & set(decoy_ids)
            fresh_total, _fresh = await _page(db, stale=False, status=None, page=1, size=50)
            assert fresh_total == _PERIOD_COUNT - 3
            open_only, _open_rows = await _page(db, stale=True, status='open', page=1, size=10)
            both, both_rows = await _page(db, stale=True, status='open,reopened', page=1, size=10)
            assert open_only == 2
            assert both == 3
            assert [row.id for row in both_rows] == stale_ids
            assert both_rows[1].status == PeriodStatus.reopened.value
    finally:
        await _drop_schema(engine, schema)
        await engine.dispose()


def _create_tables(sync_conn: Connection) -> None:
    RiderSalarySettlePeriod.__table__.create(sync_conn, checkfirst=False)
    RiderSalaryPayroll.__table__.create(sync_conn, checkfirst=False)


async def _drop_schema(engine: AsyncEngine, schema: str) -> None:
    if _SCHEMA_RE.fullmatch(schema) is None:
        return
    async with engine.begin() as conn:
        current_db = await conn.scalar(text('select current_database()'))
        if current_db != settings.DATABASE_SCHEMA:
            raise RuntimeError(f'拒绝清理临时 schema，当前库是 {current_db}，只允许 {settings.DATABASE_SCHEMA}')
        await conn.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))


async def _seed(db: AsyncSession) -> tuple[list[int], list[int]]:
    """30 个未删除周期，其中 3 个有需重算草稿；另有干扰数据和 1 个已删除周期。"""
    periods: list[RiderSalarySettlePeriod] = []
    for index in range(_PERIOD_COUNT):
        day = _BASE_DAY + timedelta(days=index)
        status = PeriodStatus.open.value
        if index == 15:
            status = PeriodStatus.reopened.value
        elif index == 1:
            status = PeriodStatus.locked.value
        period = RiderSalarySettlePeriod(
            site_id=91001,
            rider_id=0,
            cycle_type=CycleType.month.value,
            start_date=day,
            end_date=day,
            status=status,
        )
        db.add(period)
        periods.append(period)
    deleted = RiderSalarySettlePeriod(
        site_id=91001,
        rider_id=0,
        cycle_type=CycleType.month.value,
        start_date=_BASE_DAY + timedelta(days=40),
        end_date=_BASE_DAY + timedelta(days=40),
        status=PeriodStatus.open.value,
    )
    db.add(deleted)
    await db.flush()
    deleted.deleted = deleted.id

    def add_payroll(
        period: RiderSalarySettlePeriod,
        *,
        stale: bool,
        kind: str = PayrollKind.normal.value,
        status: str = PayrollStatus.draft.value,
        deleted_flag: int = 0,
    ) -> None:
        row = RiderSalaryPayroll(
            period_id=period.id,
            rider_id=1,
            kind=kind,
            status=status,
            stale=stale,
        )
        if deleted_flag:
            row.deleted = deleted_flag
        db.add(row)

    add_payroll(periods[29], stale=True)
    add_payroll(periods[2], stale=True)
    add_payroll(periods[15], stale=False)
    add_payroll(periods[15], stale=True, kind=PayrollKind.supplement.value)
    add_payroll(periods[8], stale=True, status=PayrollStatus.finalized.value)
    add_payroll(periods[4], stale=True, deleted_flag=4)
    add_payroll(periods[3], stale=False)
    add_payroll(deleted, stale=True)
    await db.flush()
    stale_ids = [periods[29].id, periods[15].id, periods[2].id]
    decoy_ids = [periods[8].id, periods[4].id, periods[3].id, deleted.id]
    return stale_ids, decoy_ids
