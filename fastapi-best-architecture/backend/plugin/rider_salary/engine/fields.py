from dataclasses import dataclass

from backend.plugin.rider_salary.enums import CalcStage, EmployType, OrderStatus

STAGE_PER_ORDER = CalcStage.per_order.value
STAGE_DAILY = CalcStage.daily.value
STAGE_PERIOD = CalcStage.period.value

STAGE_ORDER: dict[str, int] = {
    STAGE_PER_ORDER: 0,
    STAGE_DAILY: 1,
    STAGE_PERIOD: 2,
}

TYPE_NUMBER = 'number'
TYPE_TIME = 'time'
TYPE_ENUM = 'enum'
TYPE_BOOL = 'bool'
TYPE_DATE = 'date'


@dataclass(frozen=True)
class FieldSpec:
    """公式引擎字段定义"""

    name: str
    type: str
    stages: tuple[str, ...]
    unit: str | None
    description: str
    enum_options: tuple[dict[str, str | int], ...] | None = None


_ORDER_STATUS_OPTIONS: tuple[dict[str, str | int], ...] = (
    {'value': OrderStatus.completed.value, 'label': OrderStatus.completed.label},
    {'value': OrderStatus.cancelled.value, 'label': OrderStatus.cancelled.label},
    {'value': OrderStatus.abnormal.value, 'label': OrderStatus.abnormal.label},
    {'value': OrderStatus.refunded.value, 'label': OrderStatus.refunded.label},
)

_WEEKDAY_OPTIONS: tuple[dict[str, str | int], ...] = (
    {'value': 1, 'label': '周一'},
    {'value': 2, 'label': '周二'},
    {'value': 3, 'label': '周三'},
    {'value': 4, 'label': '周四'},
    {'value': 5, 'label': '周五'},
    {'value': 6, 'label': '周六'},
    {'value': 7, 'label': '周日'},
)

_EMPLOY_OPTIONS: tuple[dict[str, str | int], ...] = (
    {'value': EmployType.part_time.value, 'label': EmployType.part_time.label},
    {'value': EmployType.full_time.value, 'label': EmployType.full_time.label},
)

_ALL_STAGES = (STAGE_PER_ORDER, STAGE_DAILY, STAGE_PERIOD)
_ORDER_DAY = (STAGE_PER_ORDER, STAGE_DAILY)
_DAILY_ONLY = (STAGE_DAILY,)

# 周期没有「某一天」。这些字段留在周期阶段时，日期条件恒为假，日单量恒为 0。
PERIOD_STAGE_BANNED_FIELDS: frozenset[str] = frozenset({
    '日期',
    '日单量',
    '日总单量',
    '日有效单量',
})


FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec('配送距离', TYPE_NUMBER, (STAGE_PER_ORDER,), '公里', '订单配送距离'),
    FieldSpec('商品重量', TYPE_NUMBER, (STAGE_PER_ORDER,), '斤', '商品重量'),
    FieldSpec('订单金额', TYPE_NUMBER, (STAGE_PER_ORDER,), '元', '订单金额，供大额订单奖等条件使用'),
    FieldSpec('下单时刻', TYPE_TIME, (STAGE_PER_ORDER,), None, '下单时间的时分，求值时用自 0 点起分钟数'),
    FieldSpec('送达时刻', TYPE_TIME, (STAGE_PER_ORDER,), None, '送达时间的时分；无送达则条件视为假'),
    FieldSpec('配送时长', TYPE_NUMBER, (STAGE_PER_ORDER,), '分钟', '送达时间减下单时间；缺送达按 0 并记 warning'),
    FieldSpec('订单状态', TYPE_ENUM, (STAGE_PER_ORDER,), None, '订单状态', _ORDER_STATUS_OPTIONS),
    FieldSpec('日期', TYPE_DATE, _ORDER_DAY, None, '业务日期，仅逐单和按日阶段可用'),
    FieldSpec('星期', TYPE_ENUM, _ORDER_DAY, None, '周一=1 … 周日=7', _WEEKDAY_OPTIONS),
    FieldSpec('是否节假日', TYPE_BOOL, _ORDER_DAY, None, '中国法定节假日（chinese-calendar，含调休判定）'),
    FieldSpec('是否周末', TYPE_BOOL, _ORDER_DAY, None, '星期六或星期日'),
    FieldSpec('是否恶劣天气', TYPE_BOOL, _ORDER_DAY, None, '来自站点日标记，无记录为否'),
    FieldSpec('是否高温', TYPE_BOOL, _ORDER_DAY, None, '来自站点日标记，无记录为否'),
    FieldSpec('是否大促', TYPE_BOOL, _ORDER_DAY, None, '来自站点日标记，无记录为否'),
    FieldSpec(
        '用工类型', TYPE_ENUM, _ALL_STAGES, None, '逐单和按日取当天，周期取段末；均来自用工历史', _EMPLOY_OPTIONS
    ),
    FieldSpec('日单量', TYPE_NUMBER, _DAILY_ONLY, '单', '当日已完成订单数，仅按日阶段可用（决策补遗#10）'),
    FieldSpec('日总单量', TYPE_NUMBER, _DAILY_ONLY, '单', '当日全部状态订单数，仅按日阶段可用'),
    FieldSpec('日有效单量', TYPE_NUMBER, _DAILY_ONLY, '单', '日单量的别名，当日已完成订单数，仅按日阶段可用'),
    FieldSpec('日逐单金额', TYPE_NUMBER, (STAGE_DAILY,), '元', '当日逐单项进应发合计'),
    FieldSpec('周期单量', TYPE_NUMBER, (STAGE_PERIOD,), '单', '整个结算周期已完成订单数（跨方案段）'),
    FieldSpec('周期总单量', TYPE_NUMBER, (STAGE_PERIOD,), '单', '整个结算周期全部状态订单数'),
    FieldSpec('周期有效单量', TYPE_NUMBER, (STAGE_PERIOD,), '单', '周期单量的别名，整个周期已完成订单数'),
    FieldSpec('方案期内单量', TYPE_NUMBER, (STAGE_PERIOD,), '单', '本方案版本生效区间内已完成订单数'),
    FieldSpec('周期天数', TYPE_NUMBER, (STAGE_PERIOD,), '天', '周期结束日减开始日加 1'),
    FieldSpec('方案生效天数', TYPE_NUMBER, (STAGE_PERIOD,), '天', '本段日历天数'),
    FieldSpec('出勤天数', TYPE_NUMBER, (STAGE_PERIOD,), '天', '周期内有有效单的天数'),
    FieldSpec('本期已计金额', TYPE_NUMBER, (STAGE_PERIOD,), '元', '排序在前且进应发的公式明细之和，不含手工奖惩'),
    FieldSpec('本期逐单金额', TYPE_NUMBER, (STAGE_PERIOD,), '元', '本薪资单已产生的逐单项进应发合计'),
    FieldSpec('本期手工奖', TYPE_NUMBER, (STAGE_PERIOD,), '元', '本周期手工奖进应发合计'),
    FieldSpec('本期手工惩', TYPE_NUMBER, (STAGE_PERIOD,), '元', '本周期手工惩进应发合计（带符号）'),
    FieldSpec('工龄月数', TYPE_NUMBER, (STAGE_PERIOD,), '月', '入职日到周期末的整月数'),
    FieldSpec('入职天数', TYPE_NUMBER, (STAGE_PERIOD,), '天', '入职日到周期末的日历天数（含入职当日）'),
)

FIELD_MAP: dict[str, FieldSpec] = {item.name: item for item in FIELDS}

NUMBER_FIELDS: frozenset[str] = frozenset(item.name for item in FIELDS if item.type == TYPE_NUMBER)
# 金额、距离、重量、时长、已计金额：连续量，求值用 Decimal。
DECIMAL_FIELDS: frozenset[str] = frozenset({
    '配送距离',
    '商品重量',
    '订单金额',
    '配送时长',
    '日逐单金额',
    '本期已计金额',
    '本期逐单金额',
    '本期手工奖',
    '本期手工惩',
})
# 单量、天数、工龄：计数，求值用 int。时刻不在这里，见 TIME_FIELDS。
COUNT_FIELDS: frozenset[str] = frozenset({
    '日单量',
    '日总单量',
    '日有效单量',
    '周期单量',
    '周期总单量',
    '周期有效单量',
    '方案期内单量',
    '周期天数',
    '方案生效天数',
    '出勤天数',
    '工龄月数',
    '入职天数',
})
TIME_FIELDS: frozenset[str] = frozenset(item.name for item in FIELDS if item.type == TYPE_TIME)
ENUM_FIELDS: frozenset[str] = frozenset(item.name for item in FIELDS if item.type == TYPE_ENUM)
BOOL_FIELDS: frozenset[str] = frozenset(item.name for item in FIELDS if item.type == TYPE_BOOL)
DATE_FIELDS: frozenset[str] = frozenset(item.name for item in FIELDS if item.type == TYPE_DATE)

ALL_FIELD_NAMES: frozenset[str] = frozenset(FIELD_MAP)


def get_field(name: str) -> FieldSpec | None:
    """按中文名取字段定义"""
    return FIELD_MAP.get(name)


def field_available(name: str, stage: str) -> bool:
    """字段是否在指定计算阶段可用"""
    spec = FIELD_MAP.get(name)
    return spec is not None and stage in spec.stages


def fields_as_dicts() -> list[dict]:
    """序列化为接口返回结构"""
    result: list[dict] = []
    for item in FIELDS:
        row: dict = {
            'name': item.name,
            'type': item.type,
            'stages': list(item.stages),
            'unit': item.unit,
            'description': item.description,
        }
        if item.enum_options:
            row['enum_options'] = [dict(opt) for opt in item.enum_options]
        result.append(row)
    return result
