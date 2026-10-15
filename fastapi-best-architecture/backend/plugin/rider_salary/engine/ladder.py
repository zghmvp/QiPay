from decimal import Decimal, InvalidOperation
from typing import Any

MODE_FULL = '全量落档'
MODE_PROGRESSIVE = '分段累进'
PRICING_UNIT = '按单价'
PRICING_FIXED = '固定金额'

Tier = tuple[Decimal, Decimal | None, Decimal]


def to_decimal(value: Any) -> Decimal:
    """把 int、str、Decimal、float 转为 Decimal。

    float 走 ``Decimal(str(value))``，避免二进制小数误差。
    None 与空串不在这里当成 0。
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        if not value.strip():
            raise ValueError('空数值')
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise ValueError('数值无效') from exc
    raise TypeError(f'无法转换为数值：{type(value).__name__}')


def to_decimal_or_zero(value: Any) -> Decimal:
    """空值（None、空白串）视为 0，其余同 to_decimal。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return Decimal(0)
    return to_decimal(value)


def _normalize_tiers(tiers: list[Any]) -> list[Tier]:
    result: list[Tier] = []
    for item in tiers:
        if isinstance(item, dict):
            low = to_decimal_or_zero(item.get('下限'))
            raw_high = item.get('上限')
            high = None if raw_high is None else to_decimal(raw_high)
            rate = to_decimal_or_zero(item.get('值'))
        else:
            low = to_decimal_or_zero(item[0])
            raw_high = item[1]
            high = None if raw_high is None else to_decimal(raw_high)
            rate = to_decimal_or_zero(item[2])
        result.append((low, high, rate))
    return result


def find_tier(value: Decimal, tiers: list[Tier]) -> Tier | None:
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
    :return: 金额（未四舍五入，Decimal）
    """
    amount = to_decimal_or_zero(value)
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
