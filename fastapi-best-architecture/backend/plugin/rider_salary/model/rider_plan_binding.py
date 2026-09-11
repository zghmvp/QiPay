from datetime import date

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key
from backend.plugin.rider_salary.enums import BindingType


class RiderSalaryRiderPlanBinding(Base):
    """方案绑定表"""

    __tablename__ = 'rs_rider_plan_binding'
    __table_args__ = (
        sa.Index('ix_rs_rider_plan_binding_rider_date', 'rider_id', 'start_date', 'end_date'),
        {'comment': '方案绑定表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    rider_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='骑手 ID')
    plan_version_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='方案版本 ID')
    start_date: Mapped[date] = mapped_column(sa.Date, comment='生效开始日期')
    binding_type: Mapped[str] = mapped_column(sa.String(20), default=BindingType.default.value, comment='绑定类型')
    end_date: Mapped[date | None] = mapped_column(sa.Date, default=None, comment='生效结束日期')
    remark: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='备注')
