import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key
from backend.plugin.rider_salary.enums import CalcStage


class RiderSalaryPlanItem(Base):
    """方案项表"""

    __tablename__ = 'rs_plan_item'
    __table_args__ = (
        sa.Index('ix_rs_plan_item_version_stage_sort', 'plan_version_id', 'stage', 'sort_order'),
        {'comment': '方案项表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    plan_version_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='所属版本 ID')
    subject_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='科目 ID')
    name: Mapped[str] = mapped_column(sa.String(64), comment='项名称')
    stage: Mapped[str] = mapped_column(sa.String(20), default=CalcStage.per_order.value, comment='计算阶段')
    sort_order: Mapped[int] = mapped_column(default=0, comment='执行顺序')
    condition_json: Mapped[dict | None] = mapped_column(sa.JSON(), default=None, comment='触发条件')
    formula_json: Mapped[dict | None] = mapped_column(sa.JSON(), default=None, comment='计算公式')
    condition_expr: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='编译后条件表达式')
    formula_expr: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='编译后公式表达式')
    enabled: Mapped[bool] = mapped_column(default=True, comment='启用')
    remark: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='备注')
