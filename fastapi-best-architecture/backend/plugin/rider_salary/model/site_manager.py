import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key
from backend.plugin.rider_salary.enums import ManagerRole


class RiderSalarySiteManager(Base):
    """站点负责人表"""

    __tablename__ = 'rs_site_manager'
    __table_args__ = (
        sa.UniqueConstraint('site_id', 'user_id', 'deleted', name='uk_rs_site_manager_site_user_deleted'),
        # 每个站点至多一名未删除负责人。副负责人不占用这个名额。
        # Q-18 推荐不再实现 MySQL，postgresql_where 只在 PostgreSQL 生效。
        sa.Index(
            'uq_rs_site_manager_one_owner',
            'site_id',
            unique=True,
            postgresql_where=sa.text("role = 'owner' AND deleted = 0"),
        ),
        {'comment': '站点负责人表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    site_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='站点 ID')
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    role: Mapped[str] = mapped_column(sa.String(20), default=ManagerRole.owner.value, comment='负责人角色')
