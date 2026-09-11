import math

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from backend.plugin.rider_salary.engine.ladder import ladder as ladder_impl
from backend.utils.timezone import timezone

FUNCTION_META: tuple[dict[str, Any], ...] = (
    {
        'name': '最大值',
        'signature': '最大值(*args)',
        'description': '返回参数中的最大值',
    },
    {
        'name': '最小值',
        'signature': '最小值(*args)',
        'description': '返回参数中的最小值',
    },
    {
        'name': '取整',
        'signature': '取整(x)',
        'description': '向下取整为整数',
    },
    {
        'name': '向上取整',
        'signature': '向上取整(x)',
        'description': '向上取整为整数',
    },
    {
        'name': '四舍五入',
        'signature': '四舍五入(x, 位数=2)',
        'description': '按指定小数位四舍五入（ROUND_HALF_UP）',
    },
    {
        'name': '绝对值',
        'signature': '绝对值(x)',
        'description': '返回绝对值',
    },
)

WHITELIST_FUNCTION_NAMES: frozenset[str] = frozenset({
    '最大值',
    '最小值',
    '取整',
    '向上取整',
    '四舍五入',
    '绝对值',
    '在时段内',
    '不在时段内',
    '在区间内',
    '不在区间内',
    '阶梯',
    '时刻分钟',
})


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    return float(str(value))


def fn_max(*args: Any) -> float:
    """最大值(*args)"""
    if not args:
        return 0.0
    return max(_to_float(item) for item in args)


def fn_min(*args: Any) -> float:
    """最小值(*args)"""
    if not args:
        return 0.0
    return min(_to_float(item) for item in args)


def fn_floor(x: Any) -> int:
    """取整(x) 向下取整"""
    return math.floor(_to_float(x))


def fn_ceil(x: Any) -> int:
    """向上取整(x)"""
    return math.ceil(_to_float(x))


def fn_round(x: Any, 位数: int = 2) -> float:  # ruff: ignore[invalid-argument-name]
    """四舍五入(x, 位数=2)"""
    digits = int(位数)
    quant = Decimal(1) if digits <= 0 else Decimal(1).scaleb(-digits)
    return float(Decimal(str(_to_float(x))).quantize(quant, rounding=ROUND_HALF_UP))


def fn_abs(x: Any) -> float:
    """绝对值(x)"""
    return abs(_to_float(x))


def to_minutes(value: Any) -> float | None:
    """将时刻转为自 0 点起的分钟数；无法解析返回 None。datetime 先转到应用时区再取时分。"""
    if value is None or value is False:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = timezone.from_datetime(value)
        return float(value.hour * 60 + value.minute)
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    if ':' in text:
        parts = text.split(':')
        try:
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            return None
        return float(hour * 60 + minute)
    try:
        return float(text)
    except ValueError:
        return None


def fn_minutes(value: Any) -> float:
    """时刻分钟(t)，供内部比较"""
    minutes = to_minutes(value)
    return 0.0 if minutes is None else minutes


def in_time_range(t: Any, start: Any, end: Any) -> bool:
    """在时段内(t, 起, 止)，支持跨午夜；两端含"""
    current = to_minutes(t)
    start_m = to_minutes(start)
    end_m = to_minutes(end)
    if current is None or start_m is None or end_m is None:
        return False
    if start_m <= end_m:
        return start_m <= current <= end_m
    return current >= start_m or current <= end_m


def not_in_time_range(t: Any, start: Any, end: Any) -> bool:
    """不在时段内"""
    return not in_time_range(t, start, end)


def in_range(value: Any, low: Any, high: Any) -> bool:
    """在区间内(x, a, b)，含端点"""
    if value is None or low is None or high is None:
        return False
    return low <= value <= high


def not_in_range(value: Any, low: Any, high: Any) -> bool:
    """不在区间内"""
    return not in_range(value, low, high)


ENGINE_FUNCTIONS: dict[str, Any] = {
    '最大值': fn_max,
    '最小值': fn_min,
    '取整': fn_floor,
    '向上取整': fn_ceil,
    '四舍五入': fn_round,
    '绝对值': fn_abs,
    '在时段内': in_time_range,
    '不在时段内': not_in_time_range,
    '在区间内': in_range,
    '不在区间内': not_in_range,
    '阶梯': ladder_impl,
    '时刻分钟': fn_minutes,
}


def functions_as_dicts() -> list[dict[str, Any]]:
    """函数元数据"""
    return [dict(item) for item in FUNCTION_META]
