"""入参长度、金额、公式节点和完整性错误文案。"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from backend.common.exception import errors
from backend.plugin.rider_salary.schema.adjustment import BatchCreateAdjustmentParam, CreateAdjustmentParam
from backend.plugin.rider_salary.schema.advance import CreateMeAdvanceParam
from backend.plugin.rider_salary.schema.day_flag import DayFlagItem, UpsertDayFlagParam
from backend.plugin.rider_salary.schema.limits import (
    LEN_ADVANCE_REASON,
    LEN_NAME_32,
    MAX_ADJUSTMENT_BATCH,
    MAX_DAY_FLAGS,
    MAX_EXPR_NODES,
    MAX_FORMULA_NODES,
    MAX_LADDER_TIERS,
    MONEY_MAX,
)
from backend.plugin.rider_salary.schema.order import CreateOrderParam
from backend.plugin.rider_salary.schema.plan import CreatePlanParam
from backend.plugin.rider_salary.schema.plan_item import PlanItemParam
from backend.plugin.rider_salary.schema.rider import CreateRiderParam
from backend.plugin.rider_salary.utils.db_errors import client_error_from_integrity
from backend.utils.timezone import timezone


def _integrity(message: str, sqlstate: str) -> IntegrityError:
    class _OrigError(Exception):
        def __init__(self) -> None:
            super().__init__(message)
            self.sqlstate = sqlstate

    return IntegrityError('INSERT', {}, _OrigError())


def _rider(**overrides: object) -> CreateRiderParam:
    payload: dict = {
        'job_no': 'D5A099',
        'name': '张三',
        'site_id': 1,
        'hire_date': date(2026, 9, 1),
    }
    payload.update(overrides)
    return CreateRiderParam.model_validate(payload)


def test_rider_name_max_length() -> None:
    """超长姓名在入参层被拒绝。"""
    with pytest.raises(ValidationError, match='姓名不能超过 32 个字'):
        _rider(name='名' * (LEN_NAME_32 + 1))
    assert _rider(name='名' * LEN_NAME_32).name == '名' * LEN_NAME_32


def test_advance_reason_max_length() -> None:
    """预支原因有长度上限。"""
    with pytest.raises(ValidationError, match='申请原因不能超过 200 个字'):
        CreateMeAdvanceParam(amount=Decimal('100.00'), reason='因' * (LEN_ADVANCE_REASON + 1))
    ok = CreateMeAdvanceParam(amount=Decimal('100.50'), reason='周转')
    assert ok.amount == Decimal('100.50')


def test_money_non_negative_two_decimals() -> None:
    """金额不能为负、不能超过列宽、最多两位小数。"""
    with pytest.raises(ValidationError):
        CreateMeAdvanceParam(amount=Decimal('-1.00'), reason='周转')
    with pytest.raises(ValidationError):
        CreateMeAdvanceParam(amount=Decimal('1.001'), reason='周转')
    with pytest.raises(ValidationError):
        CreateMeAdvanceParam(amount=MONEY_MAX + Decimal('0.01'), reason='周转')
    order = CreateOrderParam.model_validate({
        'order_no': 'NO1',
        'site_id': 1,
        'rider_id': 1,
        'distance_km': '1.20',
        'weight_jin': '0.50',
        'order_time': datetime(2026, 9, 1, 8, 0, tzinfo=timezone.tz_info),
        'status': '已完成',
        'amount': '12.30',
    })
    assert order.distance_km == Decimal('1.20')
    with pytest.raises(ValidationError):
        CreateOrderParam.model_validate({
            'order_no': 'NO1',
            'site_id': 1,
            'rider_id': 1,
            'distance_km': '-0.01',
            'weight_jin': '1',
            'order_time': datetime(2026, 9, 1, 8, 0, tzinfo=timezone.tz_info),
            'status': '已完成',
        })


def test_adjustment_allows_signed_amount_within_cap() -> None:
    """上期补差允许负数，但仍限制位数和绝对值。"""
    item = CreateAdjustmentParam(
        rider_id=1,
        biz_date=date(2026, 9, 1),
        subject_id=1,
        amount=Decimal('-12.50'),
        remark='上期补差',
    )
    assert item.amount == Decimal('-12.50')
    with pytest.raises(ValidationError):
        CreateAdjustmentParam(
            rider_id=1,
            biz_date=date(2026, 9, 1),
            subject_id=1,
            amount=Decimal('-1.234'),
            remark='上期补差',
        )


def test_plan_color_and_short_name() -> None:
    """颜色必须是十六进制，短名不超过 6 个字。"""
    plan = CreatePlanParam(code='C01', name='纯按单', short_name='按单', color='#1677ff')
    assert plan.short_name == '按单'
    with pytest.raises(ValidationError, match='颜色须为十六进制'):
        CreatePlanParam(code='C01', name='纯按单', short_name='按单', color='blue')
    with pytest.raises(ValidationError, match='短名不能超过 6 个字'):
        CreatePlanParam(code='C01', name='纯按单', short_name='一二三四五六七', color='#1677ff')


def test_formula_nodes_and_ladder_tiers() -> None:
    """公式节点和阶梯档数有上限。"""
    tiers = [{'下限': index, '上限': index + 1, '值': 1} for index in range(MAX_LADDER_TIERS + 1)]
    with pytest.raises(ValidationError, match=f'阶梯档位不能超过 {MAX_LADDER_TIERS} 档'):
        PlanItemParam(
            subject_id=1,
            name='阶梯',
            stage='period',
            formula_json={'类型': '阶梯', '字段': '周期单量', '模式': '全量落档', '计价': '按单价', '档位': tiers},
        )
    leaves = [{'字段': '周期单量', '运算符': '大于', '值': index} for index in range(MAX_FORMULA_NODES)]
    with pytest.raises(ValidationError, match='节点不能超过'):
        PlanItemParam(
            subject_id=1,
            name='条件',
            stage='period',
            condition_json={'逻辑': '且', '条件': leaves},
            formula_json={'类型': '固定金额', '金额': 1},
        )
    expr = ' + '.join(['1'] * (MAX_EXPR_NODES + 1))
    with pytest.raises(ValidationError, match='表达式节点不能超过'):
        PlanItemParam(
            subject_id=1,
            name='表达式',
            stage='period',
            formula_json={'类型': '表达式', '表达式': expr},
        )
    ok = PlanItemParam(
        subject_id=1,
        name='按单',
        stage='per_order',
        formula_json={'类型': '固定金额', '金额': 5},
    )
    assert ok.name == '按单'


def test_batch_size_limits() -> None:
    """奖惩和日标记批量条数有上限。"""
    one = CreateAdjustmentParam(
        rider_id=1,
        biz_date=date(2026, 9, 1),
        subject_id=1,
        amount=Decimal('1.00'),
        remark='奖',
    )
    with pytest.raises(ValidationError, match=f'批量条数不能超过 {MAX_ADJUSTMENT_BATCH} 条'):
        BatchCreateAdjustmentParam(items=[one] * (MAX_ADJUSTMENT_BATCH + 1))
    day = DayFlagItem(biz_date=date(2026, 9, 1))
    with pytest.raises(ValidationError, match=f'批量条数不能超过 {MAX_DAY_FLAGS} 条'):
        UpsertDayFlagParam(site_id=1, days=[day] * (MAX_DAY_FLAGS + 1))


def test_integrity_error_messages() -> None:
    """唯一冲突为中文 409，外键和超长为中文 422。"""
    unique = client_error_from_integrity(
        _integrity('duplicate key value violates unique constraint "uk_rs_site_code_deleted"', '23505')
    )
    assert isinstance(unique, errors.ConflictError)
    assert unique.code == 409
    assert unique.msg == '站点编码已存在'

    bound = client_error_from_integrity(
        _integrity('duplicate key value violates unique constraint "uq_rs_rider_one_user"', '23505')
    )
    assert bound.code == 409
    assert bound.msg == '该账号已绑定其他骑手'
    owner = client_error_from_integrity(
        _integrity('duplicate key value violates unique constraint "uq_rs_site_manager_one_owner"', '23505')
    )
    assert owner.code == 409
    assert owner.msg == '该站点已有负责人'

    foreign = client_error_from_integrity(_integrity('insert or update violates foreign key constraint', '23503'))
    assert isinstance(foreign, errors.RequestError)
    assert foreign.code == 422
    assert foreign.msg == '关联的数据不存在或已被删除'

    too_long = client_error_from_integrity(_integrity('value too long for type character varying(32)', '22001'))
    assert too_long.code == 422
    assert too_long.msg == '提交的数据不符合字段约束'
