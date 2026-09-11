from datetime import date

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key
from backend.plugin.rider_salary.enums import ImportBatchStatus


class RiderSalaryImportBatch(Base):
    """导入批次表"""

    __tablename__ = 'rs_import_batch'
    __table_args__ = {'comment': '导入批次表'}

    id: Mapped[id_key] = mapped_column(init=False)
    site_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='站点 ID')
    file_name: Mapped[str] = mapped_column(sa.String(256), comment='文件名')
    operator_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='操作人 ID')
    total_rows: Mapped[int] = mapped_column(default=0, comment='总行数')
    success_rows: Mapped[int] = mapped_column(default=0, comment='成功行数')
    failed_rows: Mapped[int] = mapped_column(default=0, comment='失败行数')
    status: Mapped[str] = mapped_column(
        sa.String(20),
        default=ImportBatchStatus.processing.value,
        index=True,
        comment='状态',
    )
    date_from: Mapped[date | None] = mapped_column(sa.Date, default=None, comment='覆盖开始日期')
    date_to: Mapped[date | None] = mapped_column(sa.Date, default=None, comment='覆盖结束日期')
    error_report: Mapped[list | None] = mapped_column(sa.JSON(), default=None, comment='错误报告')
    remark: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='备注')
