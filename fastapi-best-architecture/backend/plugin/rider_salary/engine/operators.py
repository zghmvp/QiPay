from backend.plugin.rider_salary.engine.fields import (
    TYPE_BOOL,
    TYPE_DATE,
    TYPE_ENUM,
    TYPE_NUMBER,
    TYPE_TIME,
    FieldSpec,
    get_field,
)

OP_EQ = '='
OP_NE = '≠'
OP_GT = '>'
OP_GE = '≥'
OP_LT = '<'
OP_LE = '≤'
OP_IN_RANGE = '在区间内'
OP_NOT_IN_RANGE = '不在区间内'
OP_IN_TIME = '在时段内'
OP_NOT_IN_TIME = '不在时段内'
OP_IN = '属于'
OP_NOT_IN = '不属于'

OPERATORS_BY_TYPE: dict[str, tuple[str, ...]] = {
    TYPE_NUMBER: (OP_EQ, OP_NE, OP_GT, OP_GE, OP_LT, OP_LE, OP_IN_RANGE, OP_NOT_IN_RANGE),
    TYPE_TIME: (OP_IN_TIME, OP_NOT_IN_TIME, OP_GT, OP_LT),
    TYPE_ENUM: (OP_EQ, OP_NE, OP_IN, OP_NOT_IN),
    TYPE_BOOL: (OP_EQ,),
    TYPE_DATE: (OP_EQ, OP_GT, OP_LT, OP_IN_RANGE),
}

COMPARE_PYTHON: dict[str, str] = {
    OP_EQ: '==',
    OP_NE: '!=',
    OP_GT: '>',
    OP_GE: '>=',
    OP_LT: '<',
    OP_LE: '<=',
}


def operators_as_dicts() -> dict[str, list[str]]:
    """按字段类型返回可用运算符"""
    return {key: list(value) for key, value in OPERATORS_BY_TYPE.items()}


def operators_for_field(name: str) -> list[str]:
    """按字段名返回可用运算符"""
    spec = get_field(name)
    if spec is None:
        return []
    return list(OPERATORS_BY_TYPE.get(spec.type, ()))


def operator_allowed(spec: FieldSpec, operator: str) -> bool:
    """运算符是否可用于该字段类型"""
    return operator in OPERATORS_BY_TYPE.get(spec.type, ())
