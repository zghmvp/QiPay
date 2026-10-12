from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import Field

from backend.common.schema import SchemaBase
from backend.plugin.rider_salary.schema.advance import GetAdvanceDetail
from backend.plugin.rider_salary.schema.calendar import GetCalendarDayDetail, GetCalendarMonth
from backend.plugin.rider_salary.schema.limits import LEN_PASSWORD, zh_str
from backend.plugin.rider_salary.schema.notice import GetNoticeDetail


class MeCurrentPlan(SchemaBase):
    """当前生效方案摘要"""

    version_id: int | None = Field(None, description='版本 ID')
    plan_name: str | None = Field(None, description='方案名称')
    short_name: str | None = Field(None, description='短名')
    version_no: int | None = Field(None, description='版本号')
    mode_tag: str | None = Field(None, description='计薪模式')
    start_date: date | None = Field(None, description='生效开始')
    end_date: date | None = Field(None, description='生效结束')


class GetMeProfile(SchemaBase):
    """骑手端个人资料"""

    rider_id: int = Field(description='骑手 ID')
    job_no: str = Field(description='工号')
    name: str = Field(description='姓名')
    site_id: int = Field(description='站点 ID')
    site_name: str = Field(description='站点名')
    employ_type: str = Field(description='用工类型')
    employ_type_label: str = Field(description='用工类型中文')
    hire_date: date = Field(description='入职日期')
    status: str = Field(description='在职状态')
    status_label: str = Field(description='在职状态中文')
    leave_date: date | None = Field(None, description='离职日期')
    read_only: bool = Field(description='是否只读。离职宽限期内为真，不能提交预支')
    read_until: date | None = Field(None, description='只读查阅截止日期，含当天')
    current_plan: MeCurrentPlan | None = Field(None, description='当前生效方案')
    advance_limit: Decimal = Field(description='预支上限')
    has_in_flight_advance: bool = Field(description='是否有进行中预支')


class GetMePayrollEstimate(SchemaBase):
    """当前周期预计工资"""

    period_range: str = Field(description='周期区间')
    period_status: str = Field(description='周期状态')
    order_count: int = Field(description='单量')
    gross: Decimal = Field(description='应发')
    deduction_total: Decimal = Field(description='代扣')
    advance_deduction_estimate: Decimal = Field(description='预支抵扣（预估）')
    net_estimate: Decimal = Field(description='实发预估')
    is_estimate: bool = Field(description='是否实时预估')
    updated_at: datetime | None = Field(None, description='更新时间')


class GetMeAdjustmentItem(SchemaBase):
    """骑手端奖惩"""

    id: int = Field(description='奖惩 ID')
    biz_date: date = Field(description='日期')
    subject_name: str = Field(description='科目名')
    direction: str = Field(description='方向')
    amount: Decimal = Field(description='金额（带符号）')
    remark: str = Field(description='备注')


class MePlanItem(SchemaBase):
    """方案项（无公式）"""

    name: str = Field(description='项名称')
    subject_name: str = Field(description='科目')


class GetMePlanBinding(SchemaBase):
    """已绑定方案"""

    plan_version_id: int = Field(description='版本 ID')
    plan_name: str = Field(description='方案名称')
    short_name: str = Field(description='短名')
    color: str = Field(description='颜色')
    version_no: int = Field(description='版本号')
    mode_tag: str = Field(description='计薪模式')
    binding_type: str = Field(description='绑定类型')
    start_date: date = Field(description='开始日期')
    end_date: date | None = Field(None, description='结束日期')
    is_current: bool = Field(description='是否当前生效')
    items: list[MePlanItem] = Field(default_factory=list, description='项名称与科目')


class GetMePlan(SchemaBase):
    """当前与未来方案"""

    bindings: list[GetMePlanBinding] = Field(default_factory=list, description='绑定列表')


class GetMeAdvanceLimit(SchemaBase):
    """预支额度。可用额度 = 上限 − 在途 − 已发放未抵扣。"""

    limit: Decimal = Field(description='上限')
    used_pending_amount: Decimal = Field(description='在途占用')
    outstanding_amount: Decimal = Field(description='已发放未抵扣')
    available: Decimal = Field(description='可用额度')


class GetMeCalendar(GetCalendarMonth):
    """骑手端月历"""


class GetMeDayDetail(GetCalendarDayDetail):
    """骑手端日详情（不含表达式）"""


class GetMeNotice(GetNoticeDetail):
    """骑手端公告"""


class GetMeAdvance(GetAdvanceDetail):
    """骑手端预支记录"""


class GetMePayslipItem(SchemaBase):
    """往期工资条。只含已定稿或已发薪的有效单。"""

    id: int = Field(description='薪资单 ID')
    period_id: int = Field(description='结算周期 ID')
    period_range: str = Field(description='周期区间')
    period_status: str = Field(description='周期状态')
    period_status_label: str = Field(description='周期状态中文')
    kind: str = Field(description='薪资单类型')
    kind_label: str = Field(description='薪资单类型中文')
    status: str = Field(description='薪资单状态')
    status_label: str = Field(description='薪资单状态中文')
    order_count: int = Field(description='单量')
    gross: Decimal = Field(description='应发')
    deduction_total: Decimal = Field(description='代扣')
    advance_deduction: Decimal = Field(description='预支抵扣')
    net: Decimal = Field(description='实发')
    calc_time: datetime | None = Field(None, description='计算时间')


class GetMePayslipLine(SchemaBase):
    """工资条明细行。同一阶段、科目、来源的金额已合并，不含计算过程。"""

    stage: str = Field(description='计算阶段')
    stage_label: str = Field(description='计算阶段中文')
    subject_name: str = Field(description='科目名称')
    source: str = Field(description='来源')
    source_label: str = Field(description='来源中文')
    amount: Decimal = Field(description='金额（带符号）')
    line_count: int = Field(description='合并的明细条数')


class GetMePayslipDetail(GetMePayslipItem):
    """工资条明细"""

    lines: list[GetMePayslipLine] = Field(default_factory=list, description='按阶段与科目合并的明细')


class ChangeMePasswordParam(SchemaBase):
    """骑手修改本人密码"""

    old_password: Annotated[str, zh_str('原密码', LEN_PASSWORD, min_length=1)] = Field(
        min_length=1, max_length=LEN_PASSWORD, description='原密码'
    )
    new_password: Annotated[str, zh_str('新密码', LEN_PASSWORD, min_length=1)] = Field(
        min_length=1, max_length=LEN_PASSWORD, description='新密码'
    )
    confirm_password: Annotated[str, zh_str('确认密码', LEN_PASSWORD, min_length=1)] = Field(
        min_length=1, max_length=LEN_PASSWORD, description='确认密码'
    )
