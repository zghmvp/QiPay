"""清单 #13：预支 mark-paid 后 draft+stale → 骑手端预估 is_estimate=true。"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anyio

from backend.plugin.rider_salary.enums import (
    AdvanceStatus,
    DeductStatus,
    DetailSource,
    PayrollKind,
    PayrollStatus,
    RiderStatus,
)
from backend.plugin.rider_salary.schema.advance import AdvanceActionParam
from backend.plugin.rider_salary.service.advance_service import advance_service
from backend.plugin.rider_salary.service.me_service import me_service
from backend.plugin.rider_salary.service.payroll_service import preview_advance_deduction
from backend.utils.timezone import timezone


def _advance_to_pay(*, rider_id: int = 7) -> SimpleNamespace:
    return SimpleNamespace(
        id=11,
        rider_id=rider_id,
        site_id=1,
        amount=Decimal('800.00'),
        reason='周转',
        status=AdvanceStatus.to_pay.value,
        approver_id=2,
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


def test_mark_paid_calls_mark_stale() -> None:
    advance = _advance_to_pay()
    request = SimpleNamespace(user=SimpleNamespace(id=9, username='admin', nickname='admin'))

    async def _run() -> None:
        with (
            patch.object(advance_service, '_load_writable', AsyncMock(return_value=advance)),
            patch.object(advance_service, '_audit', AsyncMock()) as audit,
            patch(
                'backend.plugin.rider_salary.service.advance_service.rider_dao.get',
                AsyncMock(return_value=SimpleNamespace(status=RiderStatus.on_job.value)),
            ),
            patch(
                'backend.plugin.rider_salary.service.advance_service.mark_stale',
                AsyncMock(return_value=1),
            ) as stale,
        ):
            await advance_service.mark_paid(
                db=AsyncMock(),
                request=request,
                pk=11,
                obj=AdvanceActionParam(remark=None),
            )
            stale.assert_awaited_once()
            kwargs = stale.await_args.kwargs
            assert kwargs['rider_ids'] == [7]
            paid_date = timezone.from_datetime(advance.paid_time).date()
            assert kwargs['date_from'] == paid_date
            assert kwargs['date_to'] == paid_date
            audit.assert_awaited_once()
            assert advance.status == AdvanceStatus.paid.value

    anyio.run(_run)


def _payroll(*, stale: bool, status: str = PayrollStatus.draft.value, pk: int = 21) -> SimpleNamespace:
    return SimpleNamespace(
        id=pk,
        status=status,
        stale=stale,
        kind=PayrollKind.normal.value,
        calc_version=3,
        order_count=12,
        gross=Decimal('100.00'),
        deduction_total=Decimal('0.00'),
        advance_deduction=Decimal('0.00'),
        net=Decimal('100.00'),
        calc_time=datetime(2026, 9, 1, 8, 0, tzinfo=timezone.tz_info),
        updated_time=None,
    )


def _period() -> SimpleNamespace:
    return SimpleNamespace(
        id=5,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 15),
        status='open',
    )


async def _estimate(rows: list[SimpleNamespace], *, calc: SimpleNamespace | None = None) -> object:
    scalars = MagicMock()
    scalars.all.return_value = rows
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=scalars)
    calc_result = calc or SimpleNamespace(
        order_count=15,
        gross=Decimal('120.00'),
        deduction_total=Decimal('0.00'),
        advance_deductible=Decimal('0.00'),
        net=Decimal('120.00'),
    )
    rider = SimpleNamespace(id=7, site_id=1)
    with (
        patch(
            'backend.plugin.rider_salary.service.me_service.resolve_period',
            AsyncMock(return_value=_period()),
        ),
        patch(
            'backend.plugin.rider_salary.service.me_service.calculate_rider_period',
            AsyncMock(return_value=calc_result),
        ) as calc_mock,
        patch(
            'backend.plugin.rider_salary.service.me_service.payroll_detail_dao.list_by_payroll',
            AsyncMock(return_value=[]),
        ),
        patch(
            'backend.plugin.rider_salary.service.me_service._cached_estimate',
            AsyncMock(return_value=None),
        ),
        patch(
            'backend.plugin.rider_salary.service.me_service._store_estimate',
            AsyncMock(),
        ),
    ):
        data = await me_service.payroll_estimate(db=db, rider=rider)
        return data, calc_mock


def test_stale_draft_payroll_estimate_is_estimate() -> None:
    async def _run() -> None:
        data, calc_mock = await _estimate([_payroll(stale=True)])
        assert data.is_estimate is True
        assert data.net_estimate == Decimal('120.00')
        calc_mock.assert_awaited_once()

    anyio.run(_run)


def test_fresh_draft_payroll_estimate_uses_stored() -> None:
    async def _run() -> None:
        data, calc_mock = await _estimate([_payroll(stale=False)])
        assert data.is_estimate is False
        assert data.net_estimate == Decimal('100.00')
        calc_mock.assert_not_awaited()

    anyio.run(_run)


def _paid_advance(
    *,
    pk: int,
    remaining: str,
    deducted: str,
    amount: str = '10.00',
    paid_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=pk,
        amount=Decimal(amount),
        remaining_amount=Decimal(remaining),
        deducted_amount=Decimal(deducted),
        paid_time=paid_at or datetime(2026, 10, 5, 9, 0, tzinfo=timezone.tz_info),
        deduct_status=DeductStatus.done.value,
    )


def _advance_detail(
    advance_id: int | str,
    amount: str = '-10.00',
    *,
    source: str = DetailSource.advance.value,
) -> SimpleNamespace:
    return SimpleNamespace(
        source=source,
        amount=Decimal(amount),
        deleted=0,
        calc_trace={'advance_id': advance_id},
    )


def test_preview_restores_consumed_advance_without_writing_remaining() -> None:
    """草稿已抵扣完的 10 元要加回后再抵，原预支余额保持 0。"""
    advance = _paid_advance(pk=11, remaining='0.00', deducted='10.00')
    total = preview_advance_deduction([advance], [_advance_detail(11)], Decimal('20.00'))
    assert total == Decimal('10.00')
    assert advance.remaining_amount == Decimal('0.00')
    assert advance.deducted_amount == Decimal('10.00')


def test_preview_deduction_does_not_exceed_cap() -> None:
    advance = _paid_advance(pk=11, remaining='0.00', deducted='10.00')
    total = preview_advance_deduction([advance], [_advance_detail(11)], Decimal('6.00'))
    assert total == Decimal('6.00')
    assert advance.remaining_amount == Decimal('0.00')


def test_preview_partial_restore_uses_amount_before_this_draft() -> None:
    """已抵 10、尚余 90 时，可抵扣额 95 应抵 95，而不是只看当前剩余 90。"""
    advance = _paid_advance(pk=11, remaining='90.00', deducted='10.00', amount='100.00')
    total = preview_advance_deduction([advance], [_advance_detail(11)], Decimal('95.00'))
    assert total == Decimal('95.00')
    assert advance.remaining_amount == Decimal('90.00')
    assert advance.deducted_amount == Decimal('10.00')


def test_preview_includes_other_outstanding_advance() -> None:
    occupied = _paid_advance(pk=11, remaining='0.00', deducted='10.00')
    other = _paid_advance(
        pk=12,
        remaining='5.00',
        deducted='0.00',
        amount='5.00',
        paid_at=datetime(2026, 10, 6, 9, 0, tzinfo=timezone.tz_info),
    )
    total = preview_advance_deduction([occupied, other], [_advance_detail(11)], Decimal('20.00'))
    assert total == Decimal('15.00')
    assert occupied.remaining_amount == Decimal('0.00')
    assert other.remaining_amount == Decimal('5.00')


def test_preview_ignores_non_advance_and_unknown_ids() -> None:
    advance = _paid_advance(pk=11, remaining='0.00', deducted='10.00')
    details = [
        _advance_detail(11, source=DetailSource.formula.value),
        _advance_detail(99),
        SimpleNamespace(source=DetailSource.advance.value, amount=Decimal('-10.00'), deleted=0, calc_trace={}),
        SimpleNamespace(
            source=DetailSource.advance.value,
            amount=Decimal('-10.00'),
            deleted=0,
            calc_trace={'advance_id': 'abc'},
        ),
    ]
    assert preview_advance_deduction([advance], details, Decimal('20.00')) is None
    assert advance.remaining_amount == Decimal('0.00')


def test_preview_accepts_string_advance_id_and_caps_repeated_restore() -> None:
    advance = _paid_advance(pk=11, remaining='0.00', deducted='10.00')
    total = preview_advance_deduction(
        [advance],
        [_advance_detail('11'), _advance_detail(11)],
        Decimal('30.00'),
    )
    assert total == Decimal('10.00')
    assert advance.remaining_amount == Decimal('0.00')


def test_stale_estimate_reports_gross_20_deduction_10_net_10() -> None:
    """E15 内存路径：应发 20、抵扣 10、实发 10，预支待抵扣余额不被写回。"""
    advance = _paid_advance(pk=11, remaining='0.00', deducted='10.00')
    payroll_scalars = MagicMock()
    payroll_scalars.all.return_value = [_payroll(stale=True)]
    advance_scalars = MagicMock()
    advance_scalars.all.return_value = [advance]
    db = AsyncMock()
    db.scalars = AsyncMock(side_effect=[payroll_scalars, advance_scalars])
    calc_result = SimpleNamespace(
        order_count=4,
        gross=Decimal('20.00'),
        deduction_total=Decimal('0.00'),
        advance_deductible=Decimal('0.00'),
        net=Decimal('20.00'),
    )
    rider = SimpleNamespace(id=7, site_id=1)

    async def _run() -> None:
        with (
            patch(
                'backend.plugin.rider_salary.service.me_service.resolve_period',
                AsyncMock(return_value=_period()),
            ),
            patch(
                'backend.plugin.rider_salary.service.me_service.calculate_rider_period',
                AsyncMock(return_value=calc_result),
            ),
            patch(
                'backend.plugin.rider_salary.service.me_service.payroll_detail_dao.list_by_payroll',
                AsyncMock(return_value=[_advance_detail(11)]),
            ),
            patch(
                'backend.plugin.rider_salary.service.me_service._cached_estimate',
                AsyncMock(return_value=None),
            ),
            patch(
                'backend.plugin.rider_salary.service.me_service._store_estimate',
                AsyncMock(),
            ),
        ):
            data = await me_service.payroll_estimate(db=db, rider=rider)
        assert data.is_estimate is True
        assert data.gross == Decimal('20.00')
        assert data.deduction_total == Decimal('0.00')
        assert data.advance_deduction_estimate == Decimal('10.00')
        assert data.net_estimate == Decimal('10.00')
        assert advance.remaining_amount == Decimal('0.00')
        assert advance.deducted_amount == Decimal('10.00')

    anyio.run(_run)
