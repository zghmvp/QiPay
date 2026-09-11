import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key
from backend.plugin.rider_salary.enums import EnableStatus


class RiderSalaryPlan(Base):
    """方案表"""

    __tablename__ = 'rs_plan'
    __table_args__ = (
        sa.UniqueConstraint('code', 'deleted', name='uk_rs_plan_code_deleted'),
        {'comment': '方案表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    code: Mapped[str] = mapped_column(sa.String(64), comment='方案编码')
    name: Mapped[str] = mapped_column(sa.String(64), comment='方案名称')
    short_name: Mapped[str] = mapped_column(sa.String(16), comment='日历色带短名')
    color: Mapped[str] = mapped_column(sa.String(16), comment='色带颜色')
    description: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='方案说明')
    status: Mapped[str] = mapped_column(sa.String(20), default=EnableStatus.enable.value, index=True, comment='状态')
