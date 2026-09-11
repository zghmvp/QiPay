from decimal import Decimal

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key
from backend.plugin.rider_salary.enums import EnableStatus, EntryGranularity, FeeMode


class RiderSalarySubject(Base):
    """科目表"""

    __tablename__ = 'rs_subject'
    __table_args__ = (
        sa.UniqueConstraint('code', 'deleted', name='uk_rs_subject_code_deleted'),
        {'comment': '科目表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    code: Mapped[str] = mapped_column(sa.String(64), comment='科目编码')
    name: Mapped[str] = mapped_column(sa.String(64), comment='科目名称')
    direction: Mapped[str] = mapped_column(sa.String(20), comment='方向')
    fee_mode: Mapped[str] = mapped_column(sa.String(20), default=FeeMode.formula.value, comment='计费方式')
    fixed_amount: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 2), default=None, comment='定额金额')
    include_in_gross: Mapped[bool] = mapped_column(default=True, comment='是否参与应发合计')
    entry_granularity: Mapped[str] = mapped_column(
        sa.String(20),
        default=EntryGranularity.both.value,
        comment='入账粒度',
    )
    scope_sites: Mapped[list | None] = mapped_column(sa.JSON(), default=None, comment='适用站点')
    scope_employ_types: Mapped[list | None] = mapped_column(sa.JSON(), default=None, comment='适用用工类型')
    is_builtin: Mapped[bool] = mapped_column(default=False, comment='系统内置')
    status: Mapped[str] = mapped_column(sa.String(20), default=EnableStatus.enable.value, index=True, comment='状态')
    sort_order: Mapped[int] = mapped_column(default=0, comment='排序')
    remark: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='备注')
