from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field, field_validator

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import EnableStatus, PlanModeTag
from backend.plugin.rider_salary.schema.limits import (
    LEN_CODE_64,
    LEN_COLOR,
    LEN_NAME_64,
    LEN_PLAN_DESC,
    LEN_REMARK,
    LEN_SHORT_NAME,
    require_hex_color,
    zh_str,
)


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

    code: Annotated[str, zh_str('方案编码', LEN_CODE_64, min_length=1)] = Field(
        min_length=1, max_length=LEN_CODE_64, description='方案编码'
    )
    name: Annotated[str, zh_str('方案名称', LEN_NAME_64, min_length=1)] = Field(
        min_length=1, max_length=LEN_NAME_64, description='方案名称'
    )
    short_name: Annotated[str, zh_str('短名', LEN_SHORT_NAME, min_length=1)] = Field(
        min_length=1, max_length=LEN_SHORT_NAME, description='日历色带短名，不超过 6 个字'
    )
    color: Annotated[str, zh_str('颜色', LEN_COLOR)] = Field(max_length=LEN_COLOR, description='色带颜色')
    description: Annotated[str | None, zh_str('方案说明', LEN_PLAN_DESC)] = Field(
        None, max_length=LEN_PLAN_DESC, description='方案说明'
    )

    @field_validator('color')
    @classmethod
    def check_color(cls, value: str) -> str:
        """校验十六进制颜色"""
        require_hex_color(value)
        return value


class UpdatePlanParam(SchemaBase):
    """更新方案参数"""

    code: Annotated[str | None, zh_str('方案编码', LEN_CODE_64, min_length=1)] = Field(
        None, min_length=1, max_length=LEN_CODE_64, description='方案编码'
    )
    name: Annotated[str | None, zh_str('方案名称', LEN_NAME_64, min_length=1)] = Field(
        None, min_length=1, max_length=LEN_NAME_64, description='方案名称'
    )
    short_name: Annotated[str | None, zh_str('短名', LEN_SHORT_NAME, min_length=1)] = Field(
        None, min_length=1, max_length=LEN_SHORT_NAME, description='日历色带短名，不超过 6 个字'
    )
    color: Annotated[str | None, zh_str('颜色', LEN_COLOR)] = Field(None, max_length=LEN_COLOR, description='色带颜色')
    description: Annotated[str | None, zh_str('方案说明', LEN_PLAN_DESC)] = Field(
        None, max_length=LEN_PLAN_DESC, description='方案说明'
    )
    status: EnableStatus | None = Field(None, description='状态')

    @field_validator('color')
    @classmethod
    def check_color(cls, value: str | None) -> str | None:
        """校验十六进制颜色"""
        return require_hex_color(value)


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
    remark: Annotated[str | None, zh_str('备注', LEN_REMARK)] = Field(None, max_length=LEN_REMARK, description='备注')


class UpdatePlanVersionParam(SchemaBase):
    """更新方案版本基本信息"""

    mode_tag: PlanModeTag | None = Field(None, description='计薪模式标签')
    remark: Annotated[str | None, zh_str('备注', LEN_REMARK)] = Field(None, max_length=LEN_REMARK, description='备注')


class DisablePlanVersionParam(SchemaBase):
    """停用方案版本"""

    reason: Annotated[str, zh_str('停用原因', LEN_REMARK, min_length=1)] = Field(
        min_length=1, max_length=LEN_REMARK, description='停用原因'
    )
