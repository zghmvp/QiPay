"""
真实 PostgreSQL 集成测试夹具

使用独立测试库 rs_fin_test（同一 PG 实例，不碰业务库），只建 rs_ 插件表；每个用例前清空。
PG 或 Redis 不可用时跳过。
"""

from collections.abc import Awaitable, Callable
from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import anyio
import pytest

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import backend.plugin.rider_salary.model  # ruff: ignore[unused-import]  注册插件模型

from backend.common.model import MappedBase
from backend.core.conf import settings
from backend.database.redis import redis_client
from backend.plugin.rider_salary.enums import (
    BindingType,
    CalcStage,
    OrderStatus,
    PlanVersionStatus,
    SubjectDirection,
)
from backend.plugin.rider_salary.model.advance import RiderSalaryAdvance
from backend.plugin.rider_salary.model.order import RiderSalaryOrder
from backend.plugin.rider_salary.model.plan import RiderSalaryPlan
from backend.plugin.rider_salary.model.plan_item import RiderSalaryPlanItem
from backend.plugin.rider_salary.model.plan_version import RiderSalaryPlanVersion
from backend.plugin.rider_salary.model.rider import RiderSalaryRider
from backend.plugin.rider_salary.model.rider_plan_binding import RiderSalaryRiderPlanBinding
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod
from backend.plugin.rider_salary.model.site import RiderSalarySite
from backend.plugin.rider_salary.model.subject import RiderSalarySubject
from backend.utils.timezone import timezone

TEST_DB = 'rs_fin_test'
_ready = False


def _url(database: str) -> str:
    return (
        f'postgresql+asyncpg://{settings.DATABASE_USER}:{settings.DATABASE_PASSWORD}'
        f'@{settings.DATABASE_HOST}:{settings.DATABASE_PORT}/{database}'
    )


def _plugin_tables() -> list[Any]:
    return [table for table in MappedBase.metadata.sorted_tables if table.name.startswith('rs_')]


async def _prepare() -> None:
    global _ready
    if _ready:
        return
    admin = create_async_engine(_url('postgres'), isolation_level='AUTOCOMMIT')
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(text('SELECT 1 FROM pg_database WHERE datname = :n'), {'n': TEST_DB})
            if not exists:
                await conn.execute(text(f'CREATE DATABASE {TEST_DB}'))
    finally:
        await admin.dispose()
    engine = create_async_engine(_url(TEST_DB))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: MappedBase.metadata.drop_all(sync, tables=_plugin_tables()))
            await conn.run_sync(lambda sync: MappedBase.metadata.create_all(sync, tables=_plugin_tables()))
    finally:
        await engine.dispose()
    _ready = True


def run_db(test: Callable[[AsyncSession], Awaitable[None]]) -> None:
    """在干净的测试库中执行用例（整个用例一个会话，结束回滚并清表）"""

    async def _run() -> None:
        try:
            await _prepare()
        except Exception as exc:
            pytest.skip(f'集成测试数据库不可用：{exc}')
        # 每个用例是新的事件循环，Redis 连接池需重建；清掉上个用例异常遗留的算薪锁
        redis_client.connection_pool.reset()
        async for key in redis_client.scan_iter(match='rs:calc:*'):
            await redis_client.delete(key)
        engine = create_async_engine(_url(TEST_DB))
        try:
            async with engine.begin() as conn:
                names = ', '.join(table.name for table in _plugin_tables())
                await conn.execute(text(f'TRUNCATE {names} RESTART IDENTITY'))
            maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            async with maker() as db:
                await test(db)
        finally:
            await engine.dispose()

    anyio.run(_run)


def admin_request() -> Any:
    """超管请求替身"""
    user = SimpleNamespace(id=1, username='admin', nickname='admin', is_superuser=True, roles=[])
    return SimpleNamespace(user=user, state=SimpleNamespace(ip='127.0.0.1'), client=None, headers={})


class Seed:
    """测试数据工厂"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._seq = 0

    def _next(self) -> int:
        self._seq += 1
        return self._seq

    async def add(self, obj: Any) -> Any:
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def site(self, **kw: Any) -> RiderSalarySite:
        n = self._next()
        return await self.add(RiderSalarySite(code=f'S{n}', name=f'站点{n}', **kw))

    async def rider(self, site: RiderSalarySite, **kw: Any) -> RiderSalaryRider:
        n = self._next()
        kw.setdefault('hire_date', date(2026, 1, 1))
        return await self.add(RiderSalaryRider(job_no=f'R{n}', name=f'骑手{n}', site_id=site.id, **kw))

    async def subject(self, direction: str = SubjectDirection.bonus.value, **kw: Any) -> RiderSalarySubject:
        n = self._next()
        return await self.add(RiderSalarySubject(code=f'SUB{n}', name=f'科目{n}', direction=direction, **kw))

    async def plan_version(self, items: list[dict[str, Any]]) -> RiderSalaryPlanVersion:
        """items: [{'formula': '5', 'stage': 'per_order', 'condition': None, 'direction': 'bonus'}]"""
        n = self._next()
        plan = await self.add(RiderSalaryPlan(code=f'P{n}', name=f'方案{n}', short_name=f'方{n}', color='#1677ff'))
        version = await self.add(
            RiderSalaryPlanVersion(plan_id=plan.id, version_no=1, status=PlanVersionStatus.active.value)
        )
        for index, item in enumerate(items):
            subject = await self.subject(item.get('direction', SubjectDirection.bonus.value))
            await self.add(
                RiderSalaryPlanItem(
                    plan_version_id=version.id,
                    subject_id=subject.id,
                    name=item.get('name', f'项{index}'),
                    stage=item.get('stage', CalcStage.per_order.value),
                    sort_order=index,
                    condition_expr=item.get('condition'),
                    formula_expr=item['formula'],
                )
            )
        return version

    async def bind(
        self,
        rider: RiderSalaryRider,
        version: RiderSalaryPlanVersion,
        start: date,
        end: date | None = None,
        binding_type: str = BindingType.default.value,
    ) -> RiderSalaryRiderPlanBinding:
        return await self.add(
            RiderSalaryRiderPlanBinding(
                rider_id=rider.id,
                plan_version_id=version.id,
                start_date=start,
                end_date=end,
                binding_type=binding_type,
            )
        )

    async def period(
        self, site: RiderSalarySite, start: date, end: date, *, rider_id: int = 0, **kw: Any
    ) -> RiderSalarySettlePeriod:
        kw.setdefault('cycle_type', 'month')
        return await self.add(
            RiderSalarySettlePeriod(site_id=site.id, rider_id=rider_id, start_date=start, end_date=end, **kw)
        )

    async def orders(self, rider: RiderSalaryRider, day: date, count: int = 1, **kw: Any) -> list[RiderSalaryOrder]:
        rows = []
        for _ in range(count):
            n = self._next()
            rows.append(
                await self.add(
                    RiderSalaryOrder(
                        order_no=f'O{n}',
                        site_id=kw.get('site_id', rider.site_id),
                        rider_id=rider.id,
                        biz_date=day,
                        distance_km=kw.get('distance_km', Decimal('1.00')),
                        weight_jin=kw.get('weight_jin', Decimal('1.00')),
                        order_time=datetime.combine(day, time(12, 0), tzinfo=timezone.tz_info),
                        deliver_time=datetime.combine(day, time(12, 30), tzinfo=timezone.tz_info),
                        status=OrderStatus.completed.value,
                    )
                )
            )
        return rows

    async def paid_advance(
        self, rider: RiderSalaryRider, amount: str, paid_time: datetime | None = None
    ) -> RiderSalaryAdvance:
        value = Decimal(amount)
        return await self.add(
            RiderSalaryAdvance(
                rider_id=rider.id,
                site_id=rider.site_id,
                amount=value,
                reason='测试',
                status='paid',
                paid_time=paid_time or timezone.now(),
                remaining_amount=value,
            )
        )
