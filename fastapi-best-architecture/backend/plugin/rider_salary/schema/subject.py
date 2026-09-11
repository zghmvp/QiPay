from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import ConfigDict, Field, computed_field

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import EnableStatus, EntryGranularity, FeeMode, SubjectDirection


class SubjectSchemaBase(SchemaBase):
    """科目基础模型"""

    code: str = Field(description='科目编码')
    name: str = Field(description='科目名称')
    direction: SubjectDirection = Field(description='方向')
    fee_mode: FeeMode = Field(FeeMode.formula, description='计费方式')
    fixed_amount: Decimal | None = Field(None, description='定额金额')
    include_in_gross: bool = Field(True, description='是否参与应发合计')
    entry_granularity: EntryGranularity = Field(EntryGranularity.both, description='入账粒度')
    scope_sites: list[Any] | None = Field(None, description='适用站点')
    scope_employ_types: list[Any] | None = Field(None, description='适用用工类型')
    status: EnableStatus = Field(EnableStatus.enable, description='状态')
    sort_order: int = Field(0, description='排序')
    remark: str | None = Field(None, description='备注')


class CreateSubjectParam(SubjectSchemaBase):
    """创建科目参数"""


class UpdateSubjectParam(SchemaBase):
    """更新科目参数"""

    code: str | None = Field(None, description='科目编码')
    name: str | None = Field(None, description='科目名称')
    direction: SubjectDirection | None = Field(None, description='方向')
    fee_mode: FeeMode | None = Field(None, description='计费方式')
    fixed_amount: Decimal | None = Field(None, description='定额金额')
    include_in_gross: bool | None = Field(None, description='是否参与应发合计')
    entry_granularity: EntryGranularity | None = Field(None, description='入账粒度')
    scope_sites: list[Any] | None = Field(None, description='适用站点')
    scope_employ_types: list[Any] | None = Field(None, description='适用用工类型')
    status: EnableStatus | None = Field(None, description='状态')
    sort_order: int | None = Field(None, description='排序')
    remark: str | None = Field(None, description='备注')


class GetSubjectDetail(SubjectSchemaBase):
    """科目详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='科目 ID')
    is_builtin: bool = Field(description='系统内置')
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
    def direction_label(self) -> str:
        """方向中文"""
        try:
            return SubjectDirection(self.direction).label
        except ValueError:
            return str(self.direction)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fee_mode_label(self) -> str:
        """计费方式中文"""
        try:
            return FeeMode(self.fee_mode).label
        except ValueError:
            return str(self.fee_mode)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def entry_granularity_label(self) -> str:
        """入账粒度中文"""
        try:
            return EntryGranularity(self.entry_granularity).label
        except ValueError:
            return str(self.entry_granularity)
