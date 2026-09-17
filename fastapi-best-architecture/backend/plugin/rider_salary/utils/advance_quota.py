from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import AdvanceStatus

SHANGHAI_TZ = ZoneInfo('Asia/Shanghai')
DEFAULT_MONTHLY_ADVANCE_LIMIT = 1
QUOTA_CONSUMING_STATUSES = frozenset({
    AdvanceStatus.pending.value,
    AdvanceStatus.to_pay.value,
    AdvanceStatus.paid.value,
})
SITE_DISABLED_MSG = '本站暂不可预支'
QUOTA_EXHAUSTED_MSG = '本月预支次数已用完'


def resolve_monthly_advance_limit(site_limit: int | None) -> int:
    """
    站点每月可预支次数：未填 / 空 = 1；0 = 本站禁止预支

    :param site_limit: 站点配置值
    :return: 解析后的次数上限
    """
    if site_limit is None:
        return DEFAULT_MONTHLY_ADVANCE_LIMIT
    return max(int(site_limit), 0)


def shanghai_natural_month(now: datetime | None = None) -> tuple[datetime, datetime, str]:
    """
    Asia/Shanghai 自然月半开区间 [start, end) 与 YYYY-MM

    半月结也按自然月，不是每个结算周期 1 次。

    :param now: 参考时刻，默认当前上海时间
    :return: 月初、下月初、自然月
    """
    local = now or datetime.now(SHANGHAI_TZ)
    local = local.replace(tzinfo=SHANGHAI_TZ) if local.tzinfo is None else local.astimezone(SHANGHAI_TZ)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start, end, f'{start.year:04d}-{start.month:02d}'


def format_natural_month_zh(month: str) -> str:
    """YYYY-MM → 2026年9月"""
    year_str, month_str = month.split('-', 1)
    return f'{int(year_str)}年{int(month_str)}月'


def count_monthly_quota_used(statuses: list[str]) -> int:
    """
    按状态列表计占用次数。pending / to_pay / paid 各占 1；rejected / cancelled 不占。

    :param statuses: 本月该骑手预支单状态
    :return: 已占用次数
    """
    return sum(1 for status in statuses if status in QUOTA_CONSUMING_STATUSES)


def monthly_advance_quota(
    *,
    limit: int | None,
    used: int,
    month: str | None = None,
) -> dict[str, Any]:
    """
    查询接口口径：limit / used / remaining（当前自然月）

    :param limit: 站点每月可预支次数，None 按 1
    :param used: 已占用次数
    :param month: 自然月 YYYY-MM
    :return: 额度字典
    """
    resolved = resolve_monthly_advance_limit(limit)
    consumed = max(int(used), 0)
    payload: dict[str, Any] = {
        'monthly_advance_limit': resolved,
        'limit': resolved,
        'used': consumed,
        'remaining': max(resolved - consumed, 0),
    }
    if month:
        payload['month'] = month
    return payload


def quota_exhausted_message(month: str | None = None) -> str:
    """次数用尽文案，带自然月，不写金额、不写请联系站点"""
    if not month:
        return QUOTA_EXHAUSTED_MSG
    return f'{QUOTA_EXHAUSTED_MSG}（{format_natural_month_zh(month)}）'


def assert_monthly_advance_quota(*, limit: int | None, used: int, month: str | None = None) -> None:
    """
    申请前次数强校验。站点 0 与次数用尽是两条硬拒绝，文案与金额上限分开。

    :param limit: 站点每月可预支次数
    :param used: 本月已占用次数
    :param month: 自然月 YYYY-MM
    """
    resolved = resolve_monthly_advance_limit(limit)
    if resolved <= 0:
        raise errors.RequestError(msg=SITE_DISABLED_MSG)
    if int(used) >= resolved:
        raise errors.RequestError(msg=quota_exhausted_message(month))
