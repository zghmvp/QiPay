from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, id_key
from backend.plugin.rider_salary.enums import PayrollKind, PayrollStatus


class RiderSalaryPayroll(Base):
    """薪资结果表"""

    __tablename__ = 'rs_payroll'
    __table_args__ = (
        sa.Index('ix_rs_payroll_period_rider', 'period_id', 'rider_id'),
        {'comment': '薪资结果表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    period_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='结算周期 ID')
    rider_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='骑手 ID')
    kind: Mapped[str] = mapped_column(sa.String(20), default=PayrollKind.normal.value, comment='类型')
    status: Mapped[str] = mapped_column(
        sa.String(20),
        default=PayrollStatus.draft.value,
        index=True,
        comment='状态',
    )
    calc_version: Mapped[int] = mapped_column(default=0, comment='计算轮次')
    stale: Mapped[bool] = mapped_column(default=False, comment='需重算')
    reversed: Mapped[bool] = mapped_column(default=False, comment='已被反冲')
    warnings: Mapped[list | None] = mapped_column(sa.JSON(), default=None, comment='计算告警')
    order_count: Mapped[int] = mapped_column(default=0, comment='单量')
    valid_order_count: Mapped[int] = mapped_column(default=0, comment='有效单量')
    per_order_total: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('0.00'), comment='逐单项合计')
    daily_total: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('0.00'), comment='按日项合计')
    period_total: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('0.00'), comment='周期项合计')
    bonus_total: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('0.00'), comment='手工奖合计')
    penalty_total: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('0.00'), comment='手工惩合计')
    gross: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('0.00'), comment='应发')
    deduction_total: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('0.00'), comment='代扣合计')
    advance_deduction: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('0.00'), comment='预支抵扣')
    net: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('0.00'), comment='实发')
    plan_version_ids: Mapped[list | None] = mapped_column(sa.JSON(), default=None, comment='本期方案版本集合')
    reversed_of_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='反冲对象 ID')
    calc_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='计算时间')
    calc_by: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='计算人 ID')
