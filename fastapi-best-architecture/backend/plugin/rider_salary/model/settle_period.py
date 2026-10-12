from datetime import date, datetime

import sqlalchemy as sa

from sqlalchemy import DDL, column, event
from sqlalchemy.dialects.postgresql import ExcludeConstraint
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
        # 同一范围（同站点、同 rider_id）的未删除闭区间不得相交。
        # 不同骑手互不影响。站点级与骑手级的日期重叠由生成周期时拒绝，离职结算整段覆盖除外。
        # 等值比较依赖 btree_gist，建表前由 before_create 创建扩展；已有库走 sql/patch/006。
        ExcludeConstraint(
            (column('site_id'), '='),
            (column('rider_id'), '='),
            (sa.func.daterange(column('start_date'), column('end_date'), sa.literal('[]')), '&&'),
            where=column('deleted') == 0,
            name='ex_rs_settle_period_no_overlap',
        ),
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


event.listen(
    RiderSalarySettlePeriod.__table__,
    'before_create',
    DDL('CREATE EXTENSION IF NOT EXISTS btree_gist'),
)
