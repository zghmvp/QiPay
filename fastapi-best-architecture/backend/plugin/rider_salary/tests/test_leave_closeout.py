"""P0-04 离职配套的纯逻辑，以及离职日落在已锁账周期最后一天时拒绝。

锁账拒绝与 ``assert_not_locked`` 一致，使用 ``ForbiddenError``（403），
文案为「该日期所属结算周期已锁账，禁止修改，请走反冲补发流程」。
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anyio
import pytest

from sqlalchemy.dialects import postgresql

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import AdvanceStatus, EmployType
from backend.plugin.rider_salary.schema.rider import RiderLeaveParam
from backend.plugin.rider_salary.service.advance_service import (
    LEAVE_AUTO_REJECT_REASON,
    advance_service,
    leave_advance_hints,
)
from backend.plugin.rider_salary.service.rider_service import (
    RiderService,
    assert_leave_not_before_employment,
    binding_close_spans,
    leave_employ_touch,
    leave_lock_ranges,
    open_bindings_ending_on_leave,
    rider_service,
)

_SEP_END = date(2026, 9, 30)


def _history(**kwargs: object) -> SimpleNamespace:
    data: dict[str, object] = {
        'id': 1,
        'rider_id': 7,
        'employ_type': EmployType.part_time.value,
        'start_date': date(2026, 1, 1),
        'end_date': None,
        'remark': None,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _binding(**kwargs: object) -> SimpleNamespace:
    data: dict[str, object] = {
        'id': 4,
        'rider_id': 7,
        'plan_version_id': 9,
        'binding_type': 'default',
        'start_date': date(2026, 1, 1),
        'end_date': None,
        'remark': None,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def test_leave_date_not_before_hire_or_last_history() -> None:
    histories = [_history(start_date=date(2026, 3, 1))]
    assert_leave_not_before_employment(date(2026, 1, 1), histories, date(2026, 3, 1))
    with pytest.raises(errors.RequestError, match='入职日期'):
        assert_leave_not_before_employment(date(2026, 3, 1), histories, date(2026, 2, 28))
    with pytest.raises(errors.RequestError, match='用工历史'):
        assert_leave_not_before_employment(date(2026, 1, 1), histories, date(2026, 2, 28))


def test_open_binding_closes_on_leave_and_future_binding_rejected() -> None:
    closing = open_bindings_ending_on_leave(
        [_binding(), _binding(id=5, end_date=date(2026, 8, 31))],
        date(2026, 9, 10),
    )
    assert [item.id for item in closing] == [4]
    assert binding_close_spans(closing, date(2026, 9, 10)) == [(date(2026, 9, 11), None)]
    with pytest.raises(errors.RequestError, match='方案绑定'):
        open_bindings_ending_on_leave([_binding(start_date=date(2026, 10, 1))], date(2026, 9, 10))


def test_lock_ranges_include_leave_date_when_change_starts_next_day() -> None:
    """离职日是锁账周期最后一天时，次日才开始的变化区间碰不到该周期。"""
    history = _history(start_date=date(2026, 8, 1))
    employ_changed = leave_employ_touch([history], _SEP_END)
    assert employ_changed == [(date(2026, 10, 1), None)]
    ranges = leave_lock_ranges(employ_changed, [], _SEP_END)
    assert (_SEP_END, _SEP_END) in ranges


def test_leave_advance_hints() -> None:
    assert leave_advance_hints(rejected_count=0, to_pay_count=0, outstanding_amount=Decimal(0)) == []
    hints = leave_advance_hints(
        rejected_count=1,
        to_pay_count=1,
        outstanding_amount=Decimal(80),
    )
    assert hints[0] == '骑手已离职，预支申请已驳回'
    assert '取消待发放' in hints[1]
    assert '80.00' in hints[2]
    assert LEAVE_AUTO_REJECT_REASON == '骑手离职自动驳回'


def test_auto_reject_reason_is_legal_transition() -> None:
    advance = SimpleNamespace(
        status=AdvanceStatus.pending.value,
        approver_id=None,
        approve_time=None,
        approve_remark=None,
        amount=Decimal('20.00'),
    )
    advance_service.transition(advance, AdvanceStatus.rejected.value, SimpleNamespace(id=1), LEAVE_AUTO_REJECT_REASON)
    assert advance.status == AdvanceStatus.rejected.value
    assert advance.approve_remark == LEAVE_AUTO_REJECT_REASON


def test_leave_on_last_day_of_locked_period_rejected() -> None:
    """9 月已锁账，9 月 30 日离职：变化从 10 月 1 日开始，仍因离职日本身落在锁账周期而拒绝。"""
    row = _history(start_date=date(2026, 8, 1))
    rider = SimpleNamespace(
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
    obj = RiderLeaveParam(leave_date=_SEP_END, reason='个人原因')

    async def _case() -> None:
        captured: list[str] = []

        def scalar(stmt: object) -> int | None:
            text = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
            captured.append(text)
            if '2026-09-30' in text:
                return 11
            return None

        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=scalar)
        prefix = 'backend.plugin.rider_salary.service.rider_service.'
        with (
            patch.object(RiderService, '_get_visible_rider', AsyncMock(return_value=rider)),
            patch(f'{prefix}rider_employ_history_dao.get_by_rider', AsyncMock(return_value=[row])),
            patch(f'{prefix}rider_plan_binding_dao.get_by_rider', AsyncMock(return_value=[])),
            patch(f'{prefix}rider_employ_history_dao.close_open', AsyncMock()) as close_open,
            patch(f'{prefix}rider_dao.update', AsyncMock()) as rider_update,
        ):
            with pytest.raises(errors.ForbiddenError, match='反冲') as caught:
                await rider_service.leave(db=db, request=SimpleNamespace(user=SimpleNamespace(id=1)), pk=7, obj=obj)
            assert caught.value.code == 403
            close_open.assert_not_awaited()
            rider_update.assert_not_awaited()
            assert captured

    anyio.run(_case)
