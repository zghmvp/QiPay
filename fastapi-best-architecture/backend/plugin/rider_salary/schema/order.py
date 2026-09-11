from datetime import date, datetime
from decimal import Decimal

from pydantic import ConfigDict, Field, field_validator

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.enums import OrderSource, OrderStatus
from backend.utils.timezone import timezone


def _aware_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.tz_info)
    return timezone.from_datetime(value)


class OrderSchemaBase(SchemaBase):
    """订单基础字段"""

    order_no: str = Field(description='订单号')
    site_id: int = Field(description='站点 ID')
    rider_id: int = Field(description='骑手 ID')
    distance_km: Decimal = Field(description='配送距离（公里）')
    weight_jin: Decimal = Field(description='商品重量（斤）')
    order_time: datetime = Field(description='下单时间')
    deliver_time: datetime | None = Field(None, description='送达时间')
    status: str = Field(description='订单状态')
    amount: Decimal | None = Field(None, description='订单金额')
    remark: str | None = Field(None, description='备注')


class CreateOrderParam(OrderSchemaBase):
    """补录订单参数"""

    @field_validator('order_time', 'deliver_time')
    @classmethod
    def ensure_timezone(cls, value: datetime | None) -> datetime | None:
        return _aware_datetime(value)


class UpdateOrderParam(SchemaBase):
    """纠错订单参数"""

    reason: str = Field(description='修改原因')
    order_no: str | None = Field(None, description='订单号')
    site_id: int | None = Field(None, description='站点 ID')
    rider_id: int | None = Field(None, description='骑手 ID')
    distance_km: Decimal | None = Field(None, description='配送距离（公里）')
    weight_jin: Decimal | None = Field(None, description='商品重量（斤）')
    order_time: datetime | None = Field(None, description='下单时间')
    deliver_time: datetime | None = Field(None, description='送达时间')
    status: str | None = Field(None, description='订单状态')
    amount: Decimal | None = Field(None, description='订单金额')
    remark: str | None = Field(None, description='备注')

    @field_validator('order_time', 'deliver_time')
    @classmethod
    def ensure_timezone(cls, value: datetime | None) -> datetime | None:
        return _aware_datetime(value)


class GetOrderDetail(OrderSchemaBase):
    """订单详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='订单 ID')
    biz_date: date = Field(description='业务日期')
    source: str = Field(description='来源')
    source_label: str = Field('', description='来源中文')
    import_batch_id: int | None = Field(None, description='导入批次 ID')
    is_locked: bool = Field(description='是否已锁账')
    rider_job_no: str = Field('', description='骑手工号')
    rider_name: str = Field('', description='骑手姓名')
    site_name: str = Field('', description='站点名称')
    status_label: str = Field('', description='状态中文')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')


class ImportErrorItem(SchemaBase):
    """导入错误行"""

    row: int = Field(description='行号')
    order_no: str | None = Field(None, description='订单号')
    reason: str = Field(description='失败原因')


class ImportResult(SchemaBase):
    """导入结果"""

    batch_id: int | None = Field(None, description='批次 ID')
    total_rows: int = Field(description='总行数')
    success_rows: int = Field(description='成功行数')
    failed_rows: int = Field(description='失败行数')
    status: str = Field(description='批次状态')
    errors: list[ImportErrorItem] = Field(default_factory=list, description='错误列表（最多 100 条）')


def order_status_label(status: str) -> str:
    """订单状态中文"""
    try:
        return OrderStatus(status).label
    except ValueError:
        return OrderStatus.LABELS.get(status, status)


def order_source_label(source: str) -> str:
    """订单来源中文"""
    if source == OrderSource.import_.value:
        return OrderSource.import_.label
    try:
        return OrderSource(source).label
    except ValueError:
        return OrderSource.LABELS.get(source, source)
