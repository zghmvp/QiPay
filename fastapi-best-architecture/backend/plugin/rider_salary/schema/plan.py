from datetime import datetime

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import EnableStatus, PlanModeTag


class PlanSchemaBase(SchemaBase):
    """方案基础"""

    code: str = Field(description='方案编码')
    name: str = Field(description='方案名称')
    short_name: str = Field(description='日历色带短名')
    color: str = Field(description='色带颜色')
    description: str | None = Field(None, description='方案说明')
    status: EnableStatus = Field(EnableStatus.enable, description='状态')


class CreatePlanParam(PlanSchemaBase):
    """创建方案参数"""


class UpdatePlanParam(SchemaBase):
    """更新方案参数"""

    code: str | None = Field(None, description='方案编码')
    name: str | None = Field(None, description='方案名称')
    short_name: str | None = Field(None, description='日历色带短名')
    color: str | None = Field(None, description='色带颜色')
    description: str | None = Field(None, description='方案说明')
    status: EnableStatus | None = Field(None, description='状态')


class GetPlanDetail(PlanSchemaBase):
    """方案详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='方案 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')


class GetPlanBrief(SchemaBase):
    """方案摘要"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='方案 ID')
    name: str = Field(description='方案名称')
    short_name: str = Field(description='日历色带短名')
    color: str = Field(description='色带颜色')
    code: str = Field(description='方案编码')


class GetActivePlanVersion(SchemaBase):
    """启用版本下拉"""

    id: int = Field(description='版本 ID')
    plan_name: str = Field(description='方案名称')
    short_name: str = Field(description='短名')
    color: str = Field(description='颜色')
    version_no: int = Field(description='版本号')


class CreatePlanVersionParam(SchemaBase):
    """创建方案版本"""

    plan_id: int = Field(description='所属方案 ID')
    mode_tag: PlanModeTag = Field(PlanModeTag.custom, description='计薪模式标签')
    remark: str | None = Field(None, description='备注')


class UpdatePlanVersionParam(SchemaBase):
    """更新方案版本基本信息"""

    mode_tag: PlanModeTag | None = Field(None, description='计薪模式标签')
    remark: str | None = Field(None, description='备注')


class DisablePlanVersionParam(SchemaBase):
    """停用方案版本"""

    reason: str = Field(description='停用原因')
