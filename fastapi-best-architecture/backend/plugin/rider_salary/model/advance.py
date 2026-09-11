from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, UniversalText, id_key
from backend.plugin.rider_salary.enums import AdvanceStatus, DeductStatus


class RiderSalaryAdvance(Base):
    """预支单表"""

    __tablename__ = 'rs_advance'
    __table_args__ = (
        sa.Index('ix_rs_advance_rider_status', 'rider_id', 'status'),
        {'comment': '预支单表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    rider_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='骑手 ID')
    site_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='站点 ID')
    amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), comment='预支金额')
    reason: Mapped[str] = mapped_column(UniversalText, comment='原因')
    status: Mapped[str] = mapped_column(
        sa.String(20),
        default=AdvanceStatus.draft.value,
        index=True,
        comment='状态',
    )
    approver_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='审核人 ID')
    approve_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='审核时间')
    approve_remark: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='审核备注')
    paid_by: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='发放标记人 ID')
    paid_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='发放标记时间')
    deducted_amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('0.00'), comment='已抵扣')
    remaining_amount: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 2), default=None, comment='待抵扣')
    deduct_status: Mapped[str] = mapped_column(
        sa.String(20),
        default=DeductStatus.none.value,
        comment='抵扣状态',
    )
    submit_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='提交时间')
    cancel_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='取消时间')
