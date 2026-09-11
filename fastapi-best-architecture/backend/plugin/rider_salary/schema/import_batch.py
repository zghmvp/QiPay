from datetime import date, datetime

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import ImportBatchStatus


class GetImportBatchDetail(SchemaBase):
    """导入批次详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='批次 ID')
    site_id: int = Field(description='站点 ID')
    site_name: str = Field('', description='站点名称')
    file_name: str = Field(description='文件名')
    operator_id: int = Field(description='操作人 ID')
    total_rows: int = Field(description='总行数')
    success_rows: int = Field(description='成功行数')
    failed_rows: int = Field(description='失败行数')
    status: str = Field(description='状态')
    status_label: str = Field('', description='状态中文')
    date_from: date | None = Field(None, description='覆盖开始日期')
    date_to: date | None = Field(None, description='覆盖结束日期')
    error_report: list | None = Field(None, description='错误报告')
    remark: str | None = Field(None, description='备注')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')


class GetImportBatchListItem(SchemaBase):
    """导入批次列表项"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='批次 ID')
    site_id: int = Field(description='站点 ID')
    site_name: str = Field('', description='站点名称')
    file_name: str = Field(description='文件名')
    operator_id: int = Field(description='操作人 ID')
    total_rows: int = Field(description='总行数')
    success_rows: int = Field(description='成功行数')
    failed_rows: int = Field(description='失败行数')
    status: str = Field(description='状态')
    status_label: str = Field('', description='状态中文')
    date_from: date | None = Field(None, description='覆盖开始日期')
    date_to: date | None = Field(None, description='覆盖结束日期')
    created_time: datetime = Field(description='创建时间')


def import_batch_status_label(status: str) -> str:
    """批次状态中文"""
    try:
        return ImportBatchStatus(status).label
    except ValueError:
        return ImportBatchStatus.LABELS.get(status, status)
