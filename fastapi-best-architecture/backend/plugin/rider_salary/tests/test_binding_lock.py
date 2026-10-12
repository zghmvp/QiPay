"""P0-10 修改绑定时只校验生效方案实际变化的日期。

P1-03 集成基座尚未就绪（没有 ``tests/integration/``），验收写成服务层单测。
基座就绪后迁到该目录，改成走 API 的 E7 场景。

计划正文写的是 HTTP 400。本条复用 ``assert_range_unlocked``，拒绝码为
``ForbiddenError``（403），文案为「该日期所属结算周期已锁账，禁止修改，请走反冲补发流程」。
"""

from contextlib import contextmanager
from datetime import UTC, date, datetime
from re import IGNORECASE, findall, split
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import anyio
import pytest

from sqlalchemy.dialects import postgresql

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import BindingType
from backend.plugin.rider_salary.schema.rider import CreatePlanBindingParam, UpdatePlanBindingParam
from backend.plugin.rider_salary.service.rider_service import RiderService, rider_service

_SEP_START = date(2026, 9, 1)
_SEP_END = date(2026, 9, 30)
_NOV_END = date(2026, 11, 30)
_LOCK_MSG = '该日期所属结算周期已锁账'


def _run(case: Any) -> None:
    anyio.run(case)


def _binding(**kwargs: object) -> SimpleNamespace:
    data: dict[str, object] = {
        'id': 5,
        'rider_id': 7,
        'plan_version_id': 11,
        'binding_type': BindingType.default.value,
        'start_date': _SEP_START,
        'end_date': None,
        'remark': None,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _rider() -> SimpleNamespace:
    return SimpleNamespace(id=7, job_no='D5A001', name='甲', site_id=3)


def _request() -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(id=1, username='admin'))


def _sql(stmt: object) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))


def _span_overlaps_september(stmt: object) -> bool:
    """按 OR 子句判断查询区间是否碰到已锁的 9 月，间隙不算"""
    for clause in split(r'\bOR\b', _sql(stmt), flags=IGNORECASE):
        found = [date.fromisoformat(item) for item in findall(r'\d{4}-\d{2}-\d{2}', clause)]
        if len(found) < 2:
            continue
        start, end = min(found), max(found)
        if start <= _SEP_END and end >= _SEP_START:
            return True
    return False


def _scalar(captured: list[object], *, september_locked: bool) -> Any:
    def scalar(stmt: object) -> int | None:
        captured.append(stmt)
        if september_locked and _span_overlaps_september(stmt):
            return 11
        return None

    return scalar


@contextmanager
def _service(bindings: list[SimpleNamespace], *, september_locked: bool = False) -> Any:
    rows = list(bindings)
    captured: list[object] = []
    rider = _rider()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=_scalar(captured, september_locked=september_locked))

    def get_binding(_db: object, binding_id: int) -> SimpleNamespace | None:
        for row in rows:
            if row.id == binding_id:
                return row
        return None

    def create_binding(_db: object, rider_id: int, obj: CreatePlanBindingParam) -> SimpleNamespace:
        return SimpleNamespace(
            id=99,
            rider_id=rider_id,
            plan_version_id=obj.plan_version_id,
            binding_type=getattr(obj.binding_type, 'value', obj.binding_type),
            start_date=obj.start_date,
            end_date=obj.end_date,
            remark=obj.remark,
        )

    env = SimpleNamespace(
        db=db,
        captured=captured,
        mark_stale=AsyncMock(),
        audit=AsyncMock(),
        binding_get=AsyncMock(side_effect=get_binding),
        binding_create=AsyncMock(side_effect=create_binding),
        binding_update=AsyncMock(return_value=1),
        binding_delete=AsyncMock(return_value=1),
    )
    targets = {
        'rider_plan_binding_dao.get_by_rider': AsyncMock(return_value=rows),
        'rider_plan_binding_dao.get': env.binding_get,
        'rider_plan_binding_dao.create': env.binding_create,
        'rider_plan_binding_dao.update': env.binding_update,
        'rider_plan_binding_dao.delete': env.binding_delete,
        'mark_stale': env.mark_stale,
        'audit_service.record': env.audit,
    }
    prefix = 'backend.plugin.rider_salary.service.rider_service.'
    version = SimpleNamespace(is_used=True, status='active', deleted=0)
    patches = [
        patch.object(RiderService, '_get_visible_rider', AsyncMock(return_value=rider)),
        patch.object(RiderService, '_assert_plan_version_active', AsyncMock(return_value=version)),
    ]
    patches.extend(patch(f'{prefix}{name}', mock) for name, mock in targets.items())
    for item in patches:
        item.start()
    try:
        yield env
    finally:
        for item in reversed(patches):
            item.stop()


def test_e7_moving_start_out_of_locked_september_rejected() -> None:
    """E7：绑定盖住已锁的 9 月，把起始日改到 10/1，9 月失去方案，拒绝且不落库。"""
    row = _binding(start_date=_SEP_START, end_date=date(2026, 12, 31))
    obj = UpdatePlanBindingParam(start_date=date(2026, 10, 1), end_date=date(2026, 12, 31))

    async def _case() -> None:
        with _service([row], september_locked=True) as env:
            with pytest.raises(errors.ForbiddenError, match=_LOCK_MSG) as caught:
                await rider_service.update_binding(db=env.db, request=_request(), pk=7, binding_id=5, obj=obj)
            assert caught.value.code == 403
            sql = _sql(env.captured[0])
            assert '2026-09-01' in sql
            assert '2026-09-30' in sql
            env.binding_update.assert_not_awaited()
            env.mark_stale.assert_not_awaited()
            env.audit.assert_not_awaited()

    _run(_case)


def test_extend_binding_that_starts_in_locked_september_is_allowed() -> None:
    """起于已锁 9 月的绑定把结束日延长到 11 月：9 月方案不变，只校验新增日期，放行。"""
    row = _binding(start_date=_SEP_START, end_date=_SEP_END)
    obj = UpdatePlanBindingParam(end_date=_NOV_END)

    async def _case() -> None:
        with _service([row], september_locked=True) as env:
            count = await rider_service.update_binding(db=env.db, request=_request(), pk=7, binding_id=5, obj=obj)
            assert count == 1
            sql = _sql(env.captured[0])
            assert '2026-09-01' not in sql
            assert '2026-10-01' in sql
            assert '2026-11-30' in sql
            env.binding_update.assert_awaited()
            env.audit.assert_awaited()

    _run(_case)


def test_closing_open_binding_at_november_is_allowed() -> None:
    """起于已锁 9 月的开放绑定截止到 11 月：变化在 12 月之后，放行。"""
    row = _binding(start_date=_SEP_START, end_date=None)
    obj = UpdatePlanBindingParam(end_date=_NOV_END)

    async def _case() -> None:
        with _service([row], september_locked=True) as env:
            await rider_service.update_binding(db=env.db, request=_request(), pk=7, binding_id=5, obj=obj)
            sql = _sql(env.captured[0])
            assert '2026-09-01' not in sql
            assert '2026-12-01' in sql
            env.binding_update.assert_awaited()

    _run(_case)


def test_plan_change_covering_locked_september_rejected() -> None:
    """换方案且新旧区间都覆盖已锁的 9 月：并集含 9 月，拒绝。"""
    row = _binding(start_date=_SEP_START, end_date=_NOV_END, plan_version_id=11)
    obj = UpdatePlanBindingParam(plan_version_id=22)

    async def _case() -> None:
        with _service([row], september_locked=True) as env:
            with pytest.raises(errors.ForbiddenError, match=_LOCK_MSG) as caught:
                await rider_service.update_binding(db=env.db, request=_request(), pk=7, binding_id=5, obj=obj)
            assert caught.value.code == 403
            sql = _sql(env.captured[0])
            assert '2026-09-01' in sql
            assert '2026-11-30' in sql
            env.binding_update.assert_not_awaited()
            env.mark_stale.assert_not_awaited()

    _run(_case)


def test_create_covering_locked_september_rejected() -> None:
    """新增绑定整段都是变化日期，盖住已锁 9 月则拒绝。"""
    obj = CreatePlanBindingParam(
        plan_version_id=11,
        binding_type=BindingType.default,
        start_date=_SEP_START,
        end_date=_SEP_END,
    )

    async def _case() -> None:
        with _service([], september_locked=True) as env:
            with pytest.raises(errors.ForbiddenError, match=_LOCK_MSG) as caught:
                await rider_service.create_binding(db=env.db, request=_request(), pk=7, obj=obj)
            assert caught.value.code == 403
            env.binding_create.assert_not_awaited()
            env.mark_stale.assert_not_awaited()

    _run(_case)


def test_delete_covering_locked_september_rejected() -> None:
    """删除绑定按原区间整段校验，盖住已锁 9 月则拒绝。"""
    row = _binding(start_date=_SEP_START, end_date=_SEP_END)

    async def _case() -> None:
        with _service([row], september_locked=True) as env:
            with pytest.raises(errors.ForbiddenError, match=_LOCK_MSG) as caught:
                await rider_service.delete_binding(db=env.db, request=_request(), pk=7, binding_id=5)
            assert caught.value.code == 403
            env.binding_delete.assert_not_awaited()
            env.mark_stale.assert_not_awaited()

    _run(_case)


def test_closing_open_binding_marks_only_changed_dates() -> None:
    """截止开放绑定只标变化日期，开放端截到今天，不用 9999-12-31，也不标未变化的前缀。"""
    row = _binding(start_date=date(2026, 1, 1), end_date=None)
    obj = UpdatePlanBindingParam(end_date=date(2026, 9, 30))

    async def _case() -> None:
        with (
            _service([row]) as env,
            patch(
                'backend.plugin.rider_salary.service.rider_service.timezone.now',
                return_value=datetime(2026, 10, 9, 8, 0, tzinfo=UTC),
            ),
        ):
            await rider_service.update_binding(db=env.db, request=_request(), pk=7, binding_id=5, obj=obj)
            env.mark_stale.assert_awaited_once()
            stale = env.mark_stale.await_args.kwargs
            assert stale['rider_ids'] == [7]
            assert stale['date_from'] == date(2026, 10, 1)
            assert stale['date_to'] == date(2026, 10, 9)
            assert stale['date_to'] != date(9999, 12, 31)
            assert stale['date_from'] != date(2026, 1, 1)

    _run(_case)
