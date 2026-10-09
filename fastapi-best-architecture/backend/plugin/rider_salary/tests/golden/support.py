"""案例库黄金夹具：读取与前端共用的方案 JSON，调用纯函数算薪流水线。"""

import json

from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from backend.plugin.rider_salary.engine.compiler import compile_condition, compile_formula
from backend.plugin.rider_salary.engine.segments import PlanItemView, Segment
from backend.plugin.rider_salary.enums import OrderStatus, SubjectDirection
from backend.plugin.rider_salary.service.calc_service import CalcInput, CalcResult, run_calc_pipeline
from backend.utils.timezone import timezone

TZ = timezone.tz_info
REPO_ROOT = Path(__file__).resolve().parents[6]
PRESET_PATH = (
    REPO_ROOT / 'fastapi-best-architecture-ui/apps/web-antdv-next/src/plugins/rider-salary/constants/plan-presets.json'
)
PRESET_TS_PATH = PRESET_PATH.with_name('plan-presets.ts')
CASES_PATH = Path(__file__).with_name('cases.json')


def load_catalog() -> dict[str, Any]:
    """读取与 `constants/plan-presets.ts` 共用的方案目录。"""
    return json.loads(PRESET_PATH.read_text(encoding='utf-8'))


def load_casebook() -> dict[str, Any]:
    """读取黄金用例（订单分布与案例库期望金额）。"""
    return json.loads(CASES_PATH.read_text(encoding='utf-8'))


def presets_by_id(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """按案例编号索引方案预设。

    :param catalog: 共用方案目录
    :return: 编号到预设的映射
    """
    return {preset['id']: preset for preset in catalog['presets']}


def run_case(case: dict[str, Any], catalog: dict[str, Any] | None = None) -> CalcResult:
    """用共用方案 JSON 和用例订单跑一遍内存算薪。

    :param case: 单条黄金用例
    :param catalog: 方案目录，缺省时从共用 JSON 读取
    :return: 算薪结果
    """
    book = catalog if catalog is not None else load_catalog()
    presets = presets_by_id(book)
    period = _period(case)
    orders = _orders(case.get('orders') or {}, period[0], period[1])
    data = CalcInput(
        rider_id=1,
        site_id=1,
        period_start=period[0],
        period_end=period[1],
        hire_date=date(2025, 3, 1),
        leave_date=None,
        employ_type='full_time',
        segments=_segments(case, presets, period),
        orders=orders,
        day_flags=_day_flags(case.get('day_flags') or []),
        employ_history=[],
        adjustments=_adjustments(case.get('adjustments') or []),
        advances=_advances(case.get('advance')),
        covered_dates=set(_daterange(period[0], period[1])),
        site_order_dates={row.biz_date for row in orders},
        persist_advance=case.get('advance') is not None,
    )
    return run_calc_pipeline(data)


def _period(case: dict[str, Any]) -> tuple[date, date]:
    raw = case.get('period') or load_casebook()['period']
    return date.fromisoformat(raw['start']), date.fromisoformat(raw['end'])


def _daterange(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _segments(
    case: dict[str, Any],
    presets: dict[str, dict[str, Any]],
    period: tuple[date, date],
) -> list[Segment]:
    specs = case.get('segments')
    if not specs:
        window = case.get('segment') or {'start': period[0].isoformat(), 'end': period[1].isoformat()}
        specs = [
            {
                'preset_id': case['preset_id'],
                'start': window['start'],
                'end': window['end'],
                'version_id': 1,
                'ladder_field': case.get('ladder_field'),
            }
        ]
    built: list[Segment] = []
    item_seq = [1]
    for index, spec in enumerate(specs):
        preset = presets[spec['preset_id']]
        start = date.fromisoformat(spec['start'])
        end = date.fromisoformat(spec['end'])
        built.append(
            Segment(
                plan_version_id=int(spec.get('version_id') or index + 1),
                start_date=start,
                end_date=end,
                items=_items(preset, item_seq, spec.get('ladder_field')),
            )
        )
    return built


def _items(preset: dict[str, Any], item_seq: list[int], ladder_field: str | None) -> list[PlanItemView]:
    views: list[PlanItemView] = []
    for index, raw in enumerate(preset['items']):
        formula = deepcopy(raw['formula_json'])
        if ladder_field and formula.get('类型') == '阶梯':
            formula['字段'] = ladder_field
        condition = raw.get('condition_json') or {}
        stage = raw['stage']
        pk = item_seq[0]
        item_seq[0] += 1
        views.append(
            PlanItemView(
                id=pk,
                subject_id=pk,
                name=raw['name'],
                stage=stage,
                sort_order=(index + 1) * 10,
                condition_json=condition,
                formula_json=formula,
                condition_expr=compile_condition(condition, stage),
                formula_expr=compile_formula(formula, stage),
                enabled=True,
                direction=SubjectDirection.bonus.value,
                include_in_gross=True,
            )
        )
    return views


def _orders(spec: dict[str, Any], period_start: date, period_end: date) -> list[SimpleNamespace]:
    seq = [1]
    if 'samples' in spec:
        return [_sample(seq, row) for row in spec['samples']]
    if 'by_date' in spec:
        return _orders_by_date(spec['by_date'], seq)
    if 'pattern' in spec:
        return _pattern(spec['pattern'], period_start, seq)
    if 'parts' in spec:
        rows: list[SimpleNamespace] = []
        for part in spec['parts']:
            rows.extend(_part(part, seq))
        return rows
    return _spread(
        seq,
        _eligible(period_start, period_end, []),
        int(spec.get('completed') or 0),
        int(spec.get('night') or 0),
        int(spec.get('cancelled') or 0),
    )


def _orders_by_date(buckets: list[dict[str, Any]], seq: list[int]) -> list[SimpleNamespace]:
    rows: list[SimpleNamespace] = []
    for bucket in buckets:
        _fill_day(
            rows,
            seq,
            date.fromisoformat(bucket['biz_date']),
            int(bucket['completed']),
            int(bucket.get('night') or 0),
        )
    return rows


def _pattern(blocks: list[dict[str, Any]], start: date, seq: list[int]) -> list[SimpleNamespace]:
    rows: list[SimpleNamespace] = []
    cursor = start
    for block in blocks:
        per_day = int(block['completed'])
        for _ in range(int(block['days'])):
            _fill_day(rows, seq, cursor, per_day, per_day if block.get('night') else 0)
            cursor += timedelta(days=1)
    return rows


def _part(part: dict[str, Any], seq: list[int]) -> list[SimpleNamespace]:
    days = _eligible(date.fromisoformat(part['start']), date.fromisoformat(part['end']), part.get('skip') or [])
    return _spread(seq, days, int(part['completed']), int(part.get('night') or 0), int(part.get('cancelled') or 0))


def _spread(
    seq: list[int],
    days: list[date],
    completed: int,
    night: int,
    cancelled: int,
) -> list[SimpleNamespace]:
    if completed and not days:
        msg = '有效单无法落到跳过之后的空日期'
        raise ValueError(msg)
    counts = _split(completed, len(days)) if days else []
    rows: list[SimpleNamespace] = []
    night_left = night
    for day, count in zip(days, counts, strict=True):
        night_left = _fill_day(rows, seq, day, count, night_left)
    if cancelled:
        anchor = days[0] if days else date(2026, 9, 1)
        rows.extend(_make(seq, anchor, status=OrderStatus.cancelled.value) for _ in range(cancelled))
    return rows


def _fill_day(rows: list[SimpleNamespace], seq: list[int], day: date, count: int, night_left: int) -> int:
    for _ in range(count):
        night = night_left > 0
        if night:
            night_left -= 1
        rows.append(_make(seq, day, night=night))
    return night_left


def _split(total: int, buckets: int) -> list[int]:
    if buckets <= 0:
        return []
    base, extra = divmod(total, buckets)
    return [base + (1 if index < extra else 0) for index in range(buckets)]


def _eligible(start: date, end: date, skip: list[str]) -> list[date]:
    skipped = {date.fromisoformat(item) for item in skip}
    return [day for day in _daterange(start, end) if day not in skipped]


def _sample(seq: list[int], raw: dict[str, Any]) -> SimpleNamespace:
    return _make(
        seq,
        date.fromisoformat(raw['biz_date']),
        night=bool(raw.get('night')),
        distance=raw.get('distance_km', '3.2'),
        weight=raw.get('weight_jin', '4.5'),
        amount=raw.get('amount', '28'),
        status=raw.get('status', OrderStatus.completed.value),
    )


def _make(
    seq: list[int],
    day: date,
    *,
    night: bool = False,
    distance: object = '3.2',
    weight: object = '4.5',
    amount: object = '28',
    status: str = OrderStatus.completed.value,
) -> SimpleNamespace:
    pk = seq[0]
    seq[0] += 1
    if night:
        order_time = _clock(day, 21, 50)
        deliver_time = _clock(day, 22, 18)
    else:
        order_time = _clock(day, 10, 0)
        deliver_time = _clock(day, 10, 28)
    return SimpleNamespace(
        id=pk,
        order_no=f'G-{pk}',
        site_id=1,
        rider_id=1,
        biz_date=day,
        distance_km=Decimal(str(distance)),
        weight_jin=Decimal(str(weight)),
        order_time=order_time,
        deliver_time=deliver_time,
        status=status,
        amount=Decimal(str(amount)),
    )


def _clock(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


def _day_flags(rows: list[dict[str, Any]]) -> dict[date, SimpleNamespace]:
    return {
        date.fromisoformat(row['date']): SimpleNamespace(
            bad_weather=bool(row.get('bad_weather')),
            high_temp=bool(row.get('high_temp')),
            promo=bool(row.get('promo')),
        )
        for row in rows
    }


def _adjustments(rows: list[dict[str, Any]]) -> list[SimpleNamespace]:
    built: list[SimpleNamespace] = []
    for index, row in enumerate(rows, start=1):
        built.append(
            SimpleNamespace(
                id=index,
                subject_id=index,
                amount=Decimal(row['amount']),
                signed_amount=Decimal(row['signed_amount']),
                include_in_gross=bool(row['include_in_gross']),
                direction=row['direction'],
                biz_date=date.fromisoformat(row['biz_date']),
                subject=SimpleNamespace(
                    name='手工奖惩',
                    direction=row['direction'],
                    include_in_gross=bool(row['include_in_gross']),
                ),
            )
        )
    return built


def _advances(raw: dict[str, Any] | None) -> list[SimpleNamespace]:
    if raw is None:
        return []
    paid = date.fromisoformat(raw['paid_date'])
    amount = Decimal(raw['amount'])
    return [
        SimpleNamespace(
            id=1,
            amount=amount,
            remaining_amount=amount,
            deducted_amount=Decimal('0.00'),
            deduct_status='none',
            paid_time=_clock(paid, 12, 0),
        )
    ]
