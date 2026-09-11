from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import AdvanceStatus, DeductStatus
from backend.plugin.rider_salary.service.advance_service import (
    advance_service,
    assert_advance_amount,
    assert_no_in_flight,
    resolve_advance_limit,
)


def _advance(*, status: str, amount: Decimal = Decimal('800.00')) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        amount=amount,
        approver_id=None,
        approve_time=None,
        approve_remark=None,
        paid_by=None,
        paid_time=None,
        deducted_amount=Decimal('0.00'),
        remaining_amount=None,
        deduct_status=DeductStatus.none.value,
        submit_time=None,
        cancel_time=None,
    )


def test_legal_pending_to_pay() -> None:
    adv = _advance(status=AdvanceStatus.pending.value)
    advance_service.transition(adv, AdvanceStatus.to_pay.value, SimpleNamespace(id=2), 'ok')
    assert adv.status == AdvanceStatus.to_pay.value
    assert adv.approver_id == 2
    assert adv.approve_time is not None


def test_legal_pending_reject_requires_reason() -> None:
    adv = _advance(status=AdvanceStatus.pending.value)
    with pytest.raises(errors.RequestError, match='请填写操作原因'):
        advance_service.transition(adv, AdvanceStatus.rejected.value, SimpleNamespace(id=2), None)
    advance_service.transition(adv, AdvanceStatus.rejected.value, SimpleNamespace(id=2), '资料不全')
    assert adv.status == AdvanceStatus.rejected.value


def test_legal_pending_cancel() -> None:
    adv = _advance(status=AdvanceStatus.pending.value)
    advance_service.transition(adv, AdvanceStatus.cancelled.value, SimpleNamespace(id=3), '骑手撤回')
    assert adv.status == AdvanceStatus.cancelled.value
    assert adv.cancel_time is not None


def test_legal_to_pay_mark_paid_writes_remaining() -> None:
    adv = _advance(status=AdvanceStatus.to_pay.value, amount=Decimal('800.00'))
    advance_service.transition(adv, AdvanceStatus.paid.value, SimpleNamespace(id=9), None)
    assert adv.status == AdvanceStatus.paid.value
    assert adv.paid_by == 9
    assert adv.paid_time is not None
    assert adv.remaining_amount == Decimal('800.00')
    assert adv.deducted_amount == Decimal('0.00')
    assert adv.deduct_status == DeductStatus.none.value


def test_legal_to_pay_cancel() -> None:
    adv = _advance(status=AdvanceStatus.to_pay.value)
    advance_service.transition(adv, AdvanceStatus.cancelled.value, SimpleNamespace(id=1), '线下取消')
    assert adv.status == AdvanceStatus.cancelled.value


def test_legal_draft_submit() -> None:
    adv = _advance(status=AdvanceStatus.draft.value)
    advance_service.transition(adv, AdvanceStatus.pending.value, SimpleNamespace(id=1), None)
    assert adv.status == AdvanceStatus.pending.value
    assert adv.submit_time is not None


def test_illegal_pending_mark_paid() -> None:
    adv = _advance(status=AdvanceStatus.pending.value)
    with pytest.raises(errors.RequestError, match='预支单当前状态为 待审核，不允许执行 标记已发放'):
        advance_service.transition(adv, AdvanceStatus.paid.value, SimpleNamespace(id=1), None)


def test_illegal_to_pay_approve() -> None:
    adv = _advance(status=AdvanceStatus.to_pay.value)
    with pytest.raises(errors.RequestError, match='不允许执行 审核通过'):
        advance_service.transition(adv, AdvanceStatus.to_pay.value, SimpleNamespace(id=1), None)


def test_illegal_paid_cancel() -> None:
    adv = _advance(status=AdvanceStatus.paid.value)
    with pytest.raises(errors.RequestError, match='不允许执行 取消'):
        advance_service.transition(adv, AdvanceStatus.cancelled.value, SimpleNamespace(id=1), 'x')


def test_illegal_rejected_approve() -> None:
    adv = _advance(status=AdvanceStatus.rejected.value)
    with pytest.raises(errors.RequestError, match='不允许执行'):
        advance_service.transition(adv, AdvanceStatus.to_pay.value, SimpleNamespace(id=1), None)


def test_in_flight_unique() -> None:
    assert_no_in_flight(0)
    with pytest.raises(errors.RequestError, match='您已有一笔待审核或待发放的预支，请等待处理完成后再申请'):
        assert_no_in_flight(1)


def test_limit_rider_over_site_over_global() -> None:
    assert resolve_advance_limit(Decimal(100), Decimal(200), 3000) == Decimal('100.00')
    assert resolve_advance_limit(None, Decimal(200), 3000) == Decimal('200.00')
    assert resolve_advance_limit(None, None, 3000) == Decimal('3000.00')


def test_amount_over_limit() -> None:
    with pytest.raises(errors.RequestError, match=r'预支金额不能超过上限 3000\.00 元'):
        assert_advance_amount(Decimal('3000.01'), Decimal(3000))
    assert assert_advance_amount(Decimal(3000), Decimal(3000)) == Decimal('3000.00')
    with pytest.raises(errors.RequestError, match='预支金额必须大于 0'):
        assert_advance_amount(Decimal(0), Decimal(3000))
