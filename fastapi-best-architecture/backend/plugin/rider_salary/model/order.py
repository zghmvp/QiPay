from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, UniversalText, id_key
from backend.plugin.rider_salary.enums import OrderSource, OrderStatus


class RiderSalaryOrder(Base):
    """订单明细表"""

    __tablename__ = 'rs_order'
    __table_args__ = (
        sa.UniqueConstraint('order_no', 'deleted', name='uk_rs_order_order_no_deleted'),
        sa.Index('ix_rs_order_rider_biz_date', 'rider_id', 'biz_date'),
        {'comment': '订单明细表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    order_no: Mapped[str] = mapped_column(sa.String(64), comment='订单号')
    site_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='站点 ID')
    rider_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='骑手 ID')
    biz_date: Mapped[date] = mapped_column(sa.Date, index=True, comment='业务日期')
    distance_km: Mapped[Decimal] = mapped_column(sa.Numeric(8, 2), comment='配送距离（公里）')
    weight_jin: Mapped[Decimal] = mapped_column(sa.Numeric(8, 2), comment='商品重量（斤）')
    order_time: Mapped[datetime] = mapped_column(TimeZone, comment='下单时间')
    deliver_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='送达时间')
    status: Mapped[str] = mapped_column(
        sa.String(20),
        default=OrderStatus.completed.value,
        index=True,
        comment='订单状态',
    )
    amount: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 2), default=None, comment='订单金额')
    source: Mapped[str] = mapped_column(sa.String(20), default=OrderSource.manual.value, comment='来源')
    import_batch_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, index=True, comment='导入批次 ID')
    is_locked: Mapped[bool] = mapped_column(default=False, comment='已锁账')
    remark: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='备注')
