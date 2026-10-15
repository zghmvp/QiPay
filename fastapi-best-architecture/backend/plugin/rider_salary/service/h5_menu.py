from dataclasses import dataclass

from backend.common.exception import errors
from backend.plugin.rider_salary.schema.calendar import GetCalendarDayDetail, GetCalendarMonth
from backend.plugin.rider_salary.schema.me import GetMeAdvanceLimit, GetMePayrollEstimate

CLOSED_MESSAGE = '该功能暂未开放'
BOOL_FIELDS = (
    'show_adjustments',
    'show_advance',
    'show_notices',
    'show_plan',
    'show_home',
    'show_home_pay',
    'show_day_amount',
    'show_estimate_net',
    'show_advance_inflight',
)
# 整页关闭。当日明细跟随首页。
PAGE_FEATURES = {
    'adjustments': 'show_adjustments',
    'advance': 'show_advance',
    'notices': 'show_notices',
    'plan': 'show_plan',
    'home': 'show_home',
    'day': 'show_home',
    'calendar': 'show_home',
    'payroll': 'show_home',
}


@dataclass(frozen=True)
class H5MenuFlags:
    """骑手端开关。我的和个人资料不在这里。"""

    show_adjustments: bool
    show_advance: bool
    show_notices: bool
    show_plan: bool
    show_home: bool
    show_home_pay: bool
    show_day_amount: bool
    show_estimate_net: bool
    show_advance_inflight: bool
    source: str


def builtin_flags() -> H5MenuFlags:
    """没有保存过规则时，全部开放。"""
    return flags_from_values(source='builtin')


def flags_from_values(*, source: str, **flags: bool) -> H5MenuFlags:
    values = dict.fromkeys(BOOL_FIELDS, True)
    unknown = set(flags) - set(BOOL_FIELDS)
    if unknown:
        raise TypeError(f'未知开关：{", ".join(sorted(unknown))}')
    values.update(flags)
    return H5MenuFlags(source=source, **values)  # type: ignore[arg-type]


def flag_values(flags: H5MenuFlags) -> dict[str, bool]:
    return {name: bool(getattr(flags, name)) for name in BOOL_FIELDS}


def resolve_h5_menu(site_flags: H5MenuFlags | None, global_flags: H5MenuFlags | None) -> H5MenuFlags:
    """站点有行则整行覆盖，否则全局，否则全部开放。"""
    if site_flags is not None:
        return flags_from_values(source='site', **flag_values(site_flags))
    if global_flags is not None:
        return flags_from_values(source='global', **flag_values(global_flags))
    return builtin_flags()


def is_feature_open(flags: H5MenuFlags, feature: str) -> bool:
    """未知功能名视为开放，避免误伤我的和个人资料。"""
    field = PAGE_FEATURES.get(feature)
    if field is None:
        return True
    return bool(getattr(flags, field))


def assert_feature_open(flags: H5MenuFlags, feature: str) -> None:
    """关闭的页面拒绝访问。"""
    if not is_feature_open(flags, feature):
        raise errors.ForbiddenError(msg=CLOSED_MESSAGE)


def mask_payroll_estimate(flags: H5MenuFlags, row: GetMePayrollEstimate) -> GetMePayrollEstimate:
    """首页工资关闭时只留单量和周期，金额置空。"""
    if flags.show_home_pay:
        return row
    return row.model_copy(
        update={
            'gross': None,
            'deduction_total': None,
            'advance_deduction_estimate': None,
            'net_estimate': None,
        }
    )


def mask_calendar_month(flags: H5MenuFlags, row: GetCalendarMonth) -> GetCalendarMonth:
    """当日金额关闭时月历仍返回单量，汇总金额和奖惩净额置空。"""
    if flags.show_day_amount:
        return row
    return row.model_copy(
        update={
            'summary': row.summary.model_copy(
                update={
                    'gross': None,
                    'bonus': None,
                    'penalty': None,
                    'deduction_total': None,
                    'advance_deduction': None,
                    'net': None,
                }
            ),
            'days': [day.model_copy(update={'net_adjust': None}) for day in row.days],
        }
    )


def mask_day_detail(flags: H5MenuFlags, row: GetCalendarDayDetail) -> GetCalendarDayDetail:
    """当日金额关闭时保留单量和订单信息，金额与计算过程置空。"""
    if flags.show_day_amount:
        return row
    return row.model_copy(
        update={
            'totals': row.totals.model_copy(
                update={
                    'formula_amount': None,
                    'manual_bonus': None,
                    'manual_penalty': None,
                    'net': None,
                }
            ),
            'orders': [
                order.model_copy(
                    update={
                        'amount': None,
                        'details': [
                            detail.model_copy(update={'amount': None, 'calc_trace': None}) for detail in order.details
                        ],
                    }
                )
                for order in row.orders
            ],
            'daily_items': [item.model_copy(update={'amount': None, 'calc_trace': None}) for item in row.daily_items],
            'adjustments': [item.model_copy(update={'amount': None}) for item in row.adjustments],
        }
    )


def mask_advance_limit(flags: H5MenuFlags, row: GetMeAdvanceLimit) -> GetMeAdvanceLimit:
    """预估实发、在途占用各自置空。可申请额度保留。"""
    update: dict[str, None] = {}
    if not flags.show_estimate_net:
        update['estimate_net'] = None
    if not flags.show_advance_inflight:
        update['used_pending_amount'] = None
    if not update:
        return row
    return row.model_copy(update=update)
