"""P0-07 同一周期可以进行第二轮反冲补发。

P1-03 集成基座（``tests/integration/``）尚未就绪，验收写成服务层单测：
锁账 → 反冲 → 重算 → 锁账 → 反冲 → 重算 → 锁账。
每轮周期净额等于仍有效的补发单；第二轮反冲后、补发草稿出现前，锁账仍按 P0-02 拒绝。
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anyio
import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.crud.payroll import payroll_dao
from backend.plugin.rider_salary.crud.payroll_daily import payroll_daily_dao
from backend.plugin.rider_salary.crud.payroll_detail import payroll_detail_dao
from backend.plugin.rider_salary.enums import PayrollKind, PayrollStatus, PeriodStatus
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.service.calc_service import (
    CalcDetail,
    CalcResult,
    _persist_result,
    _restore_draft_advances,
)
from backend.plugin.rider_salary.service.payroll_service import payroll_service
from backend.plugin.rider_salary.service.period_service import (
    active_supplement_net_total,
    classify_lock_gaps,
    current_payroll_kind,
    latest_reversed_originals,
    lock_block_message,
    missing_supplement_rider_ids,
    period_net_total,
    period_service,
)

RIDER_ID = 7
PERIOD_ID = 9
ZERO = Decimal('0.00')


class _Ledger:
    """内存薪资单账本，代替数据库会话"""

    def __init__(self) -> None:
        self.payrolls: list[RiderSalaryPayroll] = []
        self.pending: list[object] = []
        self._next_id = 1

    def add(self, obj: object) -> None:
        self.pending.append(obj)

    def add_all(self, objs: list[object]) -> None:
        self.pending.extend(objs)

    async def flush(self) -> None:
        for obj in self.pending:
            if not isinstance(obj, RiderSalaryPayroll):
                continue
            if getattr(obj, 'id', None) is None:
                obj.id = self._next_id
                self._next_id += 1
            if obj not in self.payrolls:
                self.payrolls.append(obj)
        self.pending.clear()

    async def scalar(self, _stmt: object) -> None:
        return None

    async def execute(self, _stmt: object) -> SimpleNamespace:
        # 反冲抢占要求恰好更新 1 行；内存账本不跑 SQL，成功路径按已抢到返回。
        return SimpleNamespace(rowcount=1)


def _period() -> SimpleNamespace:
    return SimpleNamespace(
        id=PERIOD_ID,
        site_id=1,
        rider_id=0,
        cycle_type='month',
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
        status=PeriodStatus.open.value,
        remark=None,
    )


def _rider() -> SimpleNamespace:
    return SimpleNamespace(id=RIDER_ID, job_no='R007', name='丙')


def _request() -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(id=1, username='admin', nickname='管理员'))


def _site() -> SimpleNamespace:
    return SimpleNamespace(id=1, name='测试站', code='S1')


def _result(net: str) -> CalcResult:
    amount = Decimal(net)
    return CalcResult(
        rider_id=RIDER_ID,
        period_id=PERIOD_ID,
        payroll_id=None,
        order_count=2,
        valid_order_count=2,
        per_order_total=amount,
        daily_total=ZERO,
        period_total=ZERO,
        bonus_total=ZERO,
        penalty_total=ZERO,
        gross=amount,
        deduction_total=ZERO,
        advance_deduction=ZERO,
        advance_deductible=ZERO,
        net=amount,
        plan_version_ids=[],
        warnings=[],
        details=[
            CalcDetail(
                rider_id=RIDER_ID,
                subject_id=1,
                amount=amount,
                stage='per_order',
                include_in_gross=True,
                source='formula',
            )
        ],
        dailies=[],
    )


def _alive(row: RiderSalaryPayroll) -> bool:
    return int(getattr(row, 'deleted', 0) or 0) == 0


def _lock_message(ledger: _Ledger, period: SimpleNamespace) -> str | None:
    drafts = [row for row in ledger.payrolls if _alive(row) and row.status == PayrollStatus.draft.value]
    uncalculated, needs_recalc = classify_lock_gaps(
        [RIDER_ID],
        drafts,
        kind=current_payroll_kind(period.status),
    )
    missing: list[int] = []
    if period.status == PeriodStatus.reopened.value:
        missing = missing_supplement_rider_ids(ledger.payrolls, drafts)
        covered = set(missing)
        uncalculated = [rider_id for rider_id in uncalculated if rider_id not in covered]
    rider_map = {RIDER_ID: _rider()}
    return lock_block_message(
        uncalculated_job_nos=[rider_map[rider_id].job_no for rider_id in uncalculated],
        recalc_job_nos=[rider_map[rider_id].job_no for rider_id in needs_recalc],
        missing_supplement_job_nos=[rider_map[rider_id].job_no for rider_id in missing],
    )


def _finalize_drafts(ledger: _Ledger, period: SimpleNamespace) -> None:
    period.status = PeriodStatus.locked.value
    for row in ledger.payrolls:
        if _alive(row) and row.status == PayrollStatus.draft.value:
            row.status = PayrollStatus.finalized.value


def test_second_reversal_then_recalc_keeps_round_net() -> None:
    """两轮反冲补发后都能重算，周期净额等于当轮有效补发单。"""
    ledger = _Ledger()
    period = _period()
    rider = _rider()
    restored: list[int] = []

    def _get_draft(_db: object, period_id: int, rider_id: int, kind: str) -> RiderSalaryPayroll | None:
        rows = [
            row
            for row in ledger.payrolls
            if _alive(row)
            and row.period_id == period_id
            and row.rider_id == rider_id
            and row.kind == kind
            and row.status == PayrollStatus.draft.value
        ]
        if not rows:
            return None
        return max(rows, key=lambda row: int(row.id))

    def _get_current(_db: object, period_id: int, rider_id: int, kind: str) -> RiderSalaryPayroll | None:
        rows = [
            row
            for row in ledger.payrolls
            if _alive(row)
            and row.period_id == period_id
            and row.rider_id == rider_id
            and row.kind == kind
            and row.status != PayrollStatus.voided.value
        ]
        if not rows:
            return None
        return max(rows, key=lambda row: int(row.id))

    def _select_models(_db: object, *, period_id: int, deleted: int = 0) -> list[RiderSalaryPayroll]:
        return [
            row
            for row in ledger.payrolls
            if row.period_id == period_id and int(getattr(row, 'deleted', 0) or 0) == deleted
        ]

    def _restore(_db: object, payroll: RiderSalaryPayroll) -> None:
        restored.append(int(payroll.id))

    async def _case() -> None:
        with (
            patch.object(payroll_dao, 'get_draft', AsyncMock(side_effect=_get_draft)),
            patch.object(payroll_dao, 'get_current', AsyncMock(side_effect=_get_current)),
            patch.object(payroll_dao, 'select_models', AsyncMock(side_effect=_select_models)),
            patch.object(payroll_detail_dao, 'logical_delete_by_payroll', AsyncMock()),
            patch.object(payroll_detail_dao, 'list_by_payroll', AsyncMock(return_value=[])),
            patch.object(payroll_daily_dao, 'get_one', AsyncMock(return_value=None)),
            patch.object(payroll_service, 'restore_advances_from_payroll', AsyncMock(side_effect=_restore)),
            patch.object(period_service, '_load_visible', AsyncMock(return_value=(period, _site(), None))),
            patch.object(period_service, 'set_locked_flags', AsyncMock()),
            patch(
                'backend.plugin.rider_salary.service.period_service.audit_service.record',
                AsyncMock(),
            ),
            patch(
                'backend.plugin.rider_salary.service.payroll_service.audit_service.record',
                AsyncMock(),
            ),
        ):
            first = await _persist_result(ledger, rider=rider, period=period, result=_result('100.00'), operator=None)
            normal_id = int(first.payroll_id)
            assert period_net_total(ledger.payrolls) == Decimal('100.00')
            assert _lock_message(ledger, period) is None

            _finalize_drafts(ledger, period)
            assert period_net_total(ledger.payrolls) == Decimal('100.00')
            with pytest.raises(errors.RequestError, match='已定稿结果不可重算，请走反冲补发'):
                await _persist_result(ledger, rider=rider, period=period, result=_result('100.00'), operator=None)
            assert len(ledger.payrolls) == 1

            first_reverse = await period_service.reverse(db=ledger, request=_request(), pk=PERIOD_ID, reason='金额有误')
            assert period.status == PeriodStatus.reopened.value
            assert first_reverse.reversal_count == 1
            assert first_reverse.reversal_net_total == Decimal('-100.00')
            assert period_net_total(ledger.payrolls) == ZERO
            blocked = _lock_message(ledger, period)
            assert blocked is not None
            assert '存在缺补发单的骑手：工号 R007' in blocked
            assert '未算薪' not in blocked

            restored.clear()
            await _restore_draft_advances(ledger, rider_id=RIDER_ID, period=period)
            assert restored == []

            supplement = await _persist_result(
                ledger, rider=rider, period=period, result=_result('80.00'), operator=None
            )
            supplement_id = int(supplement.payroll_id)
            assert supplement_id != normal_id
            assert period_net_total(ledger.payrolls) == Decimal('80.00')
            assert active_supplement_net_total(ledger.payrolls) == Decimal('80.00')
            assert _lock_message(ledger, period) is None

            restored.clear()
            await _restore_draft_advances(ledger, rider_id=RIDER_ID, period=period)
            assert restored == [supplement_id]
            rewritten = await _persist_result(
                ledger, rider=rider, period=period, result=_result('80.00'), operator=None
            )
            assert int(rewritten.payroll_id) == supplement_id
            assert sum(1 for row in ledger.payrolls if row.kind == PayrollKind.supplement.value) == 1

            _finalize_drafts(ledger, period)
            assert period_net_total(ledger.payrolls) == Decimal('80.00')

            second_reverse = await period_service.reverse(
                db=ledger, request=_request(), pk=PERIOD_ID, reason='第二轮纠错'
            )
            assert period.status == PeriodStatus.reopened.value
            assert second_reverse.reversal_count == 1
            assert second_reverse.reversal_net_total == Decimal('-80.00')
            assert period_net_total(ledger.payrolls) == ZERO
            blocked_again = _lock_message(ledger, period)
            assert blocked_again is not None
            assert '存在缺补发单的骑手：工号 R007' in blocked_again
            originals = latest_reversed_originals(ledger.payrolls)
            assert int(originals[RIDER_ID].id) == supplement_id
            assert originals[RIDER_ID].net == Decimal('80.00')

            restored.clear()
            await _restore_draft_advances(ledger, rider_id=RIDER_ID, period=period)
            assert restored == []

            second_supplement = await _persist_result(
                ledger, rider=rider, period=period, result=_result('60.00'), operator=None
            )
            second_id = int(second_supplement.payroll_id)
            assert second_id not in {normal_id, supplement_id}
            assert period_net_total(ledger.payrolls) == Decimal('60.00')
            assert active_supplement_net_total(ledger.payrolls) == Decimal('60.00')
            assert _lock_message(ledger, period) is None

            restored.clear()
            await _restore_draft_advances(ledger, rider_id=RIDER_ID, period=period)
            assert restored == [second_id]
            adjusted = await _persist_result(ledger, rider=rider, period=period, result=_result('55.00'), operator=None)
            assert int(adjusted.payroll_id) == second_id
            assert period_net_total(ledger.payrolls) == Decimal('55.00')

            _finalize_drafts(ledger, period)
            assert period.status == PeriodStatus.locked.value
            assert period_net_total(ledger.payrolls) == Decimal('55.00')
            assert active_supplement_net_total(ledger.payrolls) == Decimal('55.00')
            with pytest.raises(errors.RequestError, match='已定稿结果不可重算，请走反冲补发'):
                await _persist_result(ledger, rider=rider, period=period, result=_result('55.00'), operator=None)
            reversals = [row for row in ledger.payrolls if row.kind == PayrollKind.reversal.value]
            assert {int(row.reversed_of_id) for row in reversals} == {normal_id, supplement_id}

    anyio.run(_case)


def test_unreversed_supplement_still_refuses_recalc() -> None:
    """补发中若补发单尚未反冲，重算仍拒绝，不能另开一张。"""
    ledger = _Ledger()
    period = _period()
    period.status = PeriodStatus.reopened.value
    rider = _rider()
    finalized = RiderSalaryPayroll(
        period_id=PERIOD_ID,
        rider_id=RIDER_ID,
        kind=PayrollKind.supplement.value,
        status=PayrollStatus.finalized.value,
        reversed=False,
        net=Decimal('80.00'),
        gross=Decimal('80.00'),
    )
    finalized.id = 3
    ledger.payrolls.append(finalized)

    def _get_draft(*_args: object, **_kwargs: object) -> None:
        return None

    def _get_current(*_args: object, **_kwargs: object) -> RiderSalaryPayroll:
        return finalized

    async def _case() -> None:
        with (
            patch.object(payroll_dao, 'get_draft', AsyncMock(side_effect=_get_draft)),
            patch.object(payroll_dao, 'get_current', AsyncMock(side_effect=_get_current)),
        ):
            with pytest.raises(errors.RequestError, match='已定稿结果不可重算，请走反冲补发'):
                await _persist_result(ledger, rider=rider, period=period, result=_result('70.00'), operator=None)
        assert ledger.payrolls == [finalized]

    anyio.run(_case)
