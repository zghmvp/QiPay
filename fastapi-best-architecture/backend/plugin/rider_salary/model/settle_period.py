from datetime import date, datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, UniversalText, id_key
from backend.plugin.rider_salary.enums import PeriodStatus


class RiderSalarySettlePeriod(Base):
    """结算周期表"""

    __tablename__ = 'rs_settle_period'
    __table_args__ = (
        sa.UniqueConstraint(
            'site_id',
            'rider_id',
            'start_date',
            'deleted',
            name='uk_rs_settle_period_site_rider_start_deleted',
        ),
        sa.Index('ix_rs_settle_period_site_dates', 'site_id', 'start_date', 'end_date'),
        {'comment': '结算周期表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    site_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='站点 ID')
    cycle_type: Mapped[str] = mapped_column(sa.String(20), comment='周期类型')
    start_date: Mapped[date] = mapped_column(sa.Date, comment='开始日期')
    end_date: Mapped[date] = mapped_column(sa.Date, comment='结束日期')
    rider_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        default=0,
        server_default='0',
        index=True,
        comment='骑手 ID（0 表示站点级周期）',
    )
    status: Mapped[str] = mapped_column(sa.String(20), default=PeriodStatus.open.value, index=True, comment='状态')
    locked_by: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='锁账人 ID')
    locked_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='锁账时间')
    paid_by: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='发薪标记人 ID')
    paid_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='发薪标记时间')
    reopened_by: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='反冲人 ID')
    reopened_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='反冲时间')
    remark: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='备注')
    last_calc_failures: Mapped[list | None] = mapped_column(
        sa.JSON(),
        default=None,
        comment='最近一次算薪失败清单',
    )
    last_calc_status: Mapped[str | None] = mapped_column(
        sa.String(20),
        default=None,
        comment='最近一次算薪态 queued/running/done/failed',
    )
    last_calc_status_message: Mapped[str | None] = mapped_column(
        UniversalText,
        default=None,
        comment='最近一次算薪态说明',
    )
