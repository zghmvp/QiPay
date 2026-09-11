from decimal import Decimal

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key
from backend.plugin.rider_salary.enums import CycleType, EnableStatus


class RiderSalarySite(Base):
    """站点表"""

    __tablename__ = 'rs_site'
    __table_args__ = (
        sa.UniqueConstraint('code', 'deleted', name='uk_rs_site_code_deleted'),
        {'comment': '站点表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    code: Mapped[str] = mapped_column(sa.String(32), comment='站点编码')
    name: Mapped[str] = mapped_column(sa.String(64), comment='站点名称')
    settle_cycle: Mapped[str] = mapped_column(sa.String(20), default=CycleType.month.value, comment='结算周期类型')
    cycle_config: Mapped[dict | None] = mapped_column(sa.JSON(), default=None, comment='周期配置')
    advance_limit: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 2), default=None, comment='预支上限（站点级）')
    dept_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, index=True, comment='关联部门 ID')
    status: Mapped[str] = mapped_column(sa.String(20), default=EnableStatus.enable.value, index=True, comment='状态')
    remark: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='备注')
