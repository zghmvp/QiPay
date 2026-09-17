"""站点每月预支次数：自然月（Asia/Shanghai），空=1，0=禁止。"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import anyio
import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import AdvanceStatus, DeductStatus, RiderStatus
from backend.plugin.rider_salary.schema.advance import CreateMeAdvanceParam, GetAdvanceDetail
from backend.plugin.rider_salary.service.advance_service import (
    MSG_QUOTA_EXHAUSTED,
    MSG_SITE_ADVANCE_BANNED,
    advance_service,
    attach_quota_fields,
    count_consumed_in_month,
    monthly_quota_view,
    resolve_monthly_advance_limit,
    shanghai_calendar_month_bounds,
)

SHANGHAI = ZoneInfo('Asia/Shanghai')
PLUGIN_SQL = Path(__file__).resolve().parents[1] / 'sql'


def _row(
    *,
    status: str,
    rider_id: int = 1,
    site_id: int = 10,
    submit_time: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(rider_id=rider_id, site_id=site_id, status=status, submit_time=submit_time)


def _created(*, amount: Decimal = Decimal('100.00')) -> SimpleNamespace:
    return SimpleNamespace(
        id=99,
        rider_id=1,
        site_id=10,
        amount=amount,
        reason='周转',
        status=AdvanceStatus.pending.value,
        approver_id=None,
        approve_time=None,
        approve_remark=None,
        paid_by=None,
        paid_time=None,
        deducted_amount=Decimal('0.00'),
        remaining_amount=None,
        deduct_status=DeductStatus.none.value,
        submit_time=datetime(2026, 9, 17, 12, tzinfo=SHANGHAI),
        cancel_time=None,
        created_time=None,
        updated_time=None,
    )


def _submit(*, monthly_limit: int | None, consumed: int, amount: Decimal = Decimal('100.00')) -> SimpleNamespace:
    rider = SimpleNamespace(
        id=1,
        site_id=10,
        status=RiderStatus.on_job.value,
        advance_limit=None,
    )
    site = SimpleNamespace(id=10, advance_limit=None, monthly_advance_limit=monthly_limit)
    created = _created(amount=amount)
    request = SimpleNamespace(user=SimpleNamespace(id=8, username='rider', nickname='骑手'))

    async def _run() -> SimpleNamespace:
        with (
            patch(
                'backend.plugin.rider_salary.service.advance_service.advance_dao.list_in_flight',
                AsyncMock(return_value=[]),
            ),
            patch(
                'backend.plugin.rider_salary.service.advance_service.site_dao.get',
                AsyncMock(return_value=site),
            ),
            patch(
                'backend.plugin.rider_salary.service.advance_service.advance_dao.count_monthly_consumed',
                AsyncMock(return_value=consumed),
            ),
            patch(
                'backend.plugin.rider_salary.service.advance_service.advance_dao.create',
                AsyncMock(return_value=created),
            ) as create,
            patch(
                'backend.plugin.rider_salary.service.advance_service.audit_service.record',
                AsyncMock(),
            ),
        ):
            result = await advance_service.submit_for_rider(
                db=AsyncMock(),
                request=request,
                rider=rider,
                obj=CreateMeAdvanceParam(amount=amount, reason='周转'),
            )
            create.assert_awaited_once()
            return result

    return anyio.run(_run)


def test_advance_monthly_quota_default_one() -> None:
    assert resolve_monthly_advance_limit(None) == 1
    assert monthly_quota_view(1, 0) == {
        'monthly_advance_limit': 1,
        'limit': 1,
        'used': 0,
        'remaining': 1,
    }
    created = _submit(monthly_limit=None, consumed=0)
    assert created.id == 99
    with pytest.raises(errors.RequestError, match=MSG_QUOTA_EXHAUSTED):
        _submit(monthly_limit=None, consumed=1)
    with pytest.raises(errors.RequestError, match=MSG_QUOTA_EXHAUSTED):
        _submit(monthly_limit=1, consumed=1)


def test_advance_monthly_quota_site_two() -> None:
    first = _submit(monthly_limit=2, consumed=0)
    second = _submit(monthly_limit=2, consumed=1)
    assert first.id == 99
    assert second.id == 99
    with pytest.raises(errors.RequestError, match=MSG_QUOTA_EXHAUSTED):
        _submit(monthly_limit=2, consumed=2)


def test_advance_monthly_quota_site_zero() -> None:
    with pytest.raises(errors.RequestError, match=MSG_SITE_ADVANCE_BANNED):
        _submit(monthly_limit=0, consumed=0)


def test_advance_monthly_quota_rejected_does_not_consume() -> None:
    now = datetime(2026, 9, 17, 12, tzinfo=SHANGHAI)
    start, end = shanghai_calendar_month_bounds(now)
    rows = [
        _row(status=AdvanceStatus.rejected.value, submit_time=now),
        _row(status=AdvanceStatus.cancelled.value, submit_time=now),
        _row(status=AdvanceStatus.draft.value, submit_time=now),
    ]
    assert count_consumed_in_month(rows, rider_id=1, site_id=10, month_start=start, month_end=end) == 0
    created = _submit(monthly_limit=1, consumed=0)
    assert created.status == AdvanceStatus.pending.value


def test_advance_monthly_quota_cross_site() -> None:
    now = datetime(2026, 9, 17, 12, tzinfo=SHANGHAI)
    start, end = shanghai_calendar_month_bounds(now)
    rows = [
        _row(status=AdvanceStatus.paid.value, site_id=99, submit_time=now),
        _row(status=AdvanceStatus.pending.value, site_id=99, submit_time=now),
    ]
    assert count_consumed_in_month(rows, rider_id=1, site_id=10, month_start=start, month_end=end) == 0
    created = _submit(monthly_limit=1, consumed=0)
    assert created.site_id == 10


def test_advance_monthly_quota_natural_month_not_period() -> None:
    """半月结也按自然月：上半月占用算进下半月。"""
    first_half = datetime(2026, 9, 10, 9, tzinfo=SHANGHAI)
    second_half = datetime(2026, 9, 20, 9, tzinfo=SHANGHAI)
    start, end = shanghai_calendar_month_bounds(second_half)
    assert start == datetime(2026, 9, 1, tzinfo=SHANGHAI)
    assert end == datetime(2026, 10, 1, tzinfo=SHANGHAI)
    rows = [_row(status=AdvanceStatus.paid.value, submit_time=first_half)]
    assert count_consumed_in_month(rows, rider_id=1, site_id=10, month_start=start, month_end=end) == 1
    utc_next_month = datetime(2026, 9, 30, 16, 0, tzinfo=ZoneInfo('UTC'))
    oct_start, oct_end = shanghai_calendar_month_bounds(utc_next_month)
    assert oct_start.month == 10
    assert oct_end.month == 11


def test_advance_monthly_quota_errors_separate_from_amount_cap() -> None:
    with pytest.raises(errors.RequestError, match=MSG_SITE_ADVANCE_BANNED):
        _submit(monthly_limit=0, consumed=0, amount=Decimal('1.00'))
    with pytest.raises(errors.RequestError, match=r'预支金额不能超过上限 3000\.00 元'):
        _submit(monthly_limit=2, consumed=0, amount=Decimal('3000.01'))
    with pytest.raises(errors.RequestError, match=MSG_QUOTA_EXHAUSTED):
        _submit(monthly_limit=1, consumed=1, amount=Decimal('10.00'))


def test_advance_list_detail_includes_quota_fields() -> None:
    payload = {
        'id': 7,
        'rider_id': 1,
        'site_id': 10,
        'amount': Decimal('80.00'),
        'reason': '周转',
        'status': AdvanceStatus.pending.value,
        'approver_id': None,
        'approve_time': None,
        'approve_remark': None,
        'paid_by': None,
        'paid_time': None,
        'deducted_amount': Decimal('0.00'),
        'remaining_amount': None,
        'deduct_status': DeductStatus.none.value,
        'submit_time': datetime(2026, 9, 17, 12, tzinfo=SHANGHAI),
        'cancel_time': None,
        'timeline': [],
        'created_time': datetime(2026, 9, 17, 12, tzinfo=SHANGHAI),
        'updated_time': None,
    }
    attach_quota_fields(payload, monthly_quota_view(2, 1))
    detail = GetAdvanceDetail.model_validate(payload)
    assert detail.quota is not None
    assert detail.quota.monthly_advance_limit == 2
    assert detail.quota.limit == 2
    assert detail.quota.used == 1
    assert detail.quota.remaining == 1
    assert detail.monthly_advance_limit == 2
    assert detail.monthly_advance_used == 1
    assert detail.monthly_advance_remaining == 1
    dumped = detail.quota.model_dump()
    assert dumped['monthly_advance_limit'] == 2
    assert dumped['limit'] == 2
    assert dumped['used'] == 1
    assert dumped['remaining'] == 1


def test_advance_monthly_quota_sql_patch_exists() -> None:
    pg_patch = PLUGIN_SQL / 'patch' / '002_site_monthly_advance_limit.sql'
    mysql_patch = PLUGIN_SQL / 'patch' / '002_site_monthly_advance_limit.mysql.sql'
    assert 'monthly_advance_limit' in pg_patch.read_text(encoding='utf-8')
    assert 'monthly_advance_limit' in mysql_patch.read_text(encoding='utf-8')
    pg_init = (PLUGIN_SQL / 'postgresql' / 'init.sql').read_text(encoding='utf-8')
    assert 'monthly_advance_limit' in pg_init
    mysql_init = (PLUGIN_SQL / 'mysql' / 'init.sql').read_text(encoding='utf-8')
    assert 'monthly_advance_limit' in mysql_init
