from decimal import Decimal
from typing import Any

from backend.plugin.rider_salary.engine.numbers import to_decimal

MODE_FULL = '全量落档'
MODE_PROGRESSIVE = '分段累进'
PRICING_UNIT = '按单价'
PRICING_FIXED = '固定金额'


def _normalize_tiers(tiers: list[Any]) -> list[tuple[Decimal, Decimal | None, Decimal]]:
    result: list[tuple[Decimal, Decimal | None, Decimal]] = []
    for item in tiers:
        if isinstance(item, dict):
            low = to_decimal(item.get('下限'))
            raw_high = item.get('上限')
            high = None if raw_high is None else to_decimal(raw_high)
            rate = to_decimal(item.get('值'))
        else:
            low = to_decimal(item[0])
            raw_high = item[1]
            high = None if raw_high is None else to_decimal(raw_high)
            rate = to_decimal(item[2])
        result.append((low, high, rate))
    return result


def find_tier(
    value: Decimal,
    tiers: list[tuple[Decimal, Decimal | None, Decimal]],
) -> tuple[Decimal, Decimal | None, Decimal] | None:
    """
    含下限、不含上限；最后一档无上限时 >= 下限即命中
    """
    for low, high, rate in tiers:
        if high is None:
            if value >= low:
                return (low, high, rate)
        elif low <= value < high:
            return (low, high, rate)
    return None


def ladder(value: Any, mode: str, pricing: str, tiers: list[Any]) -> Decimal:
    """
    阶梯计价：全量落档/分段累进 × 按单价/固定金额

    :param value: 字段值
    :param mode: 全量落档 / 分段累进
    :param pricing: 按单价 / 固定金额
    :param tiers: [[下限, 上限, 值], ...]，上限 None 表示无穷
    :return: 金额（未四舍五入到分）
    """
    amount = to_decimal(value)
    normalized = _normalize_tiers(tiers)
    if not normalized:
        return Decimal(0)
    if mode == MODE_PROGRESSIVE and pricing == PRICING_FIXED:
        raise ValueError('分段累进模式仅支持按单价计价')
    if mode == MODE_FULL:
        hit = find_tier(amount, normalized)
        if hit is None:
            return Decimal(0)
        _low, _high, rate = hit
        if pricing == PRICING_FIXED:
            return rate
        return amount * rate
    if mode == MODE_PROGRESSIVE:
        total = Decimal(0)
        for low, high, rate in normalized:
            if amount <= low:
                break
            upper = amount if high is None else min(amount, high)
            if upper > low:
                total += (upper - low) * rate
        return total
    raise ValueError(f'不支持的阶梯模式「{mode}」')
