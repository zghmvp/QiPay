from decimal import Decimal

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key

GLOBAL_POLICY_SITE_ID = 0


class RiderSalaryAdvancePolicy(Base):
    """预支规则。site_id 为 0 时表示全局默认，站点未单独配置时沿用全局。"""

    __tablename__ = 'rs_advance_policy'
    __table_args__ = (
        sa.UniqueConstraint('site_id', 'deleted', name='uk_rs_advance_policy_site_deleted'),
        {'comment': '预支规则'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    site_id: Mapped[int] = mapped_column(sa.BigInteger, comment='站点 ID，0 表示全局默认')
    amount_mode: Mapped[str] = mapped_column(
        sa.String(20),
        default='percent',
        comment='额度方式：percent 按预估实发百分比，fixed 固定额度',
    )
    percent: Mapped[Decimal] = mapped_column(sa.Numeric(5, 2), default=Decimal('50'), comment='预估实发百分比')
    fixed_amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('3000'), comment='固定额度')
    max_amount: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(12, 2),
        default=None,
        comment='绝对封顶，空表示不额外封顶',
    )
    monthly_max_count: Mapped[int] = mapped_column(default=2, comment='每月预支次数上限')
    min_tenure_days: Mapped[int] = mapped_column(default=7, comment='入职满多少天才能预支')
    min_completed_orders: Mapped[int] = mapped_column(default=1, comment='当前周期至少完成订单数')
    min_amount: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2), default=Decimal('1'), comment='单笔最低金额')
