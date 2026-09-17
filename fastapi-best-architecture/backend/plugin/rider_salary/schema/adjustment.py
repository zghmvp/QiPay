from datetime import date, datetime
from decimal import Decimal

from pydantic import ConfigDict, Field, computed_field

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import SubjectDirection


class AdjustmentSchemaBase(SchemaBase):
    """奖惩记录基础模型"""

    rider_id: int = Field(description='骑手 ID')
    biz_date: date = Field(description='业务日期')
    subject_id: int = Field(description='科目 ID')
    amount: Decimal = Field(description='金额（正数；上期补差允许负数）')
    remark: str = Field(description='备注')


class CreateAdjustmentParam(AdjustmentSchemaBase):
    """创建奖惩记录参数"""


class BatchAdjustmentItemParam(SchemaBase):
    """批量奖惩行（允许半填，由服务层跳过未完整行）"""

    rider_id: int | None = Field(None, description='骑手 ID')
    biz_date: date | None = Field(None, description='业务日期')
    subject_id: int | None = Field(None, description='科目 ID')
    amount: Decimal | None = Field(None, description='金额（正数；上期补差允许负数）')
    remark: str | None = Field(None, description='备注')


class BatchCreateAdjustmentParam(SchemaBase):
    """批量创建奖惩记录参数"""

    items: list[BatchAdjustmentItemParam] = Field(description='奖惩记录列表')


class UpdateAdjustmentParam(SchemaBase):
    """更新奖惩记录参数"""

    rider_id: int | None = Field(None, description='骑手 ID')
    biz_date: date | None = Field(None, description='业务日期')
    subject_id: int | None = Field(None, description='科目 ID')
    amount: Decimal | None = Field(None, description='金额')
    remark: str | None = Field(None, description='备注')
    reason: str = Field(description='操作原因')


class DeleteAdjustmentParam(SchemaBase):
    """删除奖惩记录参数"""

    reason: str = Field(description='操作原因')


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


class BatchCreateAdjustmentResult(SchemaBase):
    """批量录入奖惩结果"""

    created_count: int = Field(description='已录入行数')
    skipped_incomplete_count: int = Field(description='跳过未完整行数')
    items: list[GetAdjustmentDetail] = Field(default_factory=list, description='已录入记录')
    message: str = Field(description='中文结果说明')
