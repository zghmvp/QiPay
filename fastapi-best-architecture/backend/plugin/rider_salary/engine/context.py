from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from chinese_calendar import is_holiday

from backend.plugin.rider_salary.engine.fields import ALL_FIELD_NAMES, COUNT_FIELDS, DECIMAL_FIELDS, get_field
from backend.plugin.rider_salary.engine.functions import to_minutes
from backend.plugin.rider_salary.engine.numbers import to_count, to_decimal
from backend.plugin.rider_salary.enums import EmployType, OrderStatus
from backend.plugin.rider_salary.utils.money import q2

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


def clip_date_range(
    start: date,
    end: date,
    hire_date: date | None,
    leave_date: date | None,
) -> tuple[date, date] | None:
    """把闭区间裁剪到在职区间，两端都包含。没有交集时返回 None。

    入职日、离职日为空表示该端不裁剪。离职日当天仍在职，次日才不算。

    :param start: 原区间开始
    :param end: 原区间结束
    :param hire_date: 入职日
    :param leave_date: 离职日
    :return: 裁剪后的闭区间；与在职期无交集时为 None
    """
    clipped_start = hire_date if hire_date is not None and hire_date > start else start
    clipped_end = leave_date if leave_date is not None and leave_date < end else end
    if clipped_end < clipped_start:
        return None
    return clipped_start, clipped_end


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


def _duration_minutes(order_time: datetime | None, deliver_time: datetime | None) -> tuple[Decimal, bool]:
    """送达减下单，单位分钟。用微秒换算，不经过 float。"""
    if order_time is None or deliver_time is None:
        return Decimal(0), True
    delta = deliver_time - order_time
    micros = delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
    if micros <= 0:
        return Decimal(0), False
    return Decimal(micros) / Decimal(60_000_000), False


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
    distance = getattr(order, 'distance_km', None)
    weight = getattr(order, 'weight_jin', None)
    ctx: dict[str, Any] = {
        **day_ctx,
        **(rider_ctx or {}),
        '配送距离': to_decimal(0 if distance is None else distance),
        '商品重量': to_decimal(0 if weight is None else weight),
        '订单金额': to_decimal(0 if amount is None else amount),
        '下单时刻': to_minutes(getattr(order, 'order_time', None)),
        '送达时刻': to_minutes(getattr(order, 'deliver_time', None)),
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
) -> dict[str, Any]:
    """周期聚合上下文（跨段不重置的部分）。

    不含「日期」和三个日单量：周期阶段没有某一天的语义。
    这里的用工类型只是占位，算薪按段末从用工历史覆盖。
    """
    return {
        '周期单量': int(valid_order_count),
        '周期有效单量': int(valid_order_count),
        '周期总单量': int(order_count),
        '周期天数': int(period_days),
        '出勤天数': int(attendance_days),
        '工龄月数': tenure_months(hire_date, period_end),
        '入职天数': tenure_days(hire_date, period_end),
        '本期手工奖': q2(manual_bonus),
        '本期手工惩': q2(manual_penalty),
        '用工类型': employ_type,
        '本期已计金额': Decimal(0),
        '本期逐单金额': Decimal(0),
        '方案期内单量': 0,
        '方案生效天数': 0,
    }


def build_segment_context(
    period_ctx: dict[str, Any],
    *,
    plan_order_count: int,
    segment_days: int,
    accrued_gross: Decimal,
    per_order_total: Decimal,
    employ_type: str | None = None,
) -> dict[str, Any]:
    """段上下文 = 周期上下文 ∪ 段内变量。

    employ_type 给出时覆盖周期上下文里的用工类型。调用方应按段末日期从用工历史取值。
    """
    ctx = dict(period_ctx)
    ctx['方案期内单量'] = int(plan_order_count)
    ctx['方案生效天数'] = int(segment_days)
    ctx['本期已计金额'] = q2(accrued_gross)
    ctx['本期逐单金额'] = q2(per_order_total)
    if employ_type is not None:
        ctx['用工类型'] = employ_type
    return ctx


def _trace_decimal(value: Any) -> str:
    """序列化 calc_trace 时，把金额、距离、单价收成十进制字符串。"""
    return format(to_decimal(value), 'f')


def trace_variables(expr: str, names: dict[str, Any]) -> dict[str, Any]:
    """抽取表达式用到的变量。时刻格式化为 HH:MM；金额和距离只在这里变成字符串。"""
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
                    used[name] = f'{minutes // 60:02d}:{minutes % 60:02d}'
            elif name in COUNT_FIELDS:
                used[name] = to_count(value)
            elif name in DECIMAL_FIELDS or isinstance(value, Decimal):
                used[name] = _trace_decimal(value)
            else:
                used[name] = value
    return used
