from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import ConfigDict, Field, computed_field, field_validator

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import SubjectDirection
from backend.plugin.rider_salary.schema.limits import (
    LEN_REMARK,
    MAX_ADJUSTMENT_BATCH,
    MONEY_DIGITS,
    MONEY_MAX,
    MONEY_PLACES,
    zh_list,
    zh_money,
    zh_str,
)


class AdjustmentSchemaBase(SchemaBase):
    """奖惩记录基础模型"""

    rider_id: int = Field(description='骑手 ID')
    biz_date: date = Field(description='业务日期')
    subject_id: int = Field(description='科目 ID')
    amount: Decimal = Field(description='金额（正数；上期补差允许负数）')
    remark: str = Field(description='备注')


class CreateAdjustmentParam(AdjustmentSchemaBase):
    """创建奖惩记录参数"""

    amount: Annotated[Decimal, zh_money('金额', signed=True)] = Field(
        ge=-MONEY_MAX,
        le=MONEY_MAX,
        max_digits=MONEY_DIGITS,
        decimal_places=MONEY_PLACES,
        description='金额（正数；上期补差允许负数）',
    )
    remark: Annotated[str, zh_str('备注', LEN_REMARK, min_length=1)] = Field(
        min_length=1, max_length=LEN_REMARK, description='备注'
    )


class BatchCreateAdjustmentParam(SchemaBase):
    """批量创建奖惩记录参数"""

    items: Annotated[list[CreateAdjustmentParam], zh_list('批量条数', MAX_ADJUSTMENT_BATCH)] = Field(
        max_length=MAX_ADJUSTMENT_BATCH, description='奖惩记录列表'
    )

    @field_validator('items')
    @classmethod
    def limit_items(cls, value: list[CreateAdjustmentParam]) -> list[CreateAdjustmentParam]:
        """限制批量条数"""
        if len(value) > MAX_ADJUSTMENT_BATCH:
            raise ValueError(f'批量条数不能超过 {MAX_ADJUSTMENT_BATCH} 条')
        return value


class UpdateAdjustmentParam(SchemaBase):
    """更新奖惩记录参数"""

    rider_id: int | None = Field(None, description='骑手 ID')
    biz_date: date | None = Field(None, description='业务日期')
    subject_id: int | None = Field(None, description='科目 ID')
    amount: Annotated[Decimal | None, zh_money('金额', signed=True)] = Field(
        None,
        ge=-MONEY_MAX,
        le=MONEY_MAX,
        max_digits=MONEY_DIGITS,
        decimal_places=MONEY_PLACES,
        description='金额',
    )
    remark: Annotated[str | None, zh_str('备注', LEN_REMARK, min_length=1)] = Field(
        None, min_length=1, max_length=LEN_REMARK, description='备注'
    )
    reason: Annotated[str, zh_str('操作原因', LEN_REMARK, min_length=1)] = Field(
        min_length=1, max_length=LEN_REMARK, description='操作原因'
    )


class DeleteAdjustmentParam(SchemaBase):
    """删除奖惩记录参数"""

    reason: Annotated[str, zh_str('操作原因', LEN_REMARK, min_length=1)] = Field(
        min_length=1, max_length=LEN_REMARK, description='操作原因'
    )


class GetAdjustmentDetail(AdjustmentSchemaBase):
    """奖惩记录详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='奖惩记录 ID')
    site_id: int = Field(description='站点 ID')
    signed_amount: Decimal | None = Field(None, description='带符号金额')
    period_id: int | None = Field(None, description='结算周期 ID')
    is_locked: bool = Field(description='是否锁账')
    operator_id: int | None = Field(None, description='操作人 ID')
    rider_job_no: str | None = Field(None, description='骑手工号')
    rider_name: str | None = Field(None, description='骑手姓名')
    subject_name: str | None = Field(None, description='科目名称')
    direction: str | None = Field(None, description='科目方向')
    hint: str | None = Field(None, description='提示')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')

    @computed_field  # type: ignore[prop-decorator]
    @property
    def direction_label(self) -> str | None:
        """方向中文"""
        if not self.direction:
            return None
        try:
            return SubjectDirection(self.direction).label
        except ValueError:
            return self.direction
