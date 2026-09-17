from datetime import datetime

from pydantic import ConfigDict, Field, computed_field

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import RecalcJobSource, RecalcJobStatus


class GetRecalcJobDetail(SchemaBase):
    """重算任务详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='任务 ID')
    site_id: int = Field(description='站点 ID')
    source: str = Field(description='来源')
    source_id: int | None = Field(None, description='来源业务 ID')
    status: str = Field(description='状态')
    message: str | None = Field(None, description='状态说明 / 失败原因')
    month: str | None = Field(None, description='目标月份 YYYY-MM')
    total_periods: int = Field(description='涉及周期数')
    done_periods: int = Field(description='已完成周期数')
    rider_count: int = Field(description='涉及骑手数')
    operator_id: int = Field(description='操作人 ID')
    started_time: datetime | None = Field(None, description='开始时间')
    finished_time: datetime | None = Field(None, description='结束时间')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
    payload: dict | None = Field(None, description='任务快照（含失败清单）')

    @computed_field  # type: ignore[prop-decorator]
    @property
    def failed_rider_count(self) -> int:
        """失败骑手数"""
        raw = self.payload or {}
        return int(raw.get('failed_rider_count') or 0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_label(self) -> str:
        """状态中文"""
        try:
            return RecalcJobStatus(self.status).label
        except ValueError:
            return str(self.status)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source_label(self) -> str:
        """来源中文"""
        try:
            return RecalcJobSource(self.source).label
        except ValueError:
            return str(self.source)


class BatchRecalcStaleParam(SchemaBase):
    """本站本月 stale 批量重算参数"""

    site_id: int = Field(description='站点 ID')
    month: str = Field(description='月份 YYYY-MM')


class BatchRecalcStalePreview(SchemaBase):
    """批量重算预览（确认框）"""

    site_id: int = Field(description='站点 ID')
    site_name: str = Field(description='站点名称')
    month: str = Field(description='月份')
    period_count: int = Field(description='需重算周期数')
    stale_rider_count: int = Field(description='需重算骑手数（去重）')
    period_ranges: list[str] = Field(default_factory=list, description='周期区间文案')


class BatchRecalcStaleResult(SchemaBase):
    """批量重算提交结果"""

    job_id: int = Field(description='重算任务 ID')
    site_name: str = Field(description='站点名称')
    period_count: int = Field(description='涉及周期数')
    rider_count: int = Field(description='涉及骑手数')
    queued: bool = Field(True, description='是否已转入后台')
    message: str = Field(description='提示文案')
