"""P0-12 日标记识别骑手级锁账周期。

验收用例目前写成服务层单测，不依赖 P1-03 集成基座。基座就绪后迁到
``backend/plugin/rider_salary/tests/integration/``，改成走 API：
骑手级周期锁账后修改该日日标记被拒绝；读接口 ``is_locked`` 与写入规则一致。

锁账拒绝沿用现有 ``assert_not_locked`` 的 ForbiddenError（业务码 403）和同一句文案。
计划验收里的「返回 400」按领域约定落成 403，避免日标记与订单/奖惩的锁账错误码分叉。
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anyio
import pytest

from sqlalchemy.dialects import postgresql

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import PeriodStatus
from backend.plugin.rider_salary.schema.day_flag import DayFlagItem, UpsertDayFlagParam
from backend.plugin.rider_salary.service.day_flag_service import day_flag_service, rider_ids_for_day_flag_recalc
from backend.plugin.rider_salary.utils.lock_check import is_locked, site_locked_dates

_LOCK_MSG = '该日期所属结算周期已锁账，禁止修改，请走反冲补发流程'


class _Rows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


def _sql(stmt: object) -> str:
    compiled = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True})
    return str(compiled)


def _where(sql: str) -> str:
    return sql.split('WHERE', 1)[-1]


def _period(*, rider_id: int, start: date, end: date, status: str = PeriodStatus.locked.value) -> SimpleNamespace:
    return SimpleNamespace(
        id=rider_id + 100,
        site_id=1,
        rider_id=rider_id,
        start_date=start,
        end_date=end,
        status=status,
        deleted=0,
    )


def _request() -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(id=1, is_superuser=True))


def _db_scalars(*batches: list[object]) -> AsyncMock:
    pending = [_Rows(list(batch)) for batch in batches]
    captured: list[object] = []

    def _scalars(stmt: object) -> _Rows:
        captured.append(stmt)
        return pending.pop(0)

    db = AsyncMock()
    db.scalars = AsyncMock(side_effect=_scalars)
    db.captured = captured
    return db


def test_site_locked_dates_query_includes_any_rider_period() -> None:
    """站点级事实不能再把查询限制在 rider_id=0。"""
    db = _db_scalars([])

    async def _case() -> None:
        locked = await site_locked_dates(db, site_id=1, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))
        assert locked == set()

    anyio.run(_case)
    where = _where(_sql(db.captured[0]))
    assert 'rider_id' not in where
    assert 'locked' in where
    assert 'paid' in where
    assert 'reopened' not in where
    assert 'open' not in where


def test_rider_level_locked_period_marks_those_dates() -> None:
    period = _period(rider_id=7, start=date(2026, 9, 3), end=date(2026, 9, 5))
    db = _db_scalars([period])

    async def _case() -> None:
        locked = await site_locked_dates(db, site_id=1, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))
        assert locked == {date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 5)}

    anyio.run(_case)


def test_existing_is_locked_without_rider_still_site_level_only() -> None:
    """已有调用方：rider_id 为空时仍只查站点级周期。"""
    captured: list[object] = []

    def _scalar(stmt: object) -> None:
        captured.append(stmt)

    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=_scalar)

    async def _case() -> None:
        assert await is_locked(db, site_id=1, rider_id=None, biz_date=date(2026, 9, 1)) is False

    anyio.run(_case)
    assert len(captured) == 1
    where = _where(_sql(captured[0]))
    assert 'rider_id' in where
    assert '0' in where


def test_recalc_riders_come_from_orders_and_drafts() -> None:
    """离职骑手 99 当日有订单、骑手 77 只有草稿，在职但无关的骑手不在集合里。"""
    db = _db_scalars([99], [77, 99])

    async def _case() -> None:
        ids = await rider_ids_for_day_flag_recalc(db, site_id=1, dates=[date(2026, 9, 4), date(2026, 9, 4)])
        assert ids == [77, 99]

    anyio.run(_case)
    order_where = _where(_sql(db.captured[0]))
    draft_where = _where(_sql(db.captured[1]))
    assert 'rs_order' in _sql(db.captured[0])
    assert '2026-09-04' in order_where
    assert 'draft' in draft_where
    assert 'on_job' not in draft_where
    assert 'on_job' not in order_where


def test_upsert_rejects_rider_level_locked_day_before_write() -> None:
    obj = UpsertDayFlagParam(
        site_id=1,
        days=[DayFlagItem(biz_date=date(2026, 9, 4), bad_weather=True)],
    )

    async def _case() -> None:
        with (
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.get_visible_site_ids',
                AsyncMock(return_value=None),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.site_dao.get',
                AsyncMock(return_value=SimpleNamespace(id=1)),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.site_locked_dates',
                AsyncMock(return_value={date(2026, 9, 4)}),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.day_flag_dao.get_by_site_date',
                AsyncMock(side_effect=AssertionError('锁账日不应写入')),
            ) as read_row,
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.mark_stale',
                AsyncMock(side_effect=AssertionError('锁账日不应重算')),
            ),
        ):
            with pytest.raises(errors.ForbiddenError, match=_LOCK_MSG) as caught:
                await day_flag_service.upsert(db=AsyncMock(), request=_request(), obj=obj)
            assert caught.value.code == 403
            read_row.assert_not_awaited()

    anyio.run(_case)


def test_upsert_rejects_whole_batch_when_any_day_is_locked() -> None:
    obj = UpsertDayFlagParam(
        site_id=1,
        days=[
            DayFlagItem(biz_date=date(2026, 9, 1), high_temp=True),
            DayFlagItem(biz_date=date(2026, 9, 4), promo=True),
        ],
    )

    async def _case() -> None:
        with (
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.get_visible_site_ids',
                AsyncMock(return_value=None),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.site_dao.get',
                AsyncMock(return_value=SimpleNamespace(id=1)),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.site_locked_dates',
                AsyncMock(return_value={date(2026, 9, 4)}),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.day_flag_dao.create',
                AsyncMock(side_effect=AssertionError('批次中有锁账日时不应部分写入')),
            ) as create,
        ):
            with pytest.raises(errors.ForbiddenError):
                await day_flag_service.upsert(db=AsyncMock(), request=_request(), obj=obj)
            create.assert_not_awaited()

    anyio.run(_case)


def test_upsert_marks_derived_riders_not_all_on_job() -> None:
    obj = UpsertDayFlagParam(
        site_id=1,
        days=[DayFlagItem(biz_date=date(2026, 9, 4), bad_weather=True)],
    )
    existed = SimpleNamespace(id=11)

    async def _case() -> None:
        with (
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.get_visible_site_ids',
                AsyncMock(return_value=None),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.site_dao.get',
                AsyncMock(return_value=SimpleNamespace(id=1)),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.site_locked_dates',
                AsyncMock(return_value=set()),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.day_flag_dao.get_by_site_date',
                AsyncMock(return_value=existed),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.day_flag_dao.update',
                AsyncMock(),
            ) as update,
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.rider_ids_for_day_flag_recalc',
                AsyncMock(return_value=[77, 99]),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.mark_stale',
                AsyncMock(),
            ) as stale,
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.audit_service.record',
                AsyncMock(),
            ) as audit,
            patch(
                'backend.plugin.rider_salary.crud.rider.rider_dao.get_on_job_ids_by_site',
                AsyncMock(side_effect=AssertionError('不应再只取在职骑手')),
            ),
        ):
            await day_flag_service.upsert(db=AsyncMock(), request=_request(), obj=obj)
            update.assert_awaited_once()
            stale.assert_awaited_once()
            assert stale.await_args.kwargs['rider_ids'] == [77, 99]
            assert stale.await_args.kwargs['date_from'] == date(2026, 9, 4)
            assert stale.await_args.kwargs['date_to'] == date(2026, 9, 4)
            assert audit.await_args.kwargs['action'] == '更新日标记'

    anyio.run(_case)


def test_get_month_is_locked_follows_any_period() -> None:
    flag = SimpleNamespace(
        id=3,
        site_id=1,
        biz_date=date(2026, 9, 4),
        bad_weather=True,
        high_temp=False,
        promo=False,
        remark='雨',
        created_time=None,
        updated_time=None,
    )

    async def _case() -> None:
        with (
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.get_visible_site_ids',
                AsyncMock(return_value=None),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.site_dao.get',
                AsyncMock(return_value=SimpleNamespace(id=1)),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.day_flag_dao.get_by_site_range',
                AsyncMock(return_value=[flag]),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.site_locked_dates',
                AsyncMock(return_value={date(2026, 9, 4), date(2026, 9, 5)}),
            ),
        ):
            rows = await day_flag_service.get_month(db=AsyncMock(), request=_request(), site_id=1, month='2026-09')
        by_date = {row.biz_date: row for row in rows}
        assert len(rows) == 30
        assert by_date[date(2026, 9, 4)].is_locked is True
        assert by_date[date(2026, 9, 4)].bad_weather is True
        assert by_date[date(2026, 9, 5)].is_locked is True
        assert by_date[date(2026, 9, 5)].id is None
        assert by_date[date(2026, 9, 1)].is_locked is False

    anyio.run(_case)


def test_empty_recalc_dates() -> None:
    async def _case() -> None:
        assert await rider_ids_for_day_flag_recalc(AsyncMock(), site_id=1, dates=[]) == []

    anyio.run(_case)
