from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, UniversalText, id_key
from backend.plugin.rider_salary.enums import PlanModeTag, PlanVersionStatus


class RiderSalaryPlanVersion(Base):
    """方案版本表"""

    __tablename__ = 'rs_plan_version'
    __table_args__ = (
        sa.UniqueConstraint('plan_id', 'version_no', 'deleted', name='uk_rs_plan_version_plan_no_deleted'),
        {'comment': '方案版本表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    plan_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='所属方案 ID')
    version_no: Mapped[int] = mapped_column(comment='版本号')
    status: Mapped[str] = mapped_column(
        sa.String(20),
        default=PlanVersionStatus.draft.value,
        index=True,
        comment='状态',
    )
    mode_tag: Mapped[str] = mapped_column(sa.String(20), default=PlanModeTag.custom.value, comment='计薪模式标签')
    is_used: Mapped[bool] = mapped_column(default=False, comment='是否已被使用')
    items_hash: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='当前方案项内容哈希')
    trial_hash: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='试算内容哈希')
    trial_passed: Mapped[bool] = mapped_column(default=False, comment='试算通过')
    trial_snapshot: Mapped[dict | None] = mapped_column(sa.JSON(), default=None, comment='最近试算摘要')
    copied_from_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='复制来源版本 ID')
    activated_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='启用时间')
    disabled_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='停用时间')
    voided_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='作废时间')
    remark: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='备注')
