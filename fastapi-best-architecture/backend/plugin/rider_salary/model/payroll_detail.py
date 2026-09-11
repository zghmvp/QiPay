from datetime import date
from decimal import Decimal

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key
from backend.plugin.rider_salary.enums import CalcStage, DetailSource


class RiderSalaryPayrollDetail(Base):
    """薪资明细表"""

    __tablename__ = 'rs_payroll_detail'
    __table_args__ = (
        sa.Index('ix_rs_payroll_detail_payroll_stage', 'payroll_id', 'stage'),
        sa.Index('ix_rs_payroll_detail_rider_biz_date', 'rider_id', 'biz_date'),
        {'comment': '薪资明细表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    payroll_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='薪资单 ID')
    rider_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='骑手 ID')
    subject_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='科目 ID')
    amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), comment='金额（带符号）')
    stage: Mapped[str] = mapped_column(sa.String(20), default=CalcStage.per_order.value, comment='计算阶段')
    include_in_gross: Mapped[bool] = mapped_column(default=True, comment='是否计入应发')
    source: Mapped[str] = mapped_column(sa.String(20), default=DetailSource.formula.value, comment='来源')
    biz_date: Mapped[date | None] = mapped_column(sa.Date, default=None, index=True, comment='业务日期')
    plan_version_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='方案版本 ID')
    plan_item_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='方案项 ID')
    order_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='订单 ID')
    calc_trace: Mapped[dict | None] = mapped_column(sa.JSON(), default=None, comment='计算过程')
