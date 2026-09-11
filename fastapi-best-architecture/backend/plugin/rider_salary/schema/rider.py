from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import ConfigDict, Field, computed_field

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import BindingType, CycleType, EmployType, RiderStatus


class RiderSchemaBase(SchemaBase):
    """骑手基础模型"""

    job_no: str = Field(description='工号')
    name: str = Field(description='姓名')
    phone: str | None = Field(None, description='手机')
    site_id: int = Field(description='所属站点 ID')
    employ_type: EmployType = Field(EmployType.part_time, description='当前用工类型')
    hire_date: date = Field(description='入职日期')
    leave_date: date | None = Field(None, description='离职日期')
    status: RiderStatus = Field(RiderStatus.on_job, description='状态')
    advance_limit: Decimal | None = Field(None, description='预支上限（骑手级）')
    settle_cycle_override: CycleType | None = Field(None, description='结算周期覆盖')
    cycle_config_override: dict[str, Any] | None = Field(None, description='周期配置覆盖')
    remark: str | None = Field(None, description='备注')


class CreateRiderParam(RiderSchemaBase):
    """创建骑手参数"""


class UpdateRiderParam(SchemaBase):
    """更新骑手参数"""

    job_no: str | None = Field(None, description='工号')
    name: str | None = Field(None, description='姓名')
    phone: str | None = Field(None, description='手机')
    site_id: int | None = Field(None, description='所属站点 ID')
    employ_type: EmployType | None = Field(None, description='当前用工类型')
    hire_date: date | None = Field(None, description='入职日期')
    leave_date: date | None = Field(None, description='离职日期')
    status: RiderStatus | None = Field(None, description='状态')
    advance_limit: Decimal | None = Field(None, description='预支上限（骑手级）')
    settle_cycle_override: CycleType | None = Field(None, description='结算周期覆盖')
    cycle_config_override: dict[str, Any] | None = Field(None, description='周期配置覆盖')
    remark: str | None = Field(None, description='备注')
    reason: str | None = Field(None, description='操作原因（更换站点时必填）')


class GetRiderDetail(RiderSchemaBase):
    """骑手详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='骑手 ID')
    user_id: int | None = Field(None, description='绑定登录账号')
    site_name: str | None = Field(None, description='站点名称')
    plan_version_id: int | None = Field(None, description='当前生效方案版本 ID')
    plan_short_name: str | None = Field(None, description='当前绑定方案短名')
    plan_color: str | None = Field(None, description='当前方案色带颜色')
    account_status: int | None = Field(None, description='账号状态（0 停用 1 启用）')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_label(self) -> str:
        """状态中文"""
        try:
            return RiderStatus(self.status).label
        except ValueError:
            return str(self.status)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def employ_type_label(self) -> str:
        """用工类型中文"""
        try:
            return EmployType(self.employ_type).label
        except ValueError:
            return str(self.employ_type)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def account_status_label(self) -> str | None:
        """账号状态中文"""
        if self.user_id is None:
            return '未开通'
        if self.account_status == 0:
            return '停用'
        if self.account_status == 1:
            return '启用'
        return None


class RiderLeaveParam(SchemaBase):
    """骑手离职参数"""

    leave_date: date = Field(description='离职日期')
    reason: str = Field(description='离职原因')


class OpenRiderAccountParam(SchemaBase):
    """开通骑手账号参数"""

    password: str | None = Field(None, description='初始密码')
    reason: str = Field(description='操作原因')


class ResetRiderPasswordParam(SchemaBase):
    """重置骑手密码参数"""

    password: str | None = Field(None, description='新密码')
    reason: str | None = Field(None, description='操作原因')


class DisableRiderAccountParam(SchemaBase):
    """停用骑手账号参数"""

    reason: str = Field(description='操作原因')


class EnableRiderAccountParam(SchemaBase):
    """启用骑手账号参数"""

    reason: str | None = Field(None, description='操作原因')


class EmployHistorySchemaBase(SchemaBase):
    """用工类型历史基础模型"""

    employ_type: EmployType = Field(description='用工类型')
    start_date: date = Field(description='开始日期')
    end_date: date | None = Field(None, description='结束日期')
    remark: str | None = Field(None, description='备注')


class CreateEmployHistoryParam(EmployHistorySchemaBase):
    """创建用工类型历史参数"""


class UpdateEmployHistoryParam(SchemaBase):
    """更新用工类型历史参数"""

    employ_type: EmployType | None = Field(None, description='用工类型')
    start_date: date | None = Field(None, description='开始日期')
    end_date: date | None = Field(None, description='结束日期')
    remark: str | None = Field(None, description='备注')


class GetEmployHistoryDetail(EmployHistorySchemaBase):
    """用工类型历史详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='记录 ID')
    rider_id: int = Field(description='骑手 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')

    @computed_field  # type: ignore[prop-decorator]
    @property
    def employ_type_label(self) -> str:
        """用工类型中文"""
        try:
            return EmployType(self.employ_type).label
        except ValueError:
            return str(self.employ_type)


class PlanBindingSchemaBase(SchemaBase):
    """方案绑定基础模型"""

    plan_version_id: int = Field(description='方案版本 ID')
    binding_type: BindingType = Field(description='绑定类型')
    start_date: date = Field(description='生效开始日期')
    end_date: date | None = Field(None, description='生效结束日期')
    remark: str | None = Field(None, description='备注')


class CreatePlanBindingParam(PlanBindingSchemaBase):
    """创建方案绑定参数"""


class UpdatePlanBindingParam(SchemaBase):
    """更新方案绑定参数"""

    plan_version_id: int | None = Field(None, description='方案版本 ID')
    binding_type: BindingType | None = Field(None, description='绑定类型')
    start_date: date | None = Field(None, description='生效开始日期')
    end_date: date | None = Field(None, description='结束日期')
    remark: str | None = Field(None, description='备注')


class GetPlanBindingDetail(PlanBindingSchemaBase):
    """方案绑定详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='绑定 ID')
    rider_id: int = Field(description='骑手 ID')
    plan_short_name: str | None = Field(None, description='方案短名')
    plan_color: str | None = Field(None, description='方案颜色')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')

    @computed_field  # type: ignore[prop-decorator]
    @property
    def binding_type_label(self) -> str:
        """绑定类型中文"""
        try:
            return BindingType(self.binding_type).label
        except ValueError:
            return str(self.binding_type)


class GetEffectivePlanSegment(SchemaBase):
    """按日解析后的生效方案区间"""

    start: date = Field(description='开始日期')
    end: date = Field(description='结束日期')
    plan_version_id: int | None = Field(None, description='方案版本 ID')
    plan_short_name: str | None = Field(None, description='方案短名')
    plan_color: str | None = Field(None, description='方案颜色')
