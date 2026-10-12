"""P0-15：预支额度计入已发放未抵扣，骑手只能撤回待审核单。

P1-03 集成基座尚未就绪（无 tests/integration/），本文件为服务层单测。
Q-02 采用方案 A：可用额度 = 上限 − 在途 − 已发放未抵扣，不与本期预估应发取小。
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import AdvanceStatus, RiderStatus
from backend.plugin.rider_salary.schema.advance import CreateMeAdvanceParam
from backend.plugin.rider_salary.schema.me import GetMeAdvanceLimit
from backend.plugin.rider_salary.service.advance_service import (
    advance_service,
    assert_within_available,
    compute_available_amount,
)

LIMIT = Decimal('3000.00')


def test_available_is_limit_minus_inflight_minus_outstanding() -> None:
    """Q-02 方案 A：不与本期预估应发取小。"""
    assert compute_available_amount(LIMIT, Decimal(0), Decimal(1000)) == Decimal('2000.00')
    assert compute_available_amount(LIMIT, Decimal(500), Decimal(800)) == Decimal('1700.00')
    assert compute_available_amount(LIMIT, Decimal(0), Decimal(3500)) == Decimal('0.00')
    assert compute_available_amount(LIMIT, Decimal(0), Decimal(0)) == LIMIT


def test_amount_over_hard_cap_keeps_limit_message() -> None:
    with pytest.raises(errors.RequestError, match=r'预支金额不能超过上限 3000\.00 元'):
        assert_within_available(Decimal('3000.01'), LIMIT, LIMIT)


def test_amount_over_available_says_insufficient() -> None:
    with pytest.raises(errors.RequestError, match=r'可用额度不足，当前可申请 2000\.00 元') as exc:
        assert_within_available(Decimal(2500), LIMIT, Decimal(2000))
    assert exc.value.code == 400


def _rider() -> SimpleNamespace:
    return SimpleNamespace(id=18, site_id=1, status=RiderStatus.on_job.value, advance_limit=LIMIT)


def _request() -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(id=18, username='D5A001', nickname='张伟'))


def _scalars(*values: object) -> MagicMock:
    result = MagicMock()
    result.all.return_value = list(values)
    return result


def _db_with_remainings(*values: object) -> AsyncMock:
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=_scalars(*values))
    return db


def _quota_patches(*, in_flight: list[SimpleNamespace] | None = None) -> tuple[object, object]:
    return (
        patch(
            'backend.plugin.rider_salary.service.advance_service.advance_dao.list_in_flight',
            AsyncMock(return_value=in_flight or []),
        ),
        patch(
            'backend.plugin.rider_salary.service.advance_service.site_dao.get',
            AsyncMock(return_value=SimpleNamespace(id=1, advance_limit=None)),
        ),
    )


def test_e4_second_advance_rejected_when_paid_remaining_fills_limit() -> None:
    """E4：已发放 3000 且未抵扣时，第二笔 3000 返回 400 额度不足，且不创建单据。"""

    async def _run() -> None:
        db = _db_with_remainings(Decimal('3000.00'))
        in_flight_patch, site_patch = _quota_patches()
        with (
            in_flight_patch,
            site_patch,
            patch(
                'backend.plugin.rider_salary.service.advance_service.advance_dao.create',
                AsyncMock(side_effect=AssertionError('额度不足时不应创建预支单')),
            ),
        ):
            quota = await advance_service.limit_for_rider(db=db, rider=_rider())
            parsed = GetMeAdvanceLimit(**quota)
            assert parsed.limit == LIMIT
            assert parsed.used_pending_amount == Decimal('0.00')
            assert parsed.outstanding_amount == LIMIT
            assert parsed.available == Decimal('0.00')
            with pytest.raises(errors.RequestError, match='可用额度不足') as exc:
                await advance_service.submit_for_rider(
                    db=db,
                    request=_request(),
                    rider=_rider(),
                    obj=CreateMeAdvanceParam(amount=LIMIT, reason='再次周转'),
                )
            assert exc.value.code == 400

    anyio.run(_run)


def test_partial_remaining_still_allows_amount_within_room() -> None:
    """已抵扣一部分后，只占用 remaining，剩余额度内可以再申请。"""

    async def _run() -> None:
        created = SimpleNamespace(id=99)
        db = _db_with_remainings(Decimal('1000.00'), None, Decimal(0), Decimal(-1))
        in_flight_patch, site_patch = _quota_patches()
        create = AsyncMock(return_value=created)
        with (
            in_flight_patch,
            site_patch,
            patch('backend.plugin.rider_salary.service.advance_service.advance_dao.create', create),
            patch('backend.plugin.rider_salary.service.advance_service.audit_service.record', AsyncMock()),
        ):
            quota = await advance_service.limit_for_rider(db=db, rider=_rider())
            assert quota['outstanding_amount'] == Decimal('1000.00')
            assert quota['available'] == Decimal('2000.00')
            with pytest.raises(errors.RequestError, match=r'可用额度不足，当前可申请 2000\.00 元'):
                await advance_service.submit_for_rider(
                    db=db,
                    request=_request(),
                    rider=_rider(),
                    obj=CreateMeAdvanceParam(amount=Decimal('2000.01'), reason='周转'),
                )
            advance = await advance_service.submit_for_rider(
                db=db,
                request=_request(),
                rider=_rider(),
                obj=CreateMeAdvanceParam(amount=Decimal(2000), reason='周转'),
            )
            assert advance is created
            assert create.await_args.args[1].amount == Decimal('2000.00')

    anyio.run(_run)


def test_inflight_reduces_available_and_blocks_submit() -> None:
    async def _run() -> None:
        db = _db_with_remainings(Decimal('700.00'))
        in_flight = [SimpleNamespace(amount=Decimal('800.00'), status=AdvanceStatus.pending.value)]
        in_flight_patch, site_patch = _quota_patches(in_flight=in_flight)
        with in_flight_patch, site_patch:
            quota = await advance_service.limit_for_rider(db=db, rider=_rider())
            assert quota['used_pending_amount'] == Decimal('800.00')
            assert quota['outstanding_amount'] == Decimal('700.00')
            assert quota['available'] == Decimal('1500.00')
            with pytest.raises(errors.RequestError, match='您已有一笔待审核或待发放的预支'):
                await advance_service.submit_for_rider(
                    db=db,
                    request=_request(),
                    rider=_rider(),
                    obj=CreateMeAdvanceParam(amount=Decimal(100), reason='周转'),
                )

    anyio.run(_run)


def test_paid_remaining_query_only_counts_paid_rows() -> None:
    async def _run() -> None:
        db = _db_with_remainings(Decimal('1.00'))
        in_flight_patch, site_patch = _quota_patches()
        with in_flight_patch, site_patch:
            await advance_service.limit_for_rider(db=db, rider=_rider())
        stmt = db.scalars.await_args.args[0]
        sql = str(stmt)
        params = list(stmt.compile().params.values())
        assert 'remaining_amount' in sql
        assert 'status' in sql
        assert 'rider_id' in sql
        assert 'deleted' in sql
        assert AdvanceStatus.paid.value in params
        assert 18 in params
        assert 0 in params

    anyio.run(_run)


def _cancel_target(*, status: str, rider_id: int = 18) -> SimpleNamespace:
    return SimpleNamespace(
        id=5,
        rider_id=rider_id,
        site_id=1,
        amount=Decimal('800.00'),
        reason='周转',
        status=status,
        approver_id=2,
        approve_time=None,
        approve_remark=None,
        paid_by=None,
        paid_time=None,
        deducted_amount=Decimal('0.00'),
        remaining_amount=Decimal('800.00') if status == AdvanceStatus.paid.value else None,
        deduct_status='none',
        submit_time=None,
        cancel_time=None,
    )


@pytest.mark.parametrize(
    'status',
    [
        AdvanceStatus.draft.value,
        AdvanceStatus.to_pay.value,
        AdvanceStatus.paid.value,
        AdvanceStatus.rejected.value,
        AdvanceStatus.cancelled.value,
    ],
)
def test_rider_cancel_rejects_non_pending(status: str) -> None:
    """E10：撤回待发放返回 400；草稿、已发放、已驳回、已取消同样拒绝。"""

    async def _run() -> None:
        advance = _cancel_target(status=status)
        with patch(
            'backend.plugin.rider_salary.service.advance_service.advance_dao.get',
            AsyncMock(return_value=advance),
        ):
            with pytest.raises(errors.RequestError, match='只能撤回待审核的预支申请') as exc:
                await advance_service.cancel_for_rider(
                    db=AsyncMock(),
                    request=_request(),
                    rider=_rider(),
                    pk=advance.id,
                )
            assert exc.value.code == 400
            assert advance.status == status
            assert advance.cancel_time is None

    anyio.run(_run)


def test_rider_can_cancel_pending() -> None:
    async def _run() -> None:
        advance = _cancel_target(status=AdvanceStatus.pending.value)
        with (
            patch(
                'backend.plugin.rider_salary.service.advance_service.advance_dao.get',
                AsyncMock(return_value=advance),
            ),
            patch.object(advance_service, '_audit', AsyncMock()) as audit,
        ):
            await advance_service.cancel_for_rider(
                db=AsyncMock(),
                request=_request(),
                rider=_rider(),
                pk=advance.id,
            )
        assert advance.status == AdvanceStatus.cancelled.value
        assert advance.cancel_time is not None
        audit.assert_awaited_once()

    anyio.run(_run)


def test_rider_cancel_missing_or_others_advance() -> None:
    async def _run() -> None:
        with patch(
            'backend.plugin.rider_salary.service.advance_service.advance_dao.get',
            AsyncMock(return_value=None),
        ):
            with pytest.raises(errors.NotFoundError, match='预支单不存在'):
                await advance_service.cancel_for_rider(
                    db=AsyncMock(),
                    request=_request(),
                    rider=_rider(),
                    pk=5,
                )
        other = _cancel_target(status=AdvanceStatus.pending.value, rider_id=99)
        with patch(
            'backend.plugin.rider_salary.service.advance_service.advance_dao.get',
            AsyncMock(return_value=other),
        ):
            with pytest.raises(errors.NotFoundError, match='预支单不存在'):
                await advance_service.cancel_for_rider(
                    db=AsyncMock(),
                    request=_request(),
                    rider=_rider(),
                    pk=other.id,
                )
        assert other.status == AdvanceStatus.pending.value

    anyio.run(_run)
