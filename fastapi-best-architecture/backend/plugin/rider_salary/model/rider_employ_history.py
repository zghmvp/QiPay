from datetime import date

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key
from backend.plugin.rider_salary.enums import EmployType


class RiderSalaryRiderEmployHistory(Base):
    """用工类型历史表"""

    __tablename__ = 'rs_rider_employ_history'
    __table_args__ = (
        sa.Index('ix_rs_rider_employ_history_rider_date', 'rider_id', 'start_date'),
        {'comment': '用工类型历史表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    rider_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='骑手 ID')
    start_date: Mapped[date] = mapped_column(sa.Date, comment='开始日期')
    employ_type: Mapped[str] = mapped_column(sa.String(20), default=EmployType.part_time.value, comment='用工类型')
    end_date: Mapped[date | None] = mapped_column(sa.Date, default=None, comment='结束日期')
    remark: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='备注')
