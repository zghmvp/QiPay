"""P5-11：状态迁移接受 expected_status，不符或重复提交时返回 409，不写第二条审计。"""

from contextlib import ExitStack
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import AdvanceStatus, PeriodStatus
from backend.plugin.rider_salary.schema.advance import AdvanceActionParam, AdvanceReasonParam
from backend.plugin.rider_salary.service.advance_service import STATUS_CHANGED_MSG, advance_service
from backend.plugin.rider_salary.service.payroll_service import payroll_service
from backend.plugin.rider_salary.service.period_service import PERIOD_STATUS_CHANGED_MSG, period_service


def _period(**kwargs: object) -> SimpleNamespace:
    data: dict[str, object] = {
        'id': 9,
        'site_id': 1,
        'rider_id': 0,
        'cycle_type': 'month',
        'start_date': date(2026, 9, 1),
        'end_date': date(2026, 9, 30),
        'status': PeriodStatus.open.value,
        'remark': None,
        'locked_by': None,
        'locked_time': None,
        'paid_by': None,
        'paid_time': None,
        'reopened_by': None,
        'reopened_time': None,
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def _site() -> SimpleNamespace:
    return SimpleNamespace(id=1, name='测试站', code='S1')


def _request() -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(id=1, username='admin', nickname='管理员'))


def _db() -> AsyncMock:
    draft_result = MagicMock()
    draft_result.all.return_value = []
    rider_result = MagicMock()
    rider_result.all.return_value = []
    pending = [draft_result, rider_result]

    def _next(*_args: object, **_kwargs: object) -> MagicMock:
        if pending:
            return pending.pop(0)
        empty = MagicMock()
        empty.all.return_value = []
        return empty

    db = AsyncMock()
    db.scalars = AsyncMock(side_effect=_next)
    db.scalar = AsyncMock(return_value=0)
    return db


def _lock_patches(period: SimpleNamespace, audit: AsyncMock) -> tuple[object, ...]:
    return (
        patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
        patch(
            'backend.plugin.rider_salary.service.period_service.is_period_calculating',
            AsyncMock(return_value=False),
        ),
        patch(
            'backend.plugin.rider_salary.service.period_service.read_period_calc_warnings',
            AsyncMock(return_value=[]),
        ),
        patch(
            'backend.plugin.rider_salary.service.period_service.riders_for_period',
            AsyncMock(return_value=[]),
        ),
        patch.object(period_service, 'set_locked_flags', AsyncMock()),
        patch.object(period_service, '_mark_plan_versions_used', AsyncMock()),
        patch('backend.plugin.rider_salary.service.period_service.audit_service.record', audit),
    )


def test_second_lock_returns_409_without_second_audit() -> None:
    """第一次锁账成功；同一期望状态或不再带期望状态的重复提交都是 409，审计只写一次。"""
    period = _period()
    db = _db()
    audit = AsyncMock()

    async def _case() -> None:
        with ExitStack() as stack:
            for item in _lock_patches(period, audit):
                stack.enter_context(item)
            await period_service.lock(db=db, request=_request(), pk=9, reason='第一次锁账', expected_status='open')
            assert audit.await_count == 1
            with pytest.raises(errors.ConflictError, match=PERIOD_STATUS_CHANGED_MSG) as caught:
                await period_service.lock(db=db, request=_request(), pk=9, reason='重复锁账', expected_status='open')
            assert caught.value.code == 409
            with pytest.raises(errors.ConflictError, match=PERIOD_STATUS_CHANGED_MSG):
                await period_service.lock(db=db, request=_request(), pk=9, reason='再点一次')
            assert audit.await_count == 1
        assert period.status == PeriodStatus.locked.value

    anyio.run(_case)


def test_lock_expected_status_mismatch_skips_readiness_and_audit() -> None:
    period = _period(status=PeriodStatus.paid.value)
    audit = AsyncMock()
    readiness = AsyncMock(side_effect=AssertionError('状态不符时不应做锁账预检'))

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.is_period_calculating',
                AsyncMock(return_value=False),
            ),
            patch.object(period_service, '_assert_lock_ready', readiness),
            patch('backend.plugin.rider_salary.service.period_service.audit_service.record', audit),
        ):
            with pytest.raises(errors.ConflictError, match=PERIOD_STATUS_CHANGED_MSG) as caught:
                await period_service.lock(
                    db=AsyncMock(),
                    request=_request(),
                    pk=9,
                    reason='过期的开放状态',
                    expected_status='open',
                )
            assert caught.value.code == 409
        readiness.assert_not_awaited()
        audit.assert_not_awaited()
        assert period.status == PeriodStatus.paid.value

    anyio.run(_case)


def test_lock_on_paid_period_stays_400() -> None:
    """期望状态与已发薪一致时，锁账仍是原来的 400，不是 409。"""
    period = _period(status=PeriodStatus.paid.value)

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.is_period_calculating',
                AsyncMock(return_value=False),
            ),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(side_effect=AssertionError('已发薪周期不应计算应算集合')),
            ),
        ):
            with pytest.raises(errors.RequestError, match='不允许执行锁账'):
                await period_service.lock(
                    db=AsyncMock(),
                    request=_request(),
                    pk=9,
                    reason='核对完成',
                    expected_status=PeriodStatus.paid.value,
                )

    anyio.run(_case)


def test_second_mark_paid_returns_409_without_audit() -> None:
    period = _period(status=PeriodStatus.paid.value)
    audit = AsyncMock()

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch('backend.plugin.rider_salary.service.period_service.audit_service.record', audit),
        ):
            with pytest.raises(errors.ConflictError, match=PERIOD_STATUS_CHANGED_MSG) as caught:
                await period_service.mark_paid(db=AsyncMock(), request=_request(), pk=9, reason='再标一次')
            assert caught.value.code == 409
            with pytest.raises(errors.ConflictError, match=PERIOD_STATUS_CHANGED_MSG):
                await period_service.mark_paid(
                    db=AsyncMock(),
                    request=_request(),
                    pk=9,
                    reason=None,
                    expected_status=PeriodStatus.locked.value,
                )
        audit.assert_not_awaited()
        assert period.status == PeriodStatus.paid.value

    anyio.run(_case)


def test_reverse_expected_status_mismatch_does_not_create_reversal() -> None:
    period = _period(status=PeriodStatus.reopened.value)
    audit = AsyncMock()
    select_models = AsyncMock(side_effect=AssertionError('不应查询薪资单'))
    create_reversal = AsyncMock(side_effect=AssertionError('不应生成反冲单'))

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch('backend.plugin.rider_salary.service.period_service.payroll_dao.select_models', select_models),
            patch.object(payroll_service, 'create_reversal', create_reversal),
            patch('backend.plugin.rider_salary.service.period_service.audit_service.record', audit),
        ):
            with pytest.raises(errors.ConflictError, match=PERIOD_STATUS_CHANGED_MSG) as caught:
                await period_service.reverse(
                    db=AsyncMock(),
                    request=_request(),
                    pk=9,
                    reason='过期的锁账状态',
                    expected_status=PeriodStatus.locked.value,
                )
            assert caught.value.code == 409
        select_models.assert_not_awaited()
        create_reversal.assert_not_awaited()
        audit.assert_not_awaited()
        assert period.status == PeriodStatus.reopened.value

    anyio.run(_case)


def test_repeat_reverse_without_expected_status_stays_400() -> None:
    """不带期望状态时，补发中再次反冲仍是 400，且不会去生成反冲单。"""
    period = _period(status=PeriodStatus.reopened.value)
    select_models = AsyncMock(side_effect=AssertionError('不应查询薪资单'))

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch('backend.plugin.rider_salary.service.period_service.payroll_dao.select_models', select_models),
            patch.object(
                payroll_service,
                'create_reversal',
                AsyncMock(side_effect=AssertionError('不应生成反冲单')),
            ),
        ):
            with pytest.raises(errors.RequestError, match='不允许执行反冲补发'):
                await period_service.reverse(db=AsyncMock(), request=_request(), pk=9, reason='再反冲一次')
        select_models.assert_not_awaited()

    anyio.run(_case)


def test_approve_expected_status_mismatch_skips_transition_and_audit() -> None:
    advance = SimpleNamespace(id=3, status=AdvanceStatus.to_pay.value, rider_id=1, site_id=1)
    transition = AsyncMock(side_effect=AssertionError('不应迁移'))
    audit = AsyncMock(side_effect=AssertionError('不应审计'))

    async def _case() -> None:
        with (
            patch.object(advance_service, '_load_writable', AsyncMock(return_value=advance)),
            patch.object(advance_service, 'transition_if_status', transition),
            patch.object(advance_service, '_audit', audit),
        ):
            with pytest.raises(errors.ConflictError, match=STATUS_CHANGED_MSG) as caught:
                await advance_service.approve(
                    db=AsyncMock(),
                    request=_request(),
                    pk=3,
                    obj=AdvanceActionParam(remark='同意', expected_status=AdvanceStatus.pending.value),
                )
            assert caught.value.code == 409
        transition.assert_not_awaited()
        audit.assert_not_awaited()
        assert advance.status == AdvanceStatus.to_pay.value

    anyio.run(_case)


def test_reject_expected_status_mismatch_skips_audit() -> None:
    advance = SimpleNamespace(id=4, status=AdvanceStatus.rejected.value, rider_id=1, site_id=1)
    audit = AsyncMock()

    async def _case() -> None:
        with (
            patch.object(advance_service, '_load_writable', AsyncMock(return_value=advance)),
            patch.object(advance_service, '_audit', audit),
        ):
            with pytest.raises(errors.ConflictError, match=STATUS_CHANGED_MSG) as caught:
                await advance_service.reject(
                    db=AsyncMock(),
                    request=_request(),
                    pk=4,
                    obj=AdvanceReasonParam(reason='资料不全', expected_status=AdvanceStatus.pending.value),
                )
            assert caught.value.code == 409
        audit.assert_not_awaited()

    anyio.run(_case)


def test_blank_expected_status_does_not_block_legal_lock() -> None:
    period = _period()
    db = _db()

    async def _case() -> None:
        with ExitStack() as stack:
            for item in _lock_patches(period, AsyncMock()):
                stack.enter_context(item)
            await period_service.lock(db=db, request=_request(), pk=9, reason='空白期望', expected_status='  ')
        assert period.status == PeriodStatus.locked.value

    anyio.run(_case)
