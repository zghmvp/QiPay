from datetime import date

from pydantic import Field

from backend.common.schema import SchemaBase


class RollbackPreviewRider(SchemaBase):
    """将被解绑的骑手"""

    rider_id: int = Field(description='骑手 ID')
    job_no: str | None = Field(None, description='工号')
    name: str | None = Field(None, description='姓名')
    start_date: date | None = Field(None, description='绑定开始')
    end_date: date | None = Field(None, description='绑定结束')


class RollbackPreviewPayroll(SchemaBase):
    """受影响薪资单"""

    id: int = Field(description='薪资单 ID')
    period_id: int = Field(description='周期 ID')
    rider_id: int = Field(description='骑手 ID')
    status: str = Field(description='状态')
    kind: str = Field(description='类型')


class RollbackPreviewResult(SchemaBase):
    """回退预览"""

    version_label: str = Field(description='版本标签')
    version_id: int = Field(description='将作废的版本 ID')
    binding_count: int = Field(description='将解除的绑定数')
    riders: list[RollbackPreviewRider] = Field(default_factory=list, description='将被解绑的骑手清单')
    payrolls_draft: int = Field(description='将作废的草稿薪资条数')
    payrolls_finalized: int = Field(description='将反冲的已定稿条数')
    payrolls_paid: int = Field(description='将反冲的已发薪条数')
    reversal_count: int = Field(description='将生成的反冲单数量')
    periods_reopened: int = Field(description='将进入补发中的周期数')
    has_paid: bool = Field(description='是否存在已发薪结果')
    consequences: list[str] = Field(default_factory=list, description='中文后果说明')
    payrolls: list[RollbackPreviewPayroll] = Field(default_factory=list, description='受影响薪资单明细')


class RollbackParam(SchemaBase):
    """执行回退"""

    reason: str = Field(min_length=1, description='回退原因')
    confirm_text: str = Field('', description='存在已发薪结果时必须等于「确认回退」')
