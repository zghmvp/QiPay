"""P0-01 锁账前校验「应算未算」。

验收用例目前写成纯函数和服务层单测。P1-03 集成基座就绪后，迁到
``backend/plugin/rider_salary/tests/integration/``，改成走 API 的周期场景
（E2：有订单无薪资单锁账 400；全员算完后锁账成功；回退作废草稿后锁账 400）。
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import PayrollKind, PayrollStatus, PeriodStatus
from backend.plugin.rider_salary.service.period_service import (
    EMPTY_PERIOD_MARK_PAID_HINT,
    classify_lock_gaps,
    current_payroll_kind,
    period_service,
    uncalculated_lock_message,
)


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


def _rider(rider_id: int, job_no: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(id=rider_id, job_no=job_no, name=name)


def _draft(
    rider_id: int,
    *,
    kind: str = PayrollKind.normal.value,
    stale: bool = False,
    status: str = PayrollStatus.draft.value,
    deleted: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(rider_id=rider_id, kind=kind, stale=stale, status=status, deleted=deleted)


def _scalars_then_empty(results: list[MagicMock]) -> AsyncMock:
    """预置批次用完后补空结果。锁账还会再查求值失败草稿，假会话不能在这里停住。"""
    pending = list(results)

    def _next(*_args: object, **_kwargs: object) -> MagicMock:
        if pending:
            return pending.pop(0)
        empty = MagicMock()
        empty.all.return_value = []
        return empty

    return AsyncMock(side_effect=_next)


def _db(
    *,
    drafts: list[SimpleNamespace],
    riders: list[SimpleNamespace] | None = None,
    finalized_count: int = 0,
    payrolls: list[SimpleNamespace] | None = None,
) -> AsyncMock:
    """补发中的锁账会在草稿之后再查一遍周期内全部薪资单。传入 payrolls 才插入这次结果。"""
    results: list[MagicMock] = []
    draft_result = MagicMock()
    draft_result.all.return_value = drafts
    results.append(draft_result)
    if payrolls is not None:
        payroll_result = MagicMock()
        payroll_result.all.return_value = payrolls
        results.append(payroll_result)
    rider_result = MagicMock()
    rider_result.all.return_value = riders or []
    results.append(rider_result)
    db = AsyncMock()
    db.scalars = _scalars_then_empty(results)
    db.scalar = AsyncMock(return_value=finalized_count)
    return db


def test_uncalculated_message_lists_job_nos() -> None:
    assert uncalculated_lock_message(['R002']) == '存在未算薪骑手：工号 R002，请先算薪'
    assert uncalculated_lock_message(['R002', 'R003']) == '存在未算薪骑手：工号 R002、R003，请先算薪'


def test_current_kind_is_supplement_only_when_reopened() -> None:
    assert current_payroll_kind(PeriodStatus.open.value) == PayrollKind.normal.value
    assert current_payroll_kind(PeriodStatus.reopened.value) == PayrollKind.supplement.value


def test_e2_missing_draft_is_uncalculated() -> None:
    """R001 已有非 stale 草稿，R002 有订单但没有薪资单。"""
    uncalculated, needs_recalc = classify_lock_gaps(
        [1, 2],
        [_draft(1)],
        kind=PayrollKind.normal.value,
    )
    assert uncalculated == [2]
    assert needs_recalc == []


def test_all_fresh_drafts_have_no_gap() -> None:
    uncalculated, needs_recalc = classify_lock_gaps(
        [1, 2],
        [_draft(1), _draft(2)],
        kind=PayrollKind.normal.value,
    )
    assert uncalculated == []
    assert needs_recalc == []


def test_voided_draft_after_rollback_counts_as_uncalculated() -> None:
    uncalculated, needs_recalc = classify_lock_gaps(
        [2],
        [_draft(2, status=PayrollStatus.voided.value)],
        kind=PayrollKind.normal.value,
    )
    assert uncalculated == [2]
    assert needs_recalc == []


def test_stale_draft_is_needs_recalc_not_uncalculated() -> None:
    uncalculated, needs_recalc = classify_lock_gaps(
        [1],
        [_draft(1, stale=True)],
        kind=PayrollKind.normal.value,
    )
    assert uncalculated == []
    assert needs_recalc == [1]


def test_empty_expected_set_is_lockable() -> None:
    uncalculated, needs_recalc = classify_lock_gaps([], [], kind=PayrollKind.normal.value)
    assert uncalculated == []
    assert needs_recalc == []


def test_wrong_kind_draft_does_not_count() -> None:
    uncalculated, _needs_recalc = classify_lock_gaps(
        [1],
        [_draft(1, kind=PayrollKind.normal.value)],
        kind=PayrollKind.supplement.value,
    )
    assert uncalculated == [1]


def test_stale_draft_outside_expected_set_still_blocks() -> None:
    uncalculated, needs_recalc = classify_lock_gaps(
        [1],
        [_draft(1), _draft(9, stale=True)],
        kind=PayrollKind.normal.value,
    )
    assert uncalculated == []
    assert needs_recalc == [9]


def test_lock_rejects_e2_and_lists_r002() -> None:
    period = _period()
    db = _db(drafts=[_draft(1)], riders=[_rider(1, 'R001', '甲'), _rider(2, 'R002', '乙')])

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(return_value=[1, 2]),
            ),
            patch.object(period_service, 'set_locked_flags', AsyncMock()) as flags,
        ):
            with pytest.raises(errors.RequestError, match='存在未算薪骑手：工号 R002，请先算薪') as caught:
                await period_service.lock(db=db, request=_request(), pk=9, reason='核对完成')
            assert 'R001' not in (caught.value.msg or '')
            flags.assert_not_awaited()
        assert period.status == PeriodStatus.open.value

    anyio.run(_case)


def test_lock_succeeds_when_everyone_has_fresh_draft() -> None:
    period = _period()
    db = _db(drafts=[_draft(1), _draft(2)], riders=[])

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(return_value=[1, 2]),
            ),
            patch.object(period_service, 'set_locked_flags', AsyncMock()) as flags,
            patch.object(period_service, '_mark_plan_versions_used', AsyncMock()),
            patch(
                'backend.plugin.rider_salary.service.period_service.audit_service.record',
                AsyncMock(),
            ) as audit,
        ):
            await period_service.lock(db=db, request=_request(), pk=9, reason='核对完成')
            flags.assert_awaited_once()
            assert flags.await_args.kwargs['locked'] is True
            assert audit.await_args.kwargs['action'] == '锁账'
        assert period.status == PeriodStatus.locked.value

    anyio.run(_case)


def test_lock_rejects_after_rollback_voids_draft() -> None:
    """回退把草稿作废后，查询只剩空草稿列表，锁账应列出工号。"""
    period = _period()
    db = _db(drafts=[], riders=[_rider(2, 'R002', '乙')])

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(return_value=[2]),
            ),
        ):
            with pytest.raises(errors.RequestError, match='存在未算薪骑手：工号 R002，请先算薪'):
                await period_service.lock(db=db, request=_request(), pk=9, reason='核对完成')
        assert period.status == PeriodStatus.open.value

    anyio.run(_case)


def test_lock_allows_empty_period() -> None:
    period = _period()
    db = _db(drafts=[])

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(return_value=[]),
            ),
            patch.object(period_service, 'set_locked_flags', AsyncMock()),
            patch.object(period_service, '_mark_plan_versions_used', AsyncMock()),
            patch(
                'backend.plugin.rider_salary.service.period_service.audit_service.record',
                AsyncMock(),
            ),
        ):
            await period_service.lock(db=db, request=_request(), pk=9, reason='核对完成')
        assert period.status == PeriodStatus.locked.value

    anyio.run(_case)


def test_lock_still_rejects_stale_with_original_message() -> None:
    period = _period()
    db = _db(drafts=[_draft(1, stale=True)], riders=[_rider(1, 'R001', '甲')])

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(return_value=[1]),
            ),
        ):
            with pytest.raises(errors.RequestError, match='存在需重算的薪资结果：工号 R001，请先重算') as caught:
                await period_service.lock(db=db, request=_request(), pk=9, reason='核对完成')
            assert '未算薪' not in (caught.value.msg or '')
        assert period.status == PeriodStatus.open.value

    anyio.run(_case)


def test_lock_on_paid_period_keeps_status_error() -> None:
    period = _period(status=PeriodStatus.paid.value)
    db = _db(drafts=[])

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(side_effect=AssertionError('已发薪周期不应计算应算集合')),
            ),
        ):
            with pytest.raises(errors.RequestError, match='不允许执行锁账'):
                await period_service.lock(db=db, request=_request(), pk=9, reason='核对完成')
        db.scalars.assert_not_called()

    anyio.run(_case)


def test_lock_check_lists_uncalculated_and_needs_recalc() -> None:
    period = _period()
    db = _db(
        drafts=[_draft(1), _draft(2, stale=True)],
        riders=[_rider(2, 'R002', '乙'), _rider(3, 'R003', '丙')],
    )

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(return_value=[1, 2, 3]),
            ),
        ):
            result = await period_service.lock_check(db=db, request=_request(), pk=9)
        assert result.can_lock is False
        assert result.empty is False
        assert [(item.job_no, item.rider_name) for item in result.uncalculated] == [('R003', '丙')]
        assert [(item.job_no, item.rider_name) for item in result.needs_recalc] == [('R002', '乙')]
        assert result.message == ('存在未算薪骑手：工号 R003，请先算薪；存在需重算的薪资结果：工号 R002，请先重算')

    anyio.run(_case)


def test_lock_check_empty_period_can_lock() -> None:
    period = _period()
    db = _db(drafts=[])

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(return_value=[]),
            ),
        ):
            result = await period_service.lock_check(db=db, request=_request(), pk=9)
        assert result.can_lock is True
        assert result.empty is True
        assert result.uncalculated == []
        assert result.needs_recalc == []
        assert result.message is None

    anyio.run(_case)


def test_reopened_without_supplement_draft_is_uncalculated() -> None:
    period = _period(status=PeriodStatus.reopened.value)
    db = _db(
        drafts=[_draft(1, kind=PayrollKind.normal.value)],
        riders=[_rider(1, 'R002', '乙')],
        payrolls=[],
    )

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.riders_for_period',
                AsyncMock(return_value=[1]),
            ),
        ):
            with pytest.raises(errors.RequestError, match='存在未算薪骑手：工号 R002，请先算薪'):
                await period_service.lock(db=db, request=_request(), pk=9, reason='核对完成')

    anyio.run(_case)


def test_mark_paid_empty_period_warns() -> None:
    period = _period(status=PeriodStatus.locked.value)
    db = _db(drafts=[], finalized_count=0)

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.audit_service.record',
                AsyncMock(),
            ) as audit,
        ):
            result = await period_service.mark_paid(db=db, request=_request(), pk=9, reason=None)
        assert result.warning == EMPTY_PERIOD_MARK_PAID_HINT
        assert result.warning == '本期没有薪资单'
        assert '本期没有薪资单' in audit.await_args.kwargs['description']
        assert period.status == PeriodStatus.paid.value

    anyio.run(_case)


def test_mark_paid_with_finalized_payrolls_has_no_warning() -> None:
    period = _period(status=PeriodStatus.locked.value)
    db = _db(drafts=[], finalized_count=2)

    async def _case() -> None:
        with (
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch(
                'backend.plugin.rider_salary.service.period_service.audit_service.record',
                AsyncMock(),
            ) as audit,
        ):
            result = await period_service.mark_paid(db=db, request=_request(), pk=9, reason=None)
        assert result.warning is None
        assert '本期没有薪资单' not in audit.await_args.kwargs['description']

    anyio.run(_case)
