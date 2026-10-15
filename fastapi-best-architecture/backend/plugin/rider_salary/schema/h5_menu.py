from typing import Literal

from pydantic import Field

from backend.common.schema import SchemaBase


class SaveH5MenuParam(SchemaBase):
    """保存骑手端菜单开关"""

    site_id: int = Field(description='站点 ID，0 表示全局默认')
    show_adjustments: bool = Field(description='是否开放奖惩')
    show_advance: bool = Field(description='是否开放预支')
    show_notices: bool = Field(description='是否开放公告')
    show_plan: bool = Field(description='是否开放当前方案')
    show_home: bool = Field(description='是否开放首页')
    show_home_pay: bool = Field(description='是否显示首页工资')
    show_day_amount: bool = Field(description='是否显示当日金额')
    show_estimate_net: bool = Field(description='是否显示预估实发')
    show_advance_inflight: bool = Field(description='是否显示在途占用')


class GetH5Menu(SaveH5MenuParam):
    """骑手端菜单开关详情"""

    source: Literal['site', 'global', 'builtin'] = Field(description='规则来源：站点、全局、系统默认')
    site_name: str = Field(description='站点名称，全局时为全局默认')


class GetMeH5Menu(SchemaBase):
    """骑手看到的菜单开关"""

    show_adjustments: bool = Field(description='是否开放奖惩')
    show_advance: bool = Field(description='是否开放预支')
    show_notices: bool = Field(description='是否开放公告')
    show_plan: bool = Field(description='是否开放当前方案')
    show_home: bool = Field(description='是否开放首页')
    show_home_pay: bool = Field(description='是否显示首页工资')
    show_day_amount: bool = Field(description='是否显示当日金额')
    show_estimate_net: bool = Field(description='是否显示预估实发')
    show_advance_inflight: bool = Field(description='是否显示在途占用')
