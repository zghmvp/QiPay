from datetime import datetime
from decimal import Decimal

import pytest

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import AdvanceStatus
from backend.plugin.rider_salary.utils.advance_quota import (
    DEFAULT_MONTHLY_ADVANCE_LIMIT,
    QUOTA_EXHAUSTED_MSG,
    SHANGHAI_TZ,
    SITE_DISABLED_MSG,
    assert_monthly_advance_quota,
    count_monthly_quota_used,
    monthly_advance_quota,
    resolve_monthly_advance_limit,
    shanghai_natural_month,
)


def _quota_error(limit: int | None, used: int, month: str | None = '2026-09') -> str:
    with pytest.raises(errors.RequestError) as exc_info:
        assert_monthly_advance_quota(limit=limit, used=used, month=month)
    return str(exc_info.value)


def test_advance_monthly_quota_default_one() -> None:
    """默认 1：同月第二次失败，文案是次数不是金额"""
    assert DEFAULT_MONTHLY_ADVANCE_LIMIT == 1
    assert resolve_monthly_advance_limit(None) == 1
    assert monthly_advance_quota(limit=None, used=0, month='2026-09') == {
        'monthly_advance_limit': 1,
        'limit': 1,
        'used': 0,
        'remaining': 1,
        'month': '2026-09',
    }
    assert_monthly_advance_quota(limit=None, used=0, month='2026-09')
    msg = _quota_error(None, 1, '2026-09')
    assert QUOTA_EXHAUSTED_MSG in msg
    assert '2026年9月' in msg
    assert '元' not in msg
    assert '金额' not in msg
    assert '请联系站点' not in msg


def test_advance_monthly_quota_site_two() -> None:
    """站点 2：第二次成功，第三次失败"""
    quota_after_first = monthly_advance_quota(limit=2, used=1, month='2026-09')
    assert quota_after_first['remaining'] == 1
    assert_monthly_advance_quota(limit=2, used=0, month='2026-09')
    assert_monthly_advance_quota(limit=2, used=1, month='2026-09')
    msg = _quota_error(2, 2, '2026-09')
    assert QUOTA_EXHAUSTED_MSG in msg
    assert '2026年9月' in msg


def test_advance_monthly_quota_site_zero() -> None:
    """站点 0：第一次也失败"""
    quota = monthly_advance_quota(limit=0, used=0, month='2026-09')
    assert quota == {
        'monthly_advance_limit': 0,
        'limit': 0,
        'used': 0,
        'remaining': 0,
        'month': '2026-09',
    }
    msg = _quota_error(0, 0, '2026-09')
    assert msg == SITE_DISABLED_MSG
    assert QUOTA_EXHAUSTED_MSG not in msg
    assert '请联系站点' not in msg


def test_advance_monthly_quota_rejected_does_not_consume() -> None:
    """驳回 / 撤回不占次数，可再申请"""
    used = count_monthly_quota_used([
        AdvanceStatus.rejected.value,
        AdvanceStatus.cancelled.value,
        AdvanceStatus.draft.value,
    ])
    assert used == 0
    assert_monthly_advance_quota(limit=1, used=used, month='2026-09')
    used_with_pending = count_monthly_quota_used([
        AdvanceStatus.rejected.value,
        AdvanceStatus.pending.value,
    ])
    assert used_with_pending == 1
    msg = _quota_error(1, used_with_pending, '2026-09')
    assert QUOTA_EXHAUSTED_MSG in msg


def test_advance_monthly_quota_paid_and_to_pay_consume() -> None:
    used = count_monthly_quota_used([
        AdvanceStatus.to_pay.value,
        AdvanceStatus.paid.value,
        AdvanceStatus.rejected.value,
    ])
    assert used == 2
    assert monthly_advance_quota(limit=2, used=used)['remaining'] == 0


def test_advance_monthly_quota_site_isolation() -> None:
    """站点 A 的次数不影响站点 B（按骑手各自 used 计数）"""
    site_a = monthly_advance_quota(limit=1, used=1, month='2026-09')
    site_b = monthly_advance_quota(limit=1, used=0, month='2026-09')
    assert site_a['remaining'] == 0
    assert site_b['remaining'] == 1
    assert_monthly_advance_quota(limit=1, used=0, month='2026-09')


def test_advance_monthly_quota_half_month_same_natural_month() -> None:
    """半月结仍按自然月：上半月用掉 1 次，下半月默认 1 再申请失败"""
    start, end, month = shanghai_natural_month(datetime(2026, 9, 20, 10, 0, tzinfo=SHANGHAI_TZ))
    assert month == '2026-09'
    assert start.day == 1
    assert start.month == 9
    assert end.month == 10
    assert end.day == 1
    msg = _quota_error(1, 1, month)
    assert '2026年9月' in msg
    assert QUOTA_EXHAUSTED_MSG in msg


def test_advance_monthly_quota_api_field_names() -> None:
    """管理端 /advances/quota 与 H5 /me/advance-quota 同一字段：monthly_advance_limit / used / remaining"""
    from backend.plugin.rider_salary.schema.advance import GetAdvanceQuota
    from backend.plugin.rider_salary.schema.me import GetMeAdvanceLimit

    quota = GetAdvanceQuota(
        monthly_advance_limit=1,
        used=0,
        remaining=1,
        month='2026-09',
        rider_id=5,
        site_id=1,
    )
    dumped = quota.model_dump()
    assert dumped['monthly_advance_limit'] == 1
    assert dumped['used'] == 0
    assert dumped['remaining'] == 1
    assert dumped['limit'] == 1
    data = GetMeAdvanceLimit(
        limit=Decimal('3000.00'),
        used_pending_amount=Decimal('0.00'),
        available=Decimal('3000.00'),
        monthly_advance_limit=1,
        used=0,
        remaining=1,
        month='2026-09',
    )
    money = data.model_dump()
    assert money['monthly_advance_limit'] == 1
    assert money['used'] == 0
    assert money['remaining'] == 1
    assert money['limit'] == Decimal('3000.00')
