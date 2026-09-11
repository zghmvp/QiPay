from datetime import date

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key


class RiderSalaryDayFlag(Base):
    """日标记表"""

    __tablename__ = 'rs_day_flag'
    __table_args__ = (
        sa.UniqueConstraint('site_id', 'biz_date', 'deleted', name='uk_rs_day_flag_site_biz_date_deleted'),
        {'comment': '日标记表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    site_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='站点 ID')
    biz_date: Mapped[date] = mapped_column(sa.Date, index=True, comment='业务日期')
    bad_weather: Mapped[bool] = mapped_column(default=False, comment='恶劣天气')
    high_temp: Mapped[bool] = mapped_column(default=False, comment='高温')
    promo: Mapped[bool] = mapped_column(default=False, comment='大促')
    remark: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='备注')
