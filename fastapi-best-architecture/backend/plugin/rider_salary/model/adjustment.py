from datetime import date
from decimal import Decimal

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key


class RiderSalaryAdjustment(Base):
    """奖惩记录表"""

    __tablename__ = 'rs_adjustment'
    __table_args__ = (
        sa.Index('ix_rs_adjustment_rider_biz_date', 'rider_id', 'biz_date'),
        {'comment': '奖惩记录表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    rider_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='骑手 ID')
    site_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='站点 ID（快照）')
    biz_date: Mapped[date] = mapped_column(sa.Date, index=True, comment='业务日期')
    subject_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='科目 ID')
    amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), comment='金额（正数；上期补差允许负数）')
    remark: Mapped[str] = mapped_column(UniversalText, comment='备注')
    signed_amount: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 2), default=None, comment='带符号金额')
    period_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, index=True, comment='结算周期 ID')
    is_locked: Mapped[bool] = mapped_column(default=False, comment='已锁账')
    operator_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='操作人 ID')
