from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import DataClassBase, TimeZone, UniversalText, id_key
from backend.utils.timezone import timezone


class RiderSalaryAuditLog(DataClassBase):
    """业务审计日志表"""

    __tablename__ = 'rs_audit_log'
    __table_args__ = (
        sa.Index('ix_rs_audit_log_module_action', 'module', 'action'),
        sa.Index('ix_rs_audit_log_target', 'target_type', 'target_id'),
        {'comment': '业务审计日志表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    operator_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='操作人 ID')
    operator_name: Mapped[str] = mapped_column(sa.String(64), comment='操作人姓名')
    operate_time: Mapped[datetime] = mapped_column(TimeZone, comment='操作时间')
    module: Mapped[str] = mapped_column(sa.String(64), comment='模块')
    action: Mapped[str] = mapped_column(sa.String(64), comment='动作')
    target_type: Mapped[str] = mapped_column(sa.String(64), comment='对象类型')
    target_label: Mapped[str] = mapped_column(sa.String(256), comment='对象摘要')
    target_id: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='对象 ID')
    site_id: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        default=None,
        index=True,
        comment='所属站点；空表示全局目录或无法归属',
    )
    reason: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='原因')
    before: Mapped[dict | None] = mapped_column(sa.JSON(), default=None, comment='变更前')
    after: Mapped[dict | None] = mapped_column(sa.JSON(), default=None, comment='变更后')
    description: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='自然语言描述')
    ip: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='IP')
    trace_id: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='追踪 ID')
    created_time: Mapped[datetime] = mapped_column(
        TimeZone,
        init=False,
        default_factory=timezone.now,
        comment='创建时间',
    )
    updated_time: Mapped[datetime | None] = mapped_column(
        TimeZone,
        init=False,
        onupdate=timezone.now,
        comment='更新时间',
    )
