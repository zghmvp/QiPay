from datetime import date
from decimal import Decimal

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key
from backend.plugin.rider_salary.enums import DayStatus


class RiderSalaryPayrollDaily(Base):
    """日汇总缓存表"""

    __tablename__ = 'rs_payroll_daily'
    __table_args__ = (
        sa.UniqueConstraint('rider_id', 'biz_date', 'deleted', name='uk_rs_payroll_daily_rider_biz_date_deleted'),
        {'comment': '日汇总缓存表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    rider_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='骑手 ID')
    biz_date: Mapped[date] = mapped_column(sa.Date, index=True, comment='业务日期')
    period_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, index=True, comment='结算周期 ID')
    plan_version_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='当日生效方案版本 ID')
    order_count: Mapped[int] = mapped_column(default=0, comment='单量')
    valid_order_count: Mapped[int] = mapped_column(default=0, comment='有效单量')
    formula_amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('0.00'), comment='公式金额')
    manual_bonus: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('0.00'), comment='手工奖')
    manual_penalty: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('0.00'), comment='手工惩')
    net_adjust: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('0.00'), comment='手工奖惩净额')
    day_status: Mapped[str] = mapped_column(
        sa.String(20),
        default=DayStatus.not_imported.value,
        index=True,
        comment='日状态',
    )
