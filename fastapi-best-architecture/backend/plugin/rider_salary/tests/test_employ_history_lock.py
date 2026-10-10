"""P0-09 用工历史写操作补锁账校验。

验收用例目前写成纯函数和服务层单测。P1-03 集成基座就绪后，迁到
``backend/plugin/rider_salary/tests/integration/``，改成走 API 的 E6 场景
（已锁账的 9 月内新增用工历史被拒绝；开放周期内的修改只把受影响周期标成 stale）。

计划验收写的是 HTTP 400。本条与 ``assert_not_locked``、骨架说明对齐，拒绝码为
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
from backend.plugin.rider_salary.enums import EmployType
from backend.plugin.rider_salary.schema.rider import (
    CreateEmployHistoryParam,
    RiderLeaveParam,
    UpdateEmployHistoryParam,
)
from backend.plugin.rider_salary.service.rider_service import (
    RiderService,
    assert_range_unlocked,
    changed_coverage_spans,
    employ_create_ranges,
    leave_employ_touch,
    rider_service,
    stale_bounds,
)

_TODAY = date(2026, 10, 9)
_OPEN_END = date(9999, 12, 31)
_SEP_START = date(2026, 9, 1)
_SEP_END = date(2026, 9, 30)
_LOCK_MSG = '该日期所属结算周期已锁账'


def _run(case: Any) -> None:
    anyio.run(case)


def _history(**kwargs: object) -> SimpleNamespace:
    data: dict[str, object] = {
        'id': 1,
        'rider_id': 7,
        'employ_type': EmployType.part_time.value,
        'start_date': date(2026, 8, 1),
        'end_date': None,
        'remark': None,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _rider() -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        job_no='D5A001',
        name='甲',
        site_id=3,
        status='on_job',
        employ_type=EmployType.part_time.value,
        hire_date=date(2026, 1, 1),
        leave_date=None,
        phone=None,
        advance_limit=None,
        settle_cycle_override=None,
        cycle_config_override=None,
        user_id=None,
        remark=None,
    )


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


def _remember_end(rows: list[SimpleNamespace]) -> Any:
    def update_history(_db: object, history_id: int, obj: object) -> int:
        end_date = getattr(obj, 'end_date', None)
        for row in rows:
            if row.id == history_id and end_date is not None:
                row.end_date = end_date
        return 1

    return update_history


def _find_history(rows: list[SimpleNamespace]) -> Any:
    def get_history(_db: object, history_id: int) -> SimpleNamespace | None:
        for row in rows:
            if row.id == history_id:
                return row
        return None

    return get_history


def _new_history(_db: object, rider_id: int, obj: CreateEmployHistoryParam) -> SimpleNamespace:
    return SimpleNamespace(
        id=99,
        rider_id=rider_id,
        employ_type=getattr(obj.employ_type, 'value', obj.employ_type),
        start_date=obj.start_date,
        end_date=obj.end_date,
        remark=obj.remark,
    )


@contextmanager
def _service(histories: list[SimpleNamespace], *, september_locked: bool = False) -> Any:
    rows = list(histories)
    captured: list[object] = []
    rider = _rider()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=_scalar(captured, september_locked=september_locked))
    env = SimpleNamespace(
        db=db,
        captured=captured,
        mark_stale=AsyncMock(),
        audit=AsyncMock(),
        history_update=AsyncMock(side_effect=_remember_end(rows)),
        history_get=AsyncMock(side_effect=_find_history(rows)),
        history_create=AsyncMock(side_effect=_new_history),
        history_delete=AsyncMock(return_value=1),
        close_open=AsyncMock(return_value=1),
        rider_update=AsyncMock(return_value=1),
    )
    targets = {
        'rider_employ_history_dao.get_by_rider': AsyncMock(return_value=rows),
        'rider_employ_history_dao.update': env.history_update,
        'rider_employ_history_dao.get': env.history_get,
        'rider_employ_history_dao.create': env.history_create,
        'rider_employ_history_dao.delete': env.history_delete,
        'rider_employ_history_dao.close_open': env.close_open,
        'rider_plan_binding_dao.get_by_rider': AsyncMock(return_value=[]),
        'rider_dao.update': env.rider_update,
        'rider_dao.get': AsyncMock(return_value=rider),
        'mark_stale': env.mark_stale,
        'audit_service.record': env.audit,
        'advance_service.reject_pending_on_leave': AsyncMock(
            return_value=SimpleNamespace(rejected_count=0, to_pay_count=0, hints=[])
        ),
    }
    prefix = 'backend.plugin.rider_salary.service.rider_service.'
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


def _stale_call(env: SimpleNamespace) -> Any:
    env.mark_stale.assert_awaited()
    return env.mark_stale.await_args.kwargs


def test_auto_close_changes_only_dates_after_close() -> None:
    previous = _history(start_date=date(2026, 9, 1), end_date=None)
    _closings, changed = employ_create_ranges([previous], date(2026, 11, 1), None)
    assert changed
    assert all(start >= date(2026, 11, 1) for start, _end in changed)
    for span in changed:
        window = stale_bounds([span], today=_TODAY)
        assert window is not None
        assert window[0] >= date(2026, 11, 1)
        assert window[1] != _OPEN_END


def test_changed_spans_ignore_unchanged_prefix_and_keep_type_change() -> None:
    assert changed_coverage_spans(
        date(2026, 1, 1),
        None,
        date(2026, 1, 1),
        date(2026, 10, 31),
        type_changed=False,
    ) == [(date(2026, 11, 1), None)]
    assert changed_coverage_spans(
        date(2026, 10, 1),
        date(2026, 10, 31),
        date(2026, 10, 1),
        date(2026, 10, 31),
        type_changed=True,
    ) == [(date(2026, 10, 1), date(2026, 10, 31))]
    assert (
        changed_coverage_spans(
            date(2026, 10, 1),
            date(2026, 10, 31),
            date(2026, 10, 1),
            date(2026, 10, 31),
            type_changed=False,
        )
        == []
    )
    moved = changed_coverage_spans(
        date(2026, 9, 1),
        date(2026, 9, 30),
        date(2026, 10, 1),
        date(2026, 10, 31),
        type_changed=False,
    )
    assert (date(2026, 9, 1), date(2026, 9, 30)) in moved
    assert (date(2026, 10, 1), date(2026, 10, 31)) in moved


def test_stale_bounds_cap_open_end_at_today() -> None:
    assert stale_bounds([(date(2026, 1, 1), None)], today=_TODAY) == (date(2026, 1, 1), _TODAY)
    assert stale_bounds([(date(2026, 10, 1), date(2026, 10, 31))], today=_TODAY) == (
        date(2026, 10, 1),
        date(2026, 10, 31),
    )
    assert stale_bounds([(date(2026, 11, 1), None)], today=_TODAY) == (date(2026, 11, 1), date(2026, 11, 1))
    window = stale_bounds([(date(2026, 10, 1), None)], today=_TODAY)
    assert window is not None
    assert window[1] != _OPEN_END
    assert window[1] < date(2026, 11, 1)


def test_leave_touch_only_changes_dates_after_leave() -> None:
    changed = leave_employ_touch([_history(start_date=date(2026, 9, 1))], date(2026, 11, 15))
    assert changed == [(date(2026, 11, 16), None)]
    assert stale_bounds(changed, today=_TODAY) == (date(2026, 11, 16), date(2026, 11, 16))


def test_range_lock_query_covers_locked_paid_and_open_end() -> None:
    captured: list[object] = []

    async def _case() -> None:
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=_scalar(captured, september_locked=False))
        await assert_range_unlocked(db, site_id=3, rider_id=7, ranges=[(date(2026, 9, 1), None)])

    _run(_case)
    sql = _sql(captured[0])
    assert 'locked' in sql
    assert 'paid' in sql
    assert 'reopened' not in sql
    assert '9999-12-31' in sql
    assert '2026-09-01' in sql


def test_range_lock_rejects_when_period_hits() -> None:
    async def _case() -> None:
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=11)
        with pytest.raises(errors.ForbiddenError, match=_LOCK_MSG) as caught:
            await assert_range_unlocked(
                db,
                site_id=3,
                rider_id=7,
                ranges=[(date(2026, 9, 10), date(2026, 9, 30))],
            )
        assert caught.value.code == 403

    _run(_case)


def test_e6_create_inside_locked_september_rejected() -> None:
    """E6：已锁账的 9 月内新增用工历史，拒绝且不落库。"""
    obj = CreateEmployHistoryParam(
        employ_type=EmployType.full_time,
        start_date=date(2026, 9, 10),
        end_date=None,
    )

    async def _case() -> None:
        with _service([], september_locked=True) as env:
            with pytest.raises(errors.ForbiddenError, match=_LOCK_MSG) as caught:
                await rider_service.create_employ_history(db=env.db, request=_request(), pk=7, obj=obj)
            assert caught.value.code == 403
            env.history_create.assert_not_awaited()
            env.mark_stale.assert_not_awaited()
            env.audit.assert_not_awaited()

    _run(_case)


def test_new_segment_after_locked_month_is_allowed() -> None:
    """开放段起于已锁的 9 月，新增 11 月起的新段：9 月类型不变，放行。"""
    previous = _history(id=4, start_date=_SEP_START, end_date=None)
    obj = CreateEmployHistoryParam(employ_type=EmployType.full_time, start_date=date(2026, 11, 1), end_date=None)

    async def _case() -> None:
        with _service([previous], september_locked=True) as env:
            await rider_service.create_employ_history(db=env.db, request=_request(), pk=7, obj=obj)
            env.history_update.assert_awaited()
            env.history_create.assert_awaited()
            windows = [call.kwargs for call in env.mark_stale.await_args_list]
            assert windows
            assert all(item['date_from'] >= date(2026, 11, 1) for item in windows)
            assert all(item['date_to'] != _OPEN_END for item in windows)

    _run(_case)


def test_open_period_create_marks_only_affected_dates() -> None:
    obj = CreateEmployHistoryParam(
        employ_type=EmployType.full_time,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
    )

    async def _case() -> None:
        with _service([]) as env:
            await rider_service.create_employ_history(db=env.db, request=_request(), pk=7, obj=obj)
            stale = _stale_call(env)
            assert stale['date_from'] == date(2026, 10, 1)
            assert stale['date_to'] == date(2026, 10, 31)
            assert stale['date_to'] != _OPEN_END
            assert stale['date_to'] < date(2026, 11, 1)
            env.audit.assert_awaited()

    _run(_case)


def test_open_ended_create_does_not_use_sentinel_end() -> None:
    obj = CreateEmployHistoryParam(employ_type=EmployType.full_time, start_date=date(2026, 10, 1), end_date=None)

    async def _case() -> None:
        with _service([]) as env:
            await rider_service.create_employ_history(db=env.db, request=_request(), pk=7, obj=obj)
            stale = _stale_call(env)
            assert stale['date_from'] == date(2026, 10, 1)
            assert stale['date_to'] == _TODAY
            assert stale['date_to'] != _OPEN_END

    _run(_case)


def test_update_cannot_move_locked_month_out_of_range() -> None:
    row = _history(id=5, start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))
    obj = UpdateEmployHistoryParam(start_date=date(2026, 10, 1), end_date=date(2026, 10, 31))

    async def _case() -> None:
        with _service([row], september_locked=True) as env:
            with pytest.raises(errors.ForbiddenError, match=_LOCK_MSG):
                await rider_service.update_employ_history(
                    db=env.db,
                    request=_request(),
                    pk=7,
                    history_id=5,
                    obj=obj,
                )
            sql = _sql(env.captured[0])
            assert '2026-09-01' in sql
            assert '2026-10-31' in sql
            env.history_update.assert_not_awaited()

    _run(_case)


def test_update_in_open_month_marks_only_that_month() -> None:
    row = _history(id=5, start_date=date(2026, 10, 1), end_date=date(2026, 10, 31))
    obj = UpdateEmployHistoryParam(employ_type=EmployType.full_time)

    async def _case() -> None:
        with _service([row]) as env:
            await rider_service.update_employ_history(db=env.db, request=_request(), pk=7, history_id=5, obj=obj)
            stale = _stale_call(env)
            assert stale['date_from'] == date(2026, 10, 1)
            assert stale['date_to'] == date(2026, 10, 31)
            assert stale['date_to'] != _OPEN_END

    _run(_case)


def test_open_ended_type_change_stops_at_today() -> None:
    row = _history(id=5, start_date=date(2026, 1, 1), end_date=None)
    obj = UpdateEmployHistoryParam(employ_type=EmployType.full_time)

    async def _case() -> None:
        with _service([row]) as env:
            await rider_service.update_employ_history(db=env.db, request=_request(), pk=7, history_id=5, obj=obj)
            stale = _stale_call(env)
            assert stale['date_from'] == date(2026, 1, 1)
            assert stale['date_to'] == _TODAY
            assert stale['date_to'] != _OPEN_END

    _run(_case)


def test_delete_locked_range_rejected() -> None:
    row = _history(id=5, start_date=date(2026, 9, 1), end_date=date(2026, 9, 30))

    async def _case() -> None:
        with _service([row], september_locked=True) as env:
            with pytest.raises(errors.ForbiddenError, match=_LOCK_MSG):
                await rider_service.delete_employ_history(db=env.db, request=_request(), pk=7, history_id=5)
            env.history_delete.assert_not_awaited()
            env.mark_stale.assert_not_awaited()

    _run(_case)


def test_leave_after_locked_month_is_allowed() -> None:
    """开放段起于已锁的 9 月，11/15 离职收尾：变化从 11/16 起，放行。"""
    row = _history(start_date=_SEP_START, end_date=None)
    obj = RiderLeaveParam(leave_date=date(2026, 11, 15), reason='个人原因')

    async def _case() -> None:
        with _service([row], september_locked=True) as env:
            await rider_service.leave(db=env.db, request=_request(), pk=7, obj=obj)
            env.close_open.assert_awaited()
            env.rider_update.assert_awaited()
            stale = _stale_call(env)
            assert stale['date_from'] == date(2026, 11, 16)
            assert stale['date_to'] != _OPEN_END

    _run(_case)


def test_type_change_covering_locked_month_rejected() -> None:
    row = _history(id=5, start_date=date(2026, 8, 1), end_date=date(2026, 10, 31))
    obj = UpdateEmployHistoryParam(employ_type=EmployType.full_time)

    async def _case() -> None:
        with _service([row], september_locked=True) as env:
            with pytest.raises(errors.ForbiddenError, match=_LOCK_MSG) as caught:
                await rider_service.update_employ_history(
                    db=env.db,
                    request=_request(),
                    pk=7,
                    history_id=5,
                    obj=obj,
                )
            assert caught.value.code == 403
            env.history_update.assert_not_awaited()

    _run(_case)


def test_moving_start_into_locked_month_rejected() -> None:
    row = _history(id=5, start_date=date(2026, 8, 1), end_date=None)
    obj = UpdateEmployHistoryParam(start_date=date(2026, 9, 10))

    async def _case() -> None:
        with _service([row], september_locked=True) as env:
            with pytest.raises(errors.ForbiddenError, match=_LOCK_MSG) as caught:
                await rider_service.update_employ_history(
                    db=env.db,
                    request=_request(),
                    pk=7,
                    history_id=5,
                    obj=obj,
                )
            assert caught.value.code == 403
            sql = _sql(env.captured[0])
            assert '2026-08-01' in sql
            assert '2026-09-09' in sql
            env.history_update.assert_not_awaited()

    _run(_case)


def test_gap_between_changed_spans_does_not_hit_locked_month() -> None:
    async def _case() -> None:
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=_scalar([], september_locked=True))
        await assert_range_unlocked(
            db,
            site_id=3,
            rider_id=7,
            ranges=[(date(2026, 8, 1), date(2026, 8, 31)), (date(2026, 10, 1), date(2026, 10, 31))],
        )

    _run(_case)


def test_leave_in_open_period_marks_only_dates_after_leave() -> None:
    row = _history(start_date=date(2026, 8, 1), end_date=None)
    obj = RiderLeaveParam(leave_date=date(2026, 10, 5), reason='个人原因')

    async def _case() -> None:
        with _service([row]) as env:
            await rider_service.leave(db=env.db, request=_request(), pk=7, obj=obj)
            env.close_open.assert_awaited()
            stale = _stale_call(env)
            assert stale['date_from'] == date(2026, 10, 6)
            assert stale['date_to'] == _TODAY
            assert stale['date_to'] != _OPEN_END
            env.audit.assert_awaited()

    _run(_case)
