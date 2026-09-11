from datetime import date, datetime

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase


class DayFlagItem(SchemaBase):
    """单日标记"""

    biz_date: date = Field(description='业务日期')
    bad_weather: bool = Field(False, description='恶劣天气')
    high_temp: bool = Field(False, description='高温')
    promo: bool = Field(False, description='大促')
    remark: str | None = Field(None, description='备注')


class UpsertDayFlagParam(SchemaBase):
    """批量更新日标记参数"""

    site_id: int = Field(description='站点 ID')
    days: list[DayFlagItem] = Field(description='日标记列表')


class GetDayFlagDetail(SchemaBase):
    """日标记详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = Field(None, description='日标记 ID')
    site_id: int = Field(description='站点 ID')
    biz_date: date = Field(description='业务日期')
    bad_weather: bool = Field(False, description='恶劣天气')
    high_temp: bool = Field(False, description='高温')
    promo: bool = Field(False, description='大促')
    remark: str | None = Field(None, description='备注')
    is_locked: bool = Field(False, description='所属周期是否已锁账或已发薪')
    created_time: datetime | None = Field(None, description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
