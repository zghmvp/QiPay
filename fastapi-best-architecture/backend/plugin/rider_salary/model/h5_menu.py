import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key

GLOBAL_H5_MENU_SITE_ID = 0


class RiderSalaryH5Menu(Base):
    """骑手端菜单开关。site_id 为 0 时表示全局默认。"""

    __tablename__ = 'rs_h5_menu'
    __table_args__ = (
        sa.UniqueConstraint('site_id', 'deleted', name='uk_rs_h5_menu_site_deleted'),
        {'comment': '骑手端菜单开关'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    site_id: Mapped[int] = mapped_column(sa.BigInteger, comment='站点 ID，0 表示全局默认')
    show_adjustments: Mapped[bool] = mapped_column(sa.Boolean, default=True, comment='是否开放奖惩')
    show_advance: Mapped[bool] = mapped_column(sa.Boolean, default=True, comment='是否开放预支')
    show_notices: Mapped[bool] = mapped_column(sa.Boolean, default=True, comment='是否开放公告')
    show_plan: Mapped[bool] = mapped_column(sa.Boolean, default=True, comment='是否开放当前方案')
    show_home: Mapped[bool] = mapped_column(sa.Boolean, default=True, comment='是否开放首页')
    show_home_pay: Mapped[bool] = mapped_column(sa.Boolean, default=True, comment='是否显示首页工资')
    show_day_amount: Mapped[bool] = mapped_column(sa.Boolean, default=True, comment='是否显示当日金额')
    show_estimate_net: Mapped[bool] = mapped_column(sa.Boolean, default=True, comment='是否显示预估实发')
    show_advance_inflight: Mapped[bool] = mapped_column(sa.Boolean, default=True, comment='是否显示在途占用')
