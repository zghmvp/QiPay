from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, UniversalText, id_key
from backend.plugin.rider_salary.enums import CalcJobStatus


class RiderSalaryCalcJob(Base):
    """算薪作业表"""

    __tablename__ = 'rs_calc_job'
    __table_args__ = (
        sa.Index('ix_rs_calc_job_period_status', 'period_id', 'status'),
        # 同一周期同时只允许一条未删除的排队中或计算中作业。
        # postgresql_where 只在 PostgreSQL 生效；MySQL 的 init 只写说明，不建等价普通唯一索引。
        sa.Index(
            'uq_rs_calc_job_one_active',
            'period_id',
            unique=True,
            postgresql_where=sa.text("status IN ('queued', 'running') AND deleted = 0"),
        ),
        {'comment': '算薪作业表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    period_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='结算周期 ID')
    site_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='站点 ID')
    status: Mapped[str] = mapped_column(
        sa.String(20),
        default=CalcJobStatus.queued.value,
        index=True,
        comment='状态',
    )
    total_count: Mapped[int] = mapped_column(sa.Integer, default=0, comment='目标骑手数')
    done_count: Mapped[int] = mapped_column(sa.Integer, default=0, comment='已处理骑手数')
    success_count: Mapped[int] = mapped_column(sa.Integer, default=0, comment='成功骑手数')
    failed_count: Mapped[int] = mapped_column(sa.Integer, default=0, comment='失败骑手数')
    operator_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='操作人 ID')
    target_rider_ids: Mapped[list | None] = mapped_column(sa.JSON(), default=None, comment='指定骑手 ID')
    failures: Mapped[list | None] = mapped_column(sa.JSON(), default=None, comment='失败骑手及原因')
    warnings: Mapped[list | None] = mapped_column(sa.JSON(), default=None, comment='告警')
    error_message: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='作业级错误')
    started_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='开始时间')
    finished_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='结束时间')
