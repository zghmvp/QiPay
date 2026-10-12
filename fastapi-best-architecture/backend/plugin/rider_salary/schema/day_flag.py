from datetime import date, datetime
from typing import Annotated

from pydantic import ConfigDict, Field, field_validator

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.schema.limits import LEN_REMARK, MAX_DAY_FLAGS, zh_list, zh_str


class DayFlagItem(SchemaBase):
    """单日标记"""

    biz_date: date = Field(description='业务日期')
    bad_weather: bool = Field(False, description='恶劣天气')
    high_temp: bool = Field(False, description='高温')
    promo: bool = Field(False, description='大促')
    remark: Annotated[str | None, zh_str('备注', LEN_REMARK)] = Field(None, max_length=LEN_REMARK, description='备注')


class UpsertDayFlagParam(SchemaBase):
    """批量更新日标记参数"""

    site_id: int = Field(description='站点 ID')
    days: Annotated[list[DayFlagItem], zh_list('批量条数', MAX_DAY_FLAGS)] = Field(
        max_length=MAX_DAY_FLAGS, description='日标记列表'
    )

    @field_validator('days')
    @classmethod
    def limit_days(cls, value: list[DayFlagItem]) -> list[DayFlagItem]:
        """限制批量条数"""
        if len(value) > MAX_DAY_FLAGS:
            raise ValueError(f'批量条数不能超过 {MAX_DAY_FLAGS} 条')
        return value


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
