"""清单 #13：预支 mark-paid 后 draft+stale → 骑手端预估 is_estimate=true。"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anyio

from backend.plugin.rider_salary.enums import AdvanceStatus, DeductStatus, PayrollKind, PayrollStatus, RiderStatus
from backend.plugin.rider_salary.schema.advance import AdvanceActionParam
from backend.plugin.rider_salary.service.advance_service import advance_service
from backend.plugin.rider_salary.service.me_service import me_service
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
