from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import Field

from backend.common.schema import SchemaBase


class TrialSegmentOrderCount(SchemaBase):
    """试算各方案段内单量"""

    plan_version_id: int = Field(description='方案版本 ID')
    start_date: date = Field(description='段起')
    end_date: date = Field(description='段止')
    plan_order_count: int = Field(description='方案期内单量')


class TrialSummary(SchemaBase):
    """试算摘要"""

    order_count: int = Field(description='单量')
    valid_order_count: int = Field(0, description='周期有效单量（整期 completed）')
    plan_order_count: int = Field(0, description='方案期内单量（各段合计；单段试算等于该段）')
    segment_order_counts: list[TrialSegmentOrderCount] = Field(
        default_factory=list,
        description='各方案段方案期内单量明细（跨段换绑时对照用）',
    )
    gross: Decimal = Field(description='应发')
    deduction_total: Decimal = Field(description='代扣')
    net: Decimal = Field(description='实发')
    per_order_total: Decimal = Field(description='逐单项合计')
    daily_total: Decimal = Field(description='按日项合计')
    period_total: Decimal = Field(description='周期项合计')
    manual_bonus: Decimal = Field(description='手工奖')
    manual_penalty: Decimal = Field(description='手工惩')
    bonus_total: Decimal | None = Field(None, description='手工奖（别名）')
    penalty_total: Decimal | None = Field(None, description='手工惩（别名）')
    advance_deduction: Decimal = Field(Decimal('0.00'), description='预支抵扣（试算为 0）')
    advance_deductible: Decimal = Field(Decimal('0.00'), description='可抵扣预支金额参考值')
    warnings: list[str] = Field(default_factory=list, description='告警')


class TrialPerOrderItem(SchemaBase):
    """试算逐单项"""

    name: str = Field(description='项名称')
    amount: Decimal = Field(description='金额')
    calc_trace: dict[str, Any] = Field(default_factory=dict, description='计算过程')


class TrialPerOrderRow(SchemaBase):
    """试算逐单行"""

    order_no: str | None = Field(None, description='订单号')
    order_id: int | None = Field(None, description='订单 ID')
    biz_date: date | None = Field(None, description='业务日期')
    items: list[TrialPerOrderItem] = Field(default_factory=list, description='命中项')


class TrialDailyRow(SchemaBase):
    """试算按日行"""

    biz_date: date = Field(description='业务日期')
    order_count: int = Field(description='单量')
    amount: Decimal = Field(description='金额')
    day_status: str | None = Field(None, description='日状态')
    items: list[TrialPerOrderItem] = Field(default_factory=list, description='按日项')


class TrialPeriodItem(SchemaBase):
    """试算周期项"""

    name: str = Field(description='项名称')
    amount: Decimal = Field(description='金额')
    calc_trace: dict[str, Any] = Field(default_factory=dict, description='计算过程')
    plan_version_id: int | None = Field(None, description='方案版本 ID')


class TrialResult(SchemaBase):
    """试算返回"""

    passed: bool = Field(True, description='是否成功')
    trial_hash: str | None = Field(None, description='试算哈希')
    mode: str = Field('full_version', description='试算模式')
    mode_label: str = Field('整版试算', description='试算模式中文')
    matches_official_calculate: bool = Field(
        False,
        description='绑定感知试算时与正式 calculate 同源（应发对拍；预支仍不扣）',
    )
    summary: TrialSummary
    per_order: list[TrialPerOrderRow] = Field(default_factory=list, description='逐单明细')
    daily: list[TrialDailyRow] = Field(default_factory=list, description='按日汇总')
    period_items: list[TrialPeriodItem] = Field(default_factory=list, description='周期项')
    warnings: list[str] = Field(default_factory=list, description='告警')
    adjustments: list[dict[str, Any]] = Field(default_factory=list, description='手工奖惩')
