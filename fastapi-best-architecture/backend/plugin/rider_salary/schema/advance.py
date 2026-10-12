from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import ConfigDict, Field, computed_field

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import AdvanceStatus, DeductStatus
from backend.plugin.rider_salary.schema.limits import (
    LEN_ADVANCE_REASON,
    LEN_REMARK,
    LEN_STATUS,
    MONEY_DIGITS,
    MONEY_MAX,
    MONEY_PLACES,
    zh_money,
    zh_str,
)


class AdvanceActionParam(SchemaBase):
    """预支审核备注"""

    remark: Annotated[str | None, zh_str('备注', LEN_REMARK)] = Field(None, max_length=LEN_REMARK, description='备注')
    expected_status: Annotated[str | None, zh_str('期望状态', LEN_STATUS)] = Field(
        None,
        max_length=LEN_STATUS,
        description='期望的当前状态。与库中状态不一致时返回 409，不重复执行',
    )


class AdvanceReasonParam(SchemaBase):
    """预支驳回 / 取消"""

    reason: Annotated[str, zh_str('操作原因', LEN_REMARK, min_length=1)] = Field(
        min_length=1, max_length=LEN_REMARK, description='操作原因'
    )
    expected_status: Annotated[str | None, zh_str('期望状态', LEN_STATUS)] = Field(
        None,
        max_length=LEN_STATUS,
        description='期望的当前状态。与库中状态不一致时返回 409，不重复执行',
    )


class CreateMeAdvanceParam(SchemaBase):
    """骑手提交预支"""

    amount: Annotated[Decimal, zh_money('预支金额')] = Field(
        ge=0,
        le=MONEY_MAX,
        max_digits=MONEY_DIGITS,
        decimal_places=MONEY_PLACES,
        description='预支金额',
    )
    reason: Annotated[str, zh_str('申请原因', LEN_ADVANCE_REASON, min_length=1)] = Field(
        min_length=1, max_length=LEN_ADVANCE_REASON, description='申请原因'
    )


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
