import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key
from backend.plugin.rider_salary.enums import ManagerRole


class RiderSalarySiteManager(Base):
    """站点负责人表"""

    __tablename__ = 'rs_site_manager'
    __table_args__ = (
        sa.UniqueConstraint('site_id', 'user_id', 'deleted', name='uk_rs_site_manager_site_user_deleted'),
        {'comment': '站点负责人表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    site_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='站点 ID')
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    role: Mapped[str] = mapped_column(sa.String(20), default=ManagerRole.owner.value, comment='负责人角色')
