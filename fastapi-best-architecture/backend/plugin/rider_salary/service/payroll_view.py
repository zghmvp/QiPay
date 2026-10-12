"""有效薪资单读层。

按 (周期, 骑手) 给出当前有效单、其明细，以及净额对照。

有效单：未删除、未作废、不是反冲单、且尚未被反冲。同一组里有多张时，取
``calc_version``、``id`` 最大的一张。因此多轮「原单 → 反冲 → 补发 → 再反冲 →
再补发」只认最新一张未被反冲的补发；反冲后还没补发时，没有有效单。

净差采用 Q-06 推荐方案 A：有当前有效补发时，净差 = 补发实发 − 原单实发；
没有有效补发时净差为 0。最终实发单独给出，等于有效单实发（没有有效单时为 0）。
净额对照里的「反冲」只汇总指向第一张正常单的反冲，后续轮次的反冲留在历史分表。
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from backend.plugin.rider_salary.enums import PayrollKind, PayrollStatus
from backend.plugin.rider_salary.utils.money import q2

ZERO = Decimal('0.00')
_EFFECTIVE_STATUS = {
    PayrollStatus.draft.value,
    PayrollStatus.finalized.value,
    PayrollStatus.paid.value,
}
_KIND_KEYS = (
    PayrollKind.normal.value,
    PayrollKind.reversal.value,
    PayrollKind.supplement.value,
)


def _deleted(row: Any) -> bool:
    return bool(int(getattr(row, 'deleted', 0) or 0))


def _is_voided(row: Any) -> bool:
    return getattr(row, 'status', None) == PayrollStatus.voided.value


def is_live_payroll(row: Any) -> bool:
    """未删除且未作废。反冲单和已被反冲的单仍算在册，供历史追溯。"""
    return not _deleted(row) and not _is_voided(row)


def is_effective_payroll(row: Any) -> bool:
    """当前还能代表该骑手本期应发结果的薪资单。"""
    if not is_live_payroll(row):
        return False
    if getattr(row, 'status', None) not in _EFFECTIVE_STATUS:
        return False
    if getattr(row, 'kind', None) == PayrollKind.reversal.value:
        return False
    return not bool(getattr(row, 'reversed', False))


def _sort_key(row: Any) -> tuple[int, int]:
    return (
        int(getattr(row, 'calc_version', 0) or 0),
        int(getattr(row, 'id', 0) or 0),
    )


def pick_effective_payroll(rows: Sequence[Any]) -> Any | None:
    """
    从同一 (周期, 骑手) 的薪资单里挑出有效单

    :param rows: 该组全部薪资单，可含作废、反冲和已被反冲的单
    :return: 有效单；反冲后尚未补发时返回空
    """
    candidates = [row for row in rows if is_effective_payroll(row)]
    if not candidates:
        return None
    candidates.sort(key=_sort_key, reverse=True)
    return candidates[0]


def _root_original(live: Sequence[Any]) -> Any | None:
    """第一张未作废的正常单，多轮补发之后它仍是净差里的「原单」。"""
    normals = [row for row in live if getattr(row, 'kind', None) == PayrollKind.normal.value]
    if not normals:
        return None
    normals.sort(key=lambda row: int(getattr(row, 'id', 0) or 0))
    return normals[0]


def _reversal_net_of_original(live: Sequence[Any], original: Any | None) -> Decimal:
    """只加总指向原单的反冲。指向后续补发单的反冲不进这一列。"""
    if original is None:
        return ZERO
    original_id = int(getattr(original, 'id', 0) or 0)
    total = ZERO
    for row in live:
        if getattr(row, 'kind', None) != PayrollKind.reversal.value:
            continue
        target = getattr(row, 'reversed_of_id', None)
        if target is not None and int(target) == original_id:
            total += q2(getattr(row, 'net', ZERO) or ZERO)
    return q2(total)


def _money(row: Any | None) -> Decimal:
    if row is None:
        return ZERO
    return q2(getattr(row, 'net', ZERO) or ZERO)


@dataclass(frozen=True)
class RiderPayrollView:
    """一个 (周期, 骑手) 的有效薪资读模型。"""

    period_id: int
    rider_id: int
    effective: Any | None
    details: tuple[Any, ...]
    original_net: Decimal
    reversal_net: Decimal
    supplement_net: Decimal
    net_diff: Decimal
    final_net: Decimal
    has_live: bool


def _details_for(payroll: Any | None, grouped: dict[int, list[Any]]) -> tuple[Any, ...]:
    if payroll is None:
        return ()
    payroll_id = getattr(payroll, 'id', None)
    if payroll_id is None:
        return ()
    return tuple(grouped.get(int(payroll_id), ()))


def _view_for_group(
    period_id: int,
    rider_id: int,
    rows: Sequence[Any],
    detail_groups: dict[int, list[Any]],
) -> RiderPayrollView:
    live = [row for row in rows if is_live_payroll(row)]
    effective = pick_effective_payroll(rows)
    original = _root_original(live)
    original_net = _money(original)
    reversal_net = _reversal_net_of_original(live, original)
    if effective is not None and getattr(effective, 'kind', None) == PayrollKind.supplement.value:
        supplement_net = _money(effective)
        net_diff = q2(supplement_net - original_net) if original is not None else ZERO
    else:
        supplement_net = ZERO
        net_diff = ZERO
    return RiderPayrollView(
        period_id=period_id,
        rider_id=rider_id,
        effective=effective,
        details=_details_for(effective, detail_groups),
        original_net=original_net,
        reversal_net=reversal_net,
        supplement_net=supplement_net,
        net_diff=net_diff,
        final_net=_money(effective),
        has_live=bool(live),
    )


def _detail_groups(details: Sequence[Any] | None) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = defaultdict(list)
    if not details:
        return grouped
    ordered = sorted(details, key=lambda row: int(getattr(row, 'id', 0) or 0))
    for row in ordered:
        if _deleted(row):
            continue
        payroll_id = getattr(row, 'payroll_id', None)
        if payroll_id is None:
            continue
        grouped[int(payroll_id)].append(row)
    return grouped


def build_rider_views(
    payrolls: Sequence[Any],
    details: Sequence[Any] | None = None,
) -> list[RiderPayrollView]:
    """
    按 (周期, 骑手) 组装有效单、明细和净差

    只含至少一张未删除薪资单的组。组的顺序按组内最小薪资单 id，便于导出稳定。

    :param payrolls: 薪资单
    :param details: 明细；只保留有效单上的行
    :return:
    """
    grouped: dict[tuple[int, int], list[Any]] = defaultdict(list)
    for row in payrolls:
        if _deleted(row):
            continue
        period_id = int(getattr(row, 'period_id', 0) or 0)
        rider_id = int(getattr(row, 'rider_id', 0) or 0)
        grouped[period_id, rider_id].append(row)
    detail_groups = _detail_groups(details)
    views = [
        _view_for_group(period_id, rider_id, rows, detail_groups) for (period_id, rider_id), rows in grouped.items()
    ]
    views.sort(key=lambda view: _group_order(grouped[view.period_id, view.rider_id]))
    return views


def _group_order(rows: Sequence[Any]) -> int:
    ids = [int(getattr(row, 'id', 0) or 0) for row in rows]
    return min(ids) if ids else 0


def effective_payroll_ids(payrolls: Sequence[Any]) -> set[int]:
    """有效单 id 集合。"""
    ids: set[int] = set()
    for view in build_rider_views(payrolls):
        payroll = view.effective
        if payroll is None or getattr(payroll, 'id', None) is None:
            continue
        ids.add(int(payroll.id))
    return ids


def details_of_effective(details: Sequence[Any], payrolls: Sequence[Any]) -> list[Any]:
    """只留下有效单上的明细，顺序与传入明细一致。"""
    allowed = effective_payroll_ids(payrolls)
    return [
        row
        for row in details
        if not _deleted(row) and getattr(row, 'payroll_id', None) is not None and int(row.payroll_id) in allowed
    ]


def sum_effective_gross(payrolls: Sequence[Any]) -> Decimal:
    """有效单应发合计。作废、反冲、已被反冲的单不计入。"""
    total = ZERO
    for view in build_rider_views(payrolls):
        payroll = view.effective
        if payroll is None:
            continue
        total += q2(getattr(payroll, 'gross', ZERO) or ZERO)
    return q2(total)


def _empty_kind_counts() -> dict[str, int]:
    return dict.fromkeys(_KIND_KEYS, 0)


def summarize_period_stats(payrolls: Sequence[Any]) -> dict[int, dict[str, Any]]:
    """
    周期列表用的统计

    张数、骑手数、类型分布、需重算数都不含作废单。应发和实发只加总有效单，
    因此与「原单 + 各轮反冲 + 历史补发」的代数和脱钩，也不会把作废草稿算进去。

    :param payrolls: 若干周期的薪资单
    :return: period_id → 统计
    """
    by_period: dict[int, list[Any]] = defaultdict(list)
    for row in payrolls:
        if _deleted(row):
            continue
        by_period[int(getattr(row, 'period_id', 0) or 0)].append(row)
    result: dict[int, dict[str, Any]] = {}
    for period_id, rows in by_period.items():
        live = [row for row in rows if is_live_payroll(row)]
        kind_counts = _empty_kind_counts()
        riders: set[int] = set()
        stale_count = 0
        for row in live:
            riders.add(int(getattr(row, 'rider_id', 0) or 0))
            kind = str(getattr(row, 'kind', '') or '')
            if kind in kind_counts:
                kind_counts[kind] += 1
            if bool(getattr(row, 'stale', False)):
                stale_count += 1
        gross = ZERO
        net = ZERO
        for view in build_rider_views(rows):
            payroll = view.effective
            if payroll is None:
                continue
            gross += q2(getattr(payroll, 'gross', ZERO) or ZERO)
            net += q2(getattr(payroll, 'net', ZERO) or ZERO)
        result[period_id] = {
            'rider_count': len(riders),
            'payroll_count': len(live),
            'stale_count': stale_count,
            'gross_total': q2(gross),
            'net_total': q2(net),
            'kind_counts': kind_counts,
        }
    return result


def live_payrolls_of_kind(payrolls: Sequence[Any], kind: str) -> list[Any]:
    """某一类型的未作废薪资单，按 id 升序。作废单不返回。"""
    rows = [row for row in payrolls if is_live_payroll(row) and getattr(row, 'kind', None) == kind]
    rows.sort(key=lambda row: int(getattr(row, 'id', 0) or 0))
    return rows
