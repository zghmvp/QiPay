from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import ConfigDict, Field, computed_field, model_validator

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import AdvanceStatus, DeductStatus


class AdvanceActionParam(SchemaBase):
    """预支审核备注"""

    remark: str | None = Field(None, description='备注')


class AdvanceReasonParam(SchemaBase):
    """预支驳回 / 取消"""

    reason: str = Field(description='操作原因')


class CreateMeAdvanceParam(SchemaBase):
    """骑手提交预支"""

    amount: Decimal = Field(description='预支金额')
    reason: str = Field(description='申请原因')


class AdvanceTimelineItem(SchemaBase):
    """预支操作时间线"""

    operate_time: datetime = Field(description='操作时间')
    operator_name: str = Field(description='操作人')
    action: str = Field(description='动作')
    reason: str | None = Field(None, description='原因')
    description: str | None = Field(None, description='描述')


class GetAdvanceDetail(SchemaBase):
    """预支单详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='预支单 ID')
    rider_id: int = Field(description='骑手 ID')
    site_id: int = Field(description='站点 ID')
    amount: Decimal = Field(description='预支金额')
    reason: str = Field(description='原因')
    status: str = Field(description='状态')
    approver_id: int | None = Field(None, description='审核人 ID')
    approve_time: datetime | None = Field(None, description='审核时间')
    approve_remark: str | None = Field(None, description='审核备注')
    paid_by: int | None = Field(None, description='发放标记人 ID')
    paid_time: datetime | None = Field(None, description='发放时间')
    deducted_amount: Decimal = Field(description='已抵扣')
    remaining_amount: Decimal | None = Field(None, description='待抵扣')
    deduct_status: str = Field(description='抵扣状态')
    submit_time: datetime | None = Field(None, description='申请时间')
    cancel_time: datetime | None = Field(None, description='取消时间')
    rider_job_no: str | None = Field(None, description='工号')
    rider_name: str | None = Field(None, description='姓名')
    site_name: str | None = Field(None, description='站点')
    approver_name: str | None = Field(None, description='审核人')
    paid_by_name: str | None = Field(None, description='发放标记人')
    timeline: list[AdvanceTimelineItem] = Field(default_factory=list, description='操作时间线')
    created_time: datetime | None = Field(None, description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_label(self) -> str:
        """状态中文"""
        try:
            return AdvanceStatus(self.status).label
        except ValueError:
            return str(self.status)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def deduct_status_label(self) -> str:
        """抵扣状态中文"""
        try:
            return DeductStatus(self.deduct_status).label
        except ValueError:
            return str(self.deduct_status)


class SaveAdvancePolicyParam(SchemaBase):
    """保存预支规则"""

    site_id: int = Field(description='站点 ID，0 表示全局默认')
    amount_mode: Literal['percent', 'fixed'] = Field(description='额度方式：percent 按预估实发百分比，fixed 固定额度')
    percent: Decimal = Field(description='预估实发百分比，0–100')
    fixed_amount: Decimal = Field(description='固定额度')
    max_amount: Decimal | None = Field(None, description='绝对封顶，空表示不额外封顶')
    monthly_max_count: int = Field(description='每月预支次数上限，含待审核、待发放、已发放')
    min_tenure_days: int = Field(description='入职满多少天才能预支')
    min_completed_orders: int = Field(description='当前周期至少完成的配送完成订单数')
    min_amount: Decimal = Field(description='单笔最低金额')

    @model_validator(mode='after')
    def _check_ranges(self) -> 'SaveAdvancePolicyParam':
        if self.percent < 0 or self.percent > 100:
            raise ValueError('百分比需在 0 到 100 之间')
        if self.amount_mode == 'percent' and self.percent <= 0:
            raise ValueError('按百分比预支时，百分比必须大于 0')
        if self.amount_mode == 'fixed' and self.fixed_amount <= 0:
            raise ValueError('固定额度必须大于 0')
        if self.fixed_amount < 0:
            raise ValueError('固定额度不能为负数')
        if self.max_amount is not None and self.max_amount < 0:
            raise ValueError('封顶金额不能为负数')
        if self.monthly_max_count < 0 or self.monthly_max_count > 31:
            raise ValueError('每月次数上限需在 0 到 31 之间，0 表示禁止预支')
        if self.min_tenure_days < 0:
            raise ValueError('入职天数不能为负数')
        if self.min_completed_orders < 0:
            raise ValueError('完成订单数不能为负数')
        if self.min_amount <= 0:
            raise ValueError('单笔最低金额必须大于 0')
        return self


class GetAdvancePolicy(SaveAdvancePolicyParam):
    """预支规则详情"""

    source: Literal['site', 'global', 'builtin'] = Field(description='规则来源：站点、全局、系统默认')
    site_name: str = Field(description='站点名称，全局时为全局默认')
