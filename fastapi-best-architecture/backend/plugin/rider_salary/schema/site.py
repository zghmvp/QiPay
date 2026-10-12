from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import ConfigDict, Field, computed_field

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import CycleType, EnableStatus, ManagerRole
from backend.plugin.rider_salary.schema.limits import (
    LEN_CODE_32,
    LEN_NAME_64,
    LEN_REMARK,
    MAX_SITE_MANAGERS,
    MONEY_DIGITS,
    MONEY_MAX,
    MONEY_PLACES,
    zh_list,
    zh_money,
    zh_str,
)


class SiteSchemaBase(SchemaBase):
    """站点基础模型"""

    code: str = Field(description='站点编码')
    name: str = Field(description='站点名称')
    settle_cycle: CycleType = Field(CycleType.month, description='结算周期类型')
    cycle_config: dict[str, Any] | None = Field(None, description='周期配置')
    advance_limit: Decimal | None = Field(None, description='预支上限（站点级）')
    dept_id: int | None = Field(None, description='关联部门 ID')
    status: EnableStatus = Field(EnableStatus.enable, description='状态')
    remark: str | None = Field(None, description='备注')


class CreateSiteParam(SiteSchemaBase):
    """创建站点参数"""

    code: Annotated[str, zh_str('站点编码', LEN_CODE_32, min_length=1)] = Field(
        min_length=1, max_length=LEN_CODE_32, description='站点编码'
    )
    name: Annotated[str, zh_str('站点名称', LEN_NAME_64, min_length=1)] = Field(
        min_length=1, max_length=LEN_NAME_64, description='站点名称'
    )
    advance_limit: Annotated[Decimal | None, zh_money('预支上限')] = Field(
        None,
        ge=0,
        le=MONEY_MAX,
        max_digits=MONEY_DIGITS,
        decimal_places=MONEY_PLACES,
        description='预支上限（站点级）',
    )
    remark: Annotated[str | None, zh_str('备注', LEN_REMARK)] = Field(None, max_length=LEN_REMARK, description='备注')


class UpdateSiteParam(SchemaBase):
    """更新站点参数"""

    code: Annotated[str | None, zh_str('站点编码', LEN_CODE_32, min_length=1)] = Field(
        None, min_length=1, max_length=LEN_CODE_32, description='站点编码'
    )
    name: Annotated[str | None, zh_str('站点名称', LEN_NAME_64, min_length=1)] = Field(
        None, min_length=1, max_length=LEN_NAME_64, description='站点名称'
    )
    settle_cycle: CycleType | None = Field(None, description='结算周期类型')
    cycle_config: dict[str, Any] | None = Field(None, description='周期配置')
    advance_limit: Annotated[Decimal | None, zh_money('预支上限')] = Field(
        None,
        ge=0,
        le=MONEY_MAX,
        max_digits=MONEY_DIGITS,
        decimal_places=MONEY_PLACES,
        description='预支上限（站点级）',
    )
    dept_id: int | None = Field(None, description='关联部门 ID')
    status: EnableStatus | None = Field(None, description='状态')
    remark: Annotated[str | None, zh_str('备注', LEN_REMARK)] = Field(None, max_length=LEN_REMARK, description='备注')


class GetSiteDetail(SiteSchemaBase):
    """站点详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='站点 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_label(self) -> str:
        """状态中文"""
        try:
            return EnableStatus(self.status).label
        except ValueError:
            return str(self.status)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def settle_cycle_label(self) -> str:
        """结算周期中文"""
        try:
            return CycleType(self.settle_cycle).label
        except ValueError:
            return str(self.settle_cycle)


class SiteManagerItem(SchemaBase):
    """站点负责人项"""

    user_id: int = Field(description='用户 ID')
    role: ManagerRole = Field(description='负责人角色')


SiteManagerList = Annotated[
    list[SiteManagerItem],
    zh_list('站点负责人', MAX_SITE_MANAGERS),
    Field(max_length=MAX_SITE_MANAGERS, description='站点负责人列表'),
]


class GetSiteManagerDetail(SchemaBase):
    """站点负责人详情"""

    user_id: int = Field(description='用户 ID')
    username: str = Field(description='用户名')
    nickname: str = Field(description='昵称')
    role: str = Field(description='负责人角色')

    @computed_field  # type: ignore[prop-decorator]
    @property
    def role_label(self) -> str:
        """角色中文"""
        try:
            return ManagerRole(self.role).label
        except ValueError:
            return self.role
