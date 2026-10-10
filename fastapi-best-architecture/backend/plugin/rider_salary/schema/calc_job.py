from datetime import datetime

from pydantic import Field

from backend.common.schema import SchemaBase


class CalcJobFailure(SchemaBase):
    """算薪失败的骑手"""

    rider_id: int = Field(description='骑手 ID')
    job_no: str = Field('', description='工号')
    reason: str = Field(description='失败原因')


class GetCalcJobDetail(SchemaBase):
    """算薪作业详情"""

    id: int = Field(description='作业 ID')
    period_id: int = Field(description='结算周期 ID')
    site_id: int = Field(description='站点 ID')
    status: str = Field(description='状态')
    status_label: str = Field(description='状态中文')
    total_count: int = Field(description='目标骑手数')
    done_count: int = Field(description='已处理骑手数')
    success_count: int = Field(description='成功骑手数')
    failed_count: int = Field(description='失败骑手数')
    failures: list[CalcJobFailure] = Field(default_factory=list, description='失败骑手及原因')
    warnings: list[str] = Field(default_factory=list, description='告警')
    error_message: str | None = Field(None, description='作业级错误')
    started_time: datetime | None = Field(None, description='开始时间')
    finished_time: datetime | None = Field(None, description='结束时间')
