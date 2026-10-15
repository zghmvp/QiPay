from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from backend.plugin.rider_salary.utils.money import q2

ZERO = Decimal('0.00')
IN_FLIGHT_REASON = '已有一笔待审核或待发放的预支，请等待处理完成后再申请'


def _plain_number(value: Decimal) -> str:
    """整数不带小数，避免界面出现 50.00。"""
    quantized = q2(value)
    if quantized == quantized.to_integral():
        return str(int(quantized))
    return format(quantized, 'f')


@dataclass(frozen=True)
class AdvanceRule:
    """预支规则。"""

    amount_mode: str
    percent: Decimal
    fixed_amount: Decimal
    max_amount: Decimal | None
    monthly_max_count: int
    min_tenure_days: int
    min_completed_orders: int
    min_amount: Decimal


def builtin_rule() -> AdvanceRule:
    """未配置时的默认规则：按预估实发 50%，每月最多 2 次。"""
    return AdvanceRule(
        amount_mode='percent',
        percent=Decimal(50),
        fixed_amount=Decimal('3000.00'),
        max_amount=None,
        monthly_max_count=2,
        min_tenure_days=7,
        min_completed_orders=1,
        min_amount=Decimal('1.00'),
    )


@dataclass(frozen=True)
class AdvanceQuote:
    """一次预支额度试算结果。"""

    limit: Decimal
    used_pending_amount: Decimal
    available: Decimal
    estimate_net: Decimal
    order_count: int
    amount_mode: str
    percent: Decimal
    monthly_used_count: int
    monthly_max_count: int
    min_amount: Decimal
    eligible: bool
    reasons: tuple[str, ...]
    basis_text: str
    period_range: str
    period_status: str


def quote_advance(
    *,
    rule: AdvanceRule,
    estimate_net: Decimal,
    order_count: int,
    period_status: str,
    period_range: str,
    hire_date: date | None,
    today: date,
    on_job: bool,
    rider_limit: Decimal | None,
    site_limit: Decimal | None,
    in_flight_amount: Decimal,
    in_flight_count: int,
    monthly_count: int,
    undeducted_amount: Decimal = ZERO,
) -> AdvanceQuote:
    """
    计算可预支额度。

    百分比模式按当前周期预估实发计算。固定额度、规则封顶、骑手上限、站点上限同时存在时取更小值。
    在途金额与已发放尚未扣回的金额都从额度中扣除。资格不满足时可用额度为 0。
    """
    net = q2(estimate_net)
    reasons: list[str] = []
    if not on_job:
        reasons.append('离职骑手不能申请预支')
    if rule.min_tenure_days > 0:
        if hire_date is None:
            reasons.append('未登记入职日期，暂不能预支')
        elif (today - hire_date).days < rule.min_tenure_days:
            reasons.append(f'入职未满 {rule.min_tenure_days} 天，暂不能预支')
    if order_count < rule.min_completed_orders:
        reasons.append(f'本周期完成订单不足 {rule.min_completed_orders} 单')
    if rule.monthly_max_count <= 0:
        reasons.append('当前规则禁止预支')
    elif monthly_count >= rule.monthly_max_count:
        reasons.append(f'本月预支次数已达上限 {rule.monthly_max_count} 次')

    if rule.amount_mode == 'fixed':
        raw = q2(rule.fixed_amount)
        basis = f'固定额度 {raw} 元'
    else:
        raw = q2(net * q2(rule.percent) / Decimal(100)) if net > 0 else ZERO
        basis = f'按当前周期预估实发的 {_plain_number(rule.percent)}%'
        if net <= 0:
            reasons.append('当前周期预估实发不足，不能预支')
    quota = raw
    if rule.max_amount is not None:
        quota = min(quota, q2(rule.max_amount))
    if rider_limit is not None:
        quota = min(quota, q2(rider_limit))
    if site_limit is not None:
        quota = min(quota, q2(site_limit))
    quota = q2(max(quota, ZERO))
    used = q2(in_flight_amount + undeducted_amount)
    available = q2(max(quota - used, ZERO))

    hard = list(reasons)
    if in_flight_count > 0:
        reasons.append(IN_FLIGHT_REASON)
    if not hard and available < q2(rule.min_amount):
        reasons.append(f'可用额度低于单笔最低金额 {q2(rule.min_amount)} 元')
    if hard:
        available = ZERO
    eligible = not reasons and available >= q2(rule.min_amount)
    return AdvanceQuote(
        limit=quota,
        used_pending_amount=used,
        available=available,
        estimate_net=net,
        order_count=order_count,
        amount_mode=rule.amount_mode,
        percent=q2(rule.percent),
        monthly_used_count=monthly_count,
        monthly_max_count=rule.monthly_max_count,
        min_amount=q2(rule.min_amount),
        eligible=eligible,
        reasons=tuple(reasons),
        basis_text=basis,
        period_range=period_range,
        period_status=period_status,
    )
