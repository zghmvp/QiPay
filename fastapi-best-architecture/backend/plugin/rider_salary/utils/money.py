from decimal import ROUND_HALF_UP, Decimal


def q2(value: Decimal | float | str) -> Decimal:
    """
    将金额四舍五入到 2 位小数

    :param value: 原始数值
    :return:
    """
    if isinstance(value, Decimal):
        quantized = value
    elif isinstance(value, (int, str)):
        quantized = Decimal(value)
    else:
        quantized = Decimal(str(value))
    return quantized.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
