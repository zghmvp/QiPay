from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, UniversalText, id_key
from backend.plugin.rider_salary.enums import NoticeStatus


class RiderSalaryNotice(Base):
    """站点公告表"""

    __tablename__ = 'rs_notice'
    __table_args__ = (
        sa.Index('ix_rs_notice_site_status', 'site_id', 'status'),
        {'comment': '站点公告表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    title: Mapped[str] = mapped_column(sa.String(128), comment='标题')
    content: Mapped[str] = mapped_column(UniversalText, comment='内容')
    publisher_id: Mapped[int] = mapped_column(sa.BigInteger, comment='发布人 ID')
    site_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, index=True, comment='站点 ID')
    publish_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='发布时间')
    status: Mapped[str] = mapped_column(
        sa.String(20),
        default=NoticeStatus.draft.value,
        index=True,
        comment='状态',
    )
