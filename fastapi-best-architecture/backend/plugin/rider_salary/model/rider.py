from datetime import date
from decimal import Decimal

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key
from backend.plugin.rider_salary.enums import EmployType, RiderStatus


class RiderSalaryRider(Base):
    """骑手表"""

    __tablename__ = 'rs_rider'
    __table_args__ = (
        sa.UniqueConstraint('job_no', 'deleted', name='uk_rs_rider_job_no_deleted'),
        {'comment': '骑手表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    job_no: Mapped[str] = mapped_column(sa.String(32), comment='工号')
    name: Mapped[str] = mapped_column(sa.String(32), comment='姓名')
    site_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='所属站点 ID')
    hire_date: Mapped[date] = mapped_column(sa.Date, comment='入职日期')
    phone: Mapped[str | None] = mapped_column(sa.String(20), default=None, comment='手机')
    employ_type: Mapped[str] = mapped_column(sa.String(20), default=EmployType.part_time.value, comment='当前用工类型')
    leave_date: Mapped[date | None] = mapped_column(sa.Date, default=None, comment='离职日期')
    status: Mapped[str] = mapped_column(sa.String(20), default=RiderStatus.on_job.value, index=True, comment='状态')
    advance_limit: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 2), default=None, comment='预支上限（骑手级）')
    settle_cycle_override: Mapped[str | None] = mapped_column(sa.String(20), default=None, comment='结算周期覆盖')
    cycle_config_override: Mapped[dict | None] = mapped_column(sa.JSON(), default=None, comment='周期配置覆盖')
    user_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, index=True, comment='绑定登录账号')
    remark: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='备注')
