"""P0-11 骑手编辑收口，不再绕过三件套。

P1-03 集成基座目录已出现，但由测试通道并行改动，本条不往 ``tests/integration/`` 写用例。
验收写成 schema 校验和服务层单测。基座稳定后可迁成走 API 的场景。

计划允许「忽略或拒绝」。这里选择拒绝：请求体带 ``status`` / ``employ_type`` / ``leave_date``
时 Pydantic 直接校验失败（HTTP 422）。

换站日按 Q-11 推荐方案处理：操作当天落在新旧站点任一已锁账周期则拒绝，不静默改未锁部分。
"""

from contextlib import contextmanager
from datetime import UTC, date, datetime
from re import IGNORECASE, findall, split
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import anyio
import pytest

from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from backend.common.exception import errors
from backend.plugin.rider_salary.schema.rider import UpdateRiderParam
from backend.plugin.rider_salary.service.rider_service import RiderService, rider_service

_TODAY = date(2026, 10, 9)
_SEP_START = date(2026, 9, 1)
_SEP_END = date(2026, 9, 30)
_OPEN_END = date(9999, 12, 31)
_LOCK_MSG = '该日期所属结算周期已锁账'
_FACT_MSG = '用工类型、状态和离职日期请通过用工历史或离职办理修改'


def _run(case: Any) -> None:
    anyio.run(case)


def _rider(**kwargs: object) -> SimpleNamespace:
    data: dict[str, object] = {
        'id': 7,
        'job_no': 'D5A001',
        'name': '甲',
        'phone': '13800000000',
        'site_id': 3,
        'employ_type': 'part_time',
        'hire_date': date(2026, 1, 1),
        'leave_date': None,
        'status': 'on_job',
        'advance_limit': None,
        'settle_cycle_override': None,
        'cycle_config_override': None,
        'user_id': None,
        'remark': None,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _request() -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(id=1, username='admin', is_superuser=True))


def _sql(stmt: object) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))


def _span_overlaps_september(stmt: object) -> bool:
    for clause in split(r'\bOR\b', _sql(stmt), flags=IGNORECASE):
        found = [date.fromisoformat(item) for item in findall(r'\d{4}-\d{2}-\d{2}', clause)]
        if len(found) < 2:
            continue
        start, end = min(found), max(found)
        if start <= _SEP_END and end >= _SEP_START:
            return True
    return False


@contextmanager
def _service(rider: SimpleNamespace, *, september_locked: bool = False, lock_new_site: bool = False) -> Any:
    captured: list[object] = []
    executed: list[object] = []
    payloads: list[dict[str, object]] = []

    def scalar(stmt: object) -> int | None:
        captured.append(stmt)
        sql = _sql(stmt)
        if lock_new_site and 'site_id = 8' in sql:
            return 11
        if september_locked and _span_overlaps_september(stmt):
            return 11
        return None

    def execute(stmt: object) -> SimpleNamespace:
        executed.append(stmt)
        return SimpleNamespace(rowcount=1)

    def apply_update(_db: object, _pk: int, obj: UpdateRiderParam, **kwargs: object) -> int:
        payload = obj.model_dump(exclude_unset=True, exclude={'reason'})
        payload.update(kwargs)
        payloads.append(payload)
        for key, value in payload.items():
            setattr(rider, key, value)
        return 1

    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=scalar)
    db.execute = AsyncMock(side_effect=execute)
    env = SimpleNamespace(
        db=db,
        captured=captured,
        executed=executed,
        payloads=payloads,
        mark_stale=AsyncMock(),
        audit=AsyncMock(),
        rider_update=AsyncMock(side_effect=apply_update),
    )
    prefix = 'backend.plugin.rider_salary.service.rider_service.'
    targets = {
        'rider_dao.update': env.rider_update,
        'rider_dao.get': AsyncMock(return_value=rider),
        'site_dao.get': AsyncMock(return_value=SimpleNamespace(id=8, name='乙站')),
        'get_visible_site_ids': AsyncMock(return_value=None),
        'mark_stale': env.mark_stale,
        'audit_service.record': env.audit,
    }
    patches = [patch.object(RiderService, '_get_visible_rider', AsyncMock(return_value=rider))]
    patches.extend(patch(f'{prefix}{name}', mock) for name, mock in targets.items())
    patches.append(patch(f'{prefix}timezone.now', return_value=datetime(2026, 10, 9, 8, 0, tzinfo=UTC)))
    for item in patches:
        item.start()
    try:
        yield env
    finally:
        for item in reversed(patches):
            item.stop()


def test_update_schema_rejects_employ_status_and_leave() -> None:
    """编辑 DTO 去掉这三项，传入即拒绝。"""
    assert 'employ_type' not in UpdateRiderParam.model_fields
    assert 'status' not in UpdateRiderParam.model_fields
    assert 'leave_date' not in UpdateRiderParam.model_fields
    for payload in (
        {'name': '乙', 'status': 'resigned'},
        {'employ_type': 'full_time'},
        {'leave_date': '2026-09-30'},
    ):
        with pytest.raises(ValidationError, match=_FACT_MSG):
            UpdateRiderParam.model_validate(payload)
    kept = UpdateRiderParam.model_validate({'name': '乙'})
    assert kept.model_dump(exclude_unset=True) == {'name': '乙'}


def test_plain_edit_does_not_touch_payroll_facts_or_mark_stale() -> None:
    """只改姓名：状态保持在职，不标重算，审计带改前改后。"""
    rider = _rider()
    obj = UpdateRiderParam.model_validate({'name': '乙'})

    async def _case() -> None:
        with _service(rider) as env:
            count = await rider_service.update(db=env.db, request=_request(), pk=7, obj=obj)
            assert count == 1
            assert env.payloads == [{'name': '乙'}]
            assert rider.status == 'on_job'
            assert rider.employ_type == 'part_time'
            assert rider.leave_date is None
            env.mark_stale.assert_not_awaited()
            env.db.execute.assert_not_awaited()
            record = env.audit.await_args.kwargs
            assert record['before']['name'] == '甲'
            assert record['before']['status'] == 'on_job'
            assert record['after']['name'] == '乙'
            assert record['after']['status'] == 'on_job'

    _run(_case)


def test_hire_date_shift_out_of_locked_september_rejected() -> None:
    """入职日从 9/1 改到 10/15，9 月不再在职，已锁账则拒绝且不落库。"""
    rider = _rider(hire_date=_SEP_START)
    obj = UpdateRiderParam(hire_date=date(2026, 10, 15))

    async def _case() -> None:
        with _service(rider, september_locked=True) as env:
            with pytest.raises(errors.ForbiddenError, match=_LOCK_MSG) as caught:
                await rider_service.update(db=env.db, request=_request(), pk=7, obj=obj)
            assert caught.value.code == 403
            sql = _sql(env.captured[0])
            assert '2026-09-01' in sql
            assert '2026-10-14' in sql
            env.rider_update.assert_not_awaited()
            env.mark_stale.assert_not_awaited()
            env.audit.assert_not_awaited()

    _run(_case)


def test_hire_date_shift_in_open_month_marks_only_changed_dates() -> None:
    """开放月内后移入职日：只把失去在职的那几天标成需重算，不用 9999-12-31。"""
    rider = _rider(hire_date=date(2026, 10, 1))
    obj = UpdateRiderParam(hire_date=date(2026, 10, 15))

    async def _case() -> None:
        with _service(rider) as env:
            await rider_service.update(db=env.db, request=_request(), pk=7, obj=obj)
            env.mark_stale.assert_awaited_once()
            stale = env.mark_stale.await_args.kwargs
            assert stale['date_from'] == date(2026, 10, 1)
            assert stale['date_to'] == date(2026, 10, 14)
            assert stale['date_to'] != _OPEN_END
            assert rider.hire_date == date(2026, 10, 15)
            record = env.audit.await_args.kwargs
            assert record['before']['hire_date'] == '2026-10-01'
            assert record['after']['hire_date'] == '2026-10-15'

    _run(_case)


def test_hire_date_after_leave_rejected() -> None:
    rider = _rider(leave_date=date(2026, 10, 1))
    obj = UpdateRiderParam(hire_date=date(2026, 10, 15))

    async def _case() -> None:
        with _service(rider) as env:
            with pytest.raises(errors.RequestError, match='入职日期不能晚于离职日期'):
                await rider_service.update(db=env.db, request=_request(), pk=7, obj=obj)
            env.rider_update.assert_not_awaited()

    _run(_case)


def test_transfer_on_locked_new_site_rejected() -> None:
    """Q-11：换站日（当天）落在新站点已锁账周期，拒绝，不改站点。"""
    rider = _rider()
    obj = UpdateRiderParam(site_id=8, reason='换到乙站')

    async def _case() -> None:
        with _service(rider, lock_new_site=True) as env:
            with pytest.raises(errors.ForbiddenError, match=_LOCK_MSG) as caught:
                await rider_service.update(db=env.db, request=_request(), pk=7, obj=obj)
            assert caught.value.code == 403
            assert any('2026-10-09' in _sql(stmt) and 'site_id = 8' in _sql(stmt) for stmt in env.captured)
            assert rider.site_id == 3
            env.rider_update.assert_not_awaited()
            env.db.execute.assert_not_awaited()
            env.audit.assert_not_awaited()

    _run(_case)


def test_transfer_marks_open_drafts_on_both_sites() -> None:
    """换站后新旧两个站点的开放、补发中草稿都标成需重算，并写审计。"""
    rider = _rider()
    obj = UpdateRiderParam(site_id=8, reason='换到乙站')

    async def _case() -> None:
        with _service(rider) as env:
            await rider_service.update(db=env.db, request=_request(), pk=7, obj=obj)
            assert rider.site_id == 8
            env.mark_stale.assert_not_awaited()
            env.db.execute.assert_awaited_once()
            sql = _sql(env.executed[0])
            assert 'site_id IN (3, 8)' in sql
            assert 'open' in sql
            assert 'reopened' in sql
            assert 'draft' in sql
            assert 'stale' in sql
            assert 'locked' not in sql
            assert 'paid' not in sql
            record = env.audit.await_args.kwargs
            assert record['before']['site_id'] == 3
            assert record['after']['site_id'] == 8
            assert record['reason'] == '换到乙站'

    _run(_case)
