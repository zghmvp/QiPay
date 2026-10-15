from datetime import date

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key


class RiderSalaryRiderSiteHistory(Base):
    """骑手站点履历表"""

    __tablename__ = 'rs_rider_site_history'
    __table_args__ = (
        sa.Index('ix_rs_rider_site_history_rider_date', 'rider_id', 'start_date'),
        {'comment': '骑手站点履历表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    rider_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='骑手 ID')
    site_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='站点 ID')
    start_date: Mapped[date] = mapped_column(sa.Date, comment='开始日期')
    end_date: Mapped[date | None] = mapped_column(sa.Date, default=None, comment='结束日期，空表示至今')
