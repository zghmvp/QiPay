from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from chinese_calendar import is_holiday

from backend.plugin.rider_salary.engine.fields import ALL_FIELD_NAMES, NUMBER_FIELDS, get_field
from backend.plugin.rider_salary.engine.functions import to_minutes
from backend.plugin.rider_salary.enums import EmployType, OrderStatus
from backend.plugin.rider_salary.utils.money import q2
from backend.utils.timezone import timezone

WEEKDAY_MONDAY_ONE = 1


def iter_dates(start: date, end: date) -> list[date]:
    """闭区间日期序列"""
    if end < start:
        return []
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def weekday_monday_one(biz_date: date) -> int:
    """周一=1 … 周日=7"""
    return biz_date.weekday() + WEEKDAY_MONDAY_ONE


def is_weekend(biz_date: date) -> bool:
    """星期六或星期日"""
    return biz_date.weekday() >= 5


def tenure_months(hire_date: date | None, period_end: date) -> int:
    """入职到周期末的整月数"""
    if hire_date is None or period_end < hire_date:
        return 0
    months = (period_end.year - hire_date.year) * 12 + (period_end.month - hire_date.month)
    if period_end.day < hire_date.day:
        months -= 1
    return max(months, 0)


def tenure_days(hire_date: date | None, period_end: date) -> int:
    """入职到周期末的日历天数（含入职当日）"""
    if hire_date is None or period_end < hire_date:
        return 0
    return (period_end - hire_date).days + 1


def _minutes_of(value: datetime | None) -> float | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = timezone.from_datetime(value)
    return float(value.hour * 60 + value.minute)


def _duration_minutes(order_time: datetime | None, deliver_time: datetime | None) -> tuple[float, bool]:
    if order_time is None or deliver_time is None:
        return 0.0, True
    seconds = (deliver_time - order_time).total_seconds()
    return max(seconds / 60.0, 0.0), False


def build_day_context(
    site_id: int,
    biz_date: date,
    day_flag: Any | None,
    employ_type: str,
) -> dict[str, Any]:
    """
    日上下文：日期、星期、节假日、周末、日标记、用工类型
    """
    del site_id
    flag = day_flag
    return {
        '日期': biz_date.isoformat(),
        '星期': weekday_monday_one(biz_date),
        '是否节假日': bool(is_holiday(biz_date)),
        '是否周末': is_weekend(biz_date),
        '是否恶劣天气': bool(getattr(flag, 'bad_weather', False)) if flag is not None else False,
        '是否高温': bool(getattr(flag, 'high_temp', False)) if flag is not None else False,
        '是否大促': bool(getattr(flag, 'promo', False)) if flag is not None else False,
        '用工类型': employ_type or EmployType.part_time.value,
    }


def build_order_context(order: Any, day_ctx: dict[str, Any], rider_ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """订单字段 ∪ 日上下文 ∪ 骑手字段"""
    duration, missing_deliver = _duration_minutes(
        getattr(order, 'order_time', None),
        getattr(order, 'deliver_time', None),
    )
    amount = getattr(order, 'amount', None)
    ctx: dict[str, Any] = {
        **day_ctx,
        **(rider_ctx or {}),
        '配送距离': float(getattr(order, 'distance_km', 0) or 0),
        '商品重量': float(getattr(order, 'weight_jin', 0) or 0),
        '订单金额': float(amount) if amount is not None else 0.0,
        '下单时刻': _minutes_of(getattr(order, 'order_time', None)),
        '送达时刻': _minutes_of(getattr(order, 'deliver_time', None)),
        '配送时长': duration,
        '订单状态': getattr(order, 'status', None) or OrderStatus.completed.value,
        '_missing_deliver': missing_deliver,
        '_order_no': getattr(order, 'order_no', None),
        '_order_id': getattr(order, 'id', None),
        '_biz_date': getattr(order, 'biz_date', None),
    }
    return ctx


def build_period_context(
    *,
    period_days: int,
    order_count: int,
    valid_order_count: int,
    attendance_days: int,
    hire_date: date | None,
    period_end: date,
    manual_bonus: Decimal,
    manual_penalty: Decimal,
    employ_type: str,
    biz_date: date | None = None,
) -> dict[str, Any]:
    """周期聚合上下文（跨段不重置的部分）"""
    ctx: dict[str, Any] = {
        '周期单量': float(valid_order_count),
        '周期有效单量': float(valid_order_count),
        '周期总单量': float(order_count),
        '周期天数': float(period_days),
        '出勤天数': float(attendance_days),
        '工龄月数': float(tenure_months(hire_date, period_end)),
        '入职天数': float(tenure_days(hire_date, period_end)),
        '本期手工奖': float(q2(manual_bonus)),
        '本期手工惩': float(q2(manual_penalty)),
        '用工类型': employ_type,
        '日单量': 0.0,
        '日总单量': 0.0,
        '日有效单量': 0.0,
        '本期已计金额': 0.0,
        '本期逐单金额': 0.0,
        '方案期内单量': 0.0,
        '方案生效天数': 0.0,
    }
    if biz_date is not None:
        ctx['日期'] = biz_date.isoformat()
    return ctx


def build_segment_context(
    period_ctx: dict[str, Any],
    *,
    plan_order_count: int,
    segment_days: int,
    accrued_gross: Decimal,
    per_order_total: Decimal,
) -> dict[str, Any]:
    """段上下文 = 周期上下文 ∪ 段内变量"""
    ctx = dict(period_ctx)
    ctx['方案期内单量'] = float(plan_order_count)
    ctx['方案生效天数'] = float(segment_days)
    ctx['本期已计金额'] = float(q2(accrued_gross))
    ctx['本期逐单金额'] = float(q2(per_order_total))
    return ctx


def trace_variables(expr: str, names: dict[str, Any]) -> dict[str, Any]:
    """抽取表达式用到的变量，时刻格式化为 HH:MM"""
    used: dict[str, Any] = {}
    for name in ALL_FIELD_NAMES:
        if name in expr and name in names:
            value = names[name]
            spec = get_field(name)
            if spec is not None and spec.type == 'time':
                minutes = to_minutes(value)
                if minutes is None:
                    used[name] = None
                else:
                    total = int(minutes)
                    used[name] = f'{total // 60:02d}:{total % 60:02d}'
            elif name in NUMBER_FIELDS and isinstance(value, float):
                used[name] = round(value, 4)
            else:
                used[name] = value
    return used
