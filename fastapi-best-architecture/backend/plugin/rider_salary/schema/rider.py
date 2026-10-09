from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BeforeValidator, ConfigDict, Field, computed_field, model_validator

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import BindingType, CycleType, EmployType, RiderStatus
from backend.plugin.rider_salary.schema.limits import (
    LEN_NAME_32,
    LEN_PASSWORD,
    LEN_PHONE,
    LEN_REMARK,
    MAX_ID_LIST,
    MONEY_DIGITS,
    MONEY_MAX,
    MONEY_PLACES,
    zh_money,
    zh_str,
)


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

    job_no: Annotated[str, zh_str('工号', LEN_NAME_32, min_length=1)] = Field(
        min_length=1, max_length=LEN_NAME_32, description='工号'
    )
    name: Annotated[str, zh_str('姓名', LEN_NAME_32, min_length=1)] = Field(
        min_length=1, max_length=LEN_NAME_32, description='姓名'
    )
    phone: Annotated[str | None, zh_str('手机', LEN_PHONE)] = Field(None, max_length=LEN_PHONE, description='手机')
    advance_limit: Annotated[Decimal | None, zh_money('预支上限')] = Field(
        None,
        ge=0,
        le=MONEY_MAX,
        max_digits=MONEY_DIGITS,
        decimal_places=MONEY_PLACES,
        description='预支上限（骑手级）',
    )
    remark: Annotated[str | None, zh_str('备注', LEN_REMARK)] = Field(None, max_length=LEN_REMARK, description='备注')


class UpdateRiderParam(SchemaBase):
    """更新骑手参数

    用工类型、在职状态、离职日期不在这里改：用工类型走用工历史，离职走离职接口。
    请求里带上这三项会直接拒绝。
    """

    job_no: Annotated[str | None, zh_str('工号', LEN_NAME_32, min_length=1)] = Field(
        None, min_length=1, max_length=LEN_NAME_32, description='工号'
    )
    name: Annotated[str | None, zh_str('姓名', LEN_NAME_32, min_length=1)] = Field(
        None, min_length=1, max_length=LEN_NAME_32, description='姓名'
    )
    phone: Annotated[str | None, zh_str('手机', LEN_PHONE)] = Field(None, max_length=LEN_PHONE, description='手机')
    site_id: int | None = Field(None, description='所属站点 ID')
    hire_date: date | None = Field(None, description='入职日期')
    advance_limit: Annotated[Decimal | None, zh_money('预支上限')] = Field(
        None,
        ge=0,
        le=MONEY_MAX,
        max_digits=MONEY_DIGITS,
        decimal_places=MONEY_PLACES,
        description='预支上限（骑手级）',
    )
    settle_cycle_override: CycleType | None = Field(None, description='结算周期覆盖')
    cycle_config_override: dict[str, Any] | None = Field(None, description='周期配置覆盖')
    remark: Annotated[str | None, zh_str('备注', LEN_REMARK)] = Field(None, max_length=LEN_REMARK, description='备注')
    reason: Annotated[str | None, zh_str('操作原因', LEN_REMARK)] = Field(
        None, max_length=LEN_REMARK, description='操作原因（更换站点时必填）'
    )

    @model_validator(mode='before')
    @classmethod
    def reject_payroll_facts(cls, data: Any) -> Any:
        """编辑接口不再接收用工类型、状态和离职日期"""
        if isinstance(data, dict):
            blocked = [key for key in ('employ_type', 'status', 'leave_date') if key in data]
            if blocked:
                raise ValueError('用工类型、状态和离职日期请通过用工历史或离职办理修改')
        return data


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
    reason: Annotated[str, zh_str('离职原因', LEN_REMARK, min_length=1)] = Field(
        min_length=1, max_length=LEN_REMARK, description='离职原因'
    )


class RiderLeaveResult(SchemaBase):
    """离职办理结果"""

    hints: list[str] = Field(default_factory=list, description='需管理员继续处理的提示')
    rejected_advance_count: int = Field(description='因离职自动驳回的待审核预支数')
    to_pay_advance_count: int = Field(description='仍待发放、需管理员取消的预支数')


class IssuedRiderPassword(SchemaBase):
    """开户或重置后一次性下发的密码"""

    username: str = Field(description='登录用户名')
    initial_password: str | None = Field(None, description='系统生成的初始密码，仅本次返回')


class OpenRiderAccountParam(SchemaBase):
    """开通骑手账号参数"""

    password: Annotated[str | None, zh_str('初始密码', LEN_PASSWORD)] = Field(
        None, max_length=LEN_PASSWORD, description='初始密码'
    )
    reason: Annotated[str, zh_str('操作原因', LEN_REMARK, min_length=1)] = Field(
        min_length=1, max_length=LEN_REMARK, description='操作原因'
    )


class ResetRiderPasswordParam(SchemaBase):
    """重置骑手密码参数"""

    password: Annotated[str | None, zh_str('新密码', LEN_PASSWORD)] = Field(
        None, max_length=LEN_PASSWORD, description='新密码'
    )
    reason: Annotated[str | None, zh_str('操作原因', LEN_REMARK)] = Field(
        None, max_length=LEN_REMARK, description='操作原因'
    )


class DisableRiderAccountParam(SchemaBase):
    """停用骑手账号参数"""

    reason: Annotated[str, zh_str('操作原因', LEN_REMARK, min_length=1)] = Field(
        min_length=1, max_length=LEN_REMARK, description='操作原因'
    )


class EnableRiderAccountParam(SchemaBase):
    """启用骑手账号参数"""

    reason: Annotated[str | None, zh_str('操作原因', LEN_REMARK)] = Field(
        None, max_length=LEN_REMARK, description='操作原因'
    )


class EmployHistorySchemaBase(SchemaBase):
    """用工类型历史基础模型"""

    employ_type: EmployType = Field(description='用工类型')
    start_date: date = Field(description='开始日期')
    end_date: date | None = Field(None, description='结束日期')
    remark: Annotated[str | None, zh_str('备注', LEN_REMARK)] = Field(None, max_length=LEN_REMARK, description='备注')


class CreateEmployHistoryParam(EmployHistorySchemaBase):
    """创建用工类型历史参数"""


class UpdateEmployHistoryParam(SchemaBase):
    """更新用工类型历史参数"""

    employ_type: EmployType | None = Field(None, description='用工类型')
    start_date: date | None = Field(None, description='开始日期')
    end_date: date | None = Field(None, description='结束日期')
    remark: Annotated[str | None, zh_str('备注', LEN_REMARK)] = Field(None, max_length=LEN_REMARK, description='备注')


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
    remark: Annotated[str | None, zh_str('备注', LEN_REMARK)] = Field(None, max_length=LEN_REMARK, description='备注')


class CreatePlanBindingParam(PlanBindingSchemaBase):
    """创建方案绑定参数"""


class UpdatePlanBindingParam(SchemaBase):
    """更新方案绑定参数"""

    plan_version_id: int | None = Field(None, description='方案版本 ID')
    binding_type: BindingType | None = Field(None, description='绑定类型')
    start_date: date | None = Field(None, description='生效开始日期')
    end_date: date | None = Field(None, description='结束日期')
    remark: Annotated[str | None, zh_str('备注', LEN_REMARK)] = Field(None, max_length=LEN_REMARK, description='备注')


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


def _batch_rider_ids(value: object) -> object:
    """批量骑手列表：至少 1 人，不重复，不超过单次上限。"""
    if not isinstance(value, list):
        return value
    if len(value) < 1:
        raise ValueError('请至少选择 1 名骑手')
    if len(value) > MAX_ID_LIST:
        raise ValueError(f'骑手不能超过 {MAX_ID_LIST} 名')
    if len(set(value)) != len(value):
        raise ValueError('骑手不能重复')
    return value


def _reject_shared_password(data: Any) -> Any:
    """批量开户和重置不接受统一密码。"""
    if not isinstance(data, dict) or 'password' not in data:
        return data
    raw = data.get('password')
    if raw is not None and str(raw).strip():
        raise ValueError('批量操作不接受统一密码，系统会为每人生成随机密码')
    return data


_BatchRiderIds = Annotated[list[int], BeforeValidator(_batch_rider_ids)]


class BatchPlanBindingParam(SchemaBase):
    """批量绑定同一方案。每名骑手仍走单条绑定的锁账、重算和审计。"""

    rider_ids: _BatchRiderIds = Field(description='骑手 ID 列表')
    plan_version_id: int = Field(description='方案版本 ID')
    binding_type: BindingType = Field(description='绑定类型')
    start_date: date = Field(description='生效开始日期')
    end_date: date | None = Field(None, description='生效结束日期')
    remark: Annotated[str | None, zh_str('备注', LEN_REMARK)] = Field(None, max_length=LEN_REMARK, description='备注')


class BatchBindingItem(SchemaBase):
    """一名骑手的绑定结果"""

    rider_id: int = Field(description='骑手 ID')
    binding_id: int = Field(description='绑定 ID')
    job_no: str = Field(description='工号')
    name: str = Field(description='姓名')


class BatchBindingResult(SchemaBase):
    """批量绑定结果"""

    count: int = Field(description='成功条数')
    items: list[BatchBindingItem] = Field(description='绑定结果')


class BatchOpenAccountParam(SchemaBase):
    """批量开通账号。不接收统一密码，每人生成独立随机口令。"""

    rider_ids: _BatchRiderIds = Field(description='骑手 ID 列表')
    reason: Annotated[str, zh_str('操作原因', LEN_REMARK, min_length=1)] = Field(
        min_length=1, max_length=LEN_REMARK, description='操作原因'
    )

    @model_validator(mode='before')
    @classmethod
    def reject_shared_password(cls, data: Any) -> Any:
        """拒绝请求里的统一密码"""
        return _reject_shared_password(data)


class BatchResetPasswordParam(SchemaBase):
    """批量重置密码。不接收统一密码，每人生成独立随机口令。"""

    rider_ids: _BatchRiderIds = Field(description='骑手 ID 列表')
    reason: Annotated[str | None, zh_str('操作原因', LEN_REMARK)] = Field(
        None, max_length=LEN_REMARK, description='操作原因'
    )

    @model_validator(mode='before')
    @classmethod
    def reject_shared_password(cls, data: Any) -> Any:
        """拒绝请求里的统一密码"""
        return _reject_shared_password(data)


class BatchIssuedPasswordItem(SchemaBase):
    """一名骑手本次下发的随机密码"""

    rider_id: int = Field(description='骑手 ID')
    job_no: str = Field(description='工号')
    name: str = Field(description='姓名')
    username: str = Field(description='登录用户名')
    initial_password: str = Field(description='系统生成的初始密码，仅本次返回')


class BatchIssuedPasswordResult(SchemaBase):
    """批量开户或重置的密码清单"""

    items: list[BatchIssuedPasswordItem] = Field(description='每人一条，关闭后无法再次查看')
