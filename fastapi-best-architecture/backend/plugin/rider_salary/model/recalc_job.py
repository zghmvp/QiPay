from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key
from backend.plugin.rider_salary.enums import RecalcJobSource, RecalcJobStatus


class RiderSalaryRecalcJob(Base):
    """重算任务表（插件内轻量状态，不依赖 Celery）"""

    __tablename__ = 'rs_recalc_job'
    __table_args__ = {'comment': '重算任务表'}

    id: Mapped[id_key] = mapped_column(init=False)
    site_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='站点 ID')
    source: Mapped[str] = mapped_column(
        sa.String(20),
        default=RecalcJobSource.import_batch.value,
        index=True,
        comment='来源',
    )
    source_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, index=True, comment='来源业务 ID')
    status: Mapped[str] = mapped_column(
        sa.String(20),
        default=RecalcJobStatus.queued.value,
        index=True,
        comment='状态',
    )
    message: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='状态说明 / 失败原因')
    month: Mapped[str | None] = mapped_column(sa.String(7), default=None, comment='目标月份 YYYY-MM')
    total_periods: Mapped[int] = mapped_column(default=0, comment='涉及周期数')
    done_periods: Mapped[int] = mapped_column(default=0, comment='已完成周期数')
    rider_count: Mapped[int] = mapped_column(default=0, comment='涉及骑手数')
    operator_id: Mapped[int] = mapped_column(sa.BigInteger, default=0, index=True, comment='操作人 ID')
    started_time: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), default=None, comment='开始时间')
    finished_time: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), default=None, comment='结束时间')
    payload: Mapped[dict | None] = mapped_column(sa.JSON(), default=None, comment='重试用参数快照')
