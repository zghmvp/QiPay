import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key


class RiderSalaryRoleAnchor(Base):
    """角色种子锚点表"""

    __tablename__ = 'rs_role_anchor'
    __table_args__ = (
        sa.UniqueConstraint('role_key', 'deleted', name='uk_rs_role_anchor_role_key_deleted'),
        {'comment': '角色种子锚点表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    role_key: Mapped[str] = mapped_column(sa.String(64), comment='业务键')
    role_id: Mapped[int] = mapped_column(sa.BigInteger, comment='角色 ID')
