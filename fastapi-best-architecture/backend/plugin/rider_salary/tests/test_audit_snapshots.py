"""P3-09 审计快照与操作人显示名。

关键写路径的 audit_service.record 必须带 before/after。
占位昵称「用户」加数字不能进入操作人名称或描述；没有请求时写「系统」。
"""

import ast
import re

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anyio

from backend.plugin.rider_salary.model.audit_log import RiderSalaryAuditLog
from backend.plugin.rider_salary.schema.day_flag import DayFlagItem, UpsertDayFlagParam
from backend.plugin.rider_salary.schema.period import (
    CalculatePeriodParam,
    GeneratePeriodParam,
    GetGeneratedPeriodItem,
)
from backend.plugin.rider_salary.schema.rider import DisableRiderAccountParam, EnableRiderAccountParam
from backend.plugin.rider_salary.service.calc_service import CalcResult, _persist_result
from backend.plugin.rider_salary.service.day_flag_service import day_flag_service
from backend.plugin.rider_salary.service.import_service import import_service
from backend.plugin.rider_salary.service.payroll_service import payroll_service
from backend.plugin.rider_salary.service.period_service import PeriodService, period_service
from backend.plugin.rider_salary.service.rider_service import RiderService, rider_service
from backend.plugin.rider_salary.utils.audit import audit_service, mask_audit_phones, operator_display_name

_SERVICE = Path(__file__).resolve().parents[1] / 'service'
_PLACEHOLDER = re.compile(r'用户\d+')
_PLAN_WRITES = (
    'create_plan',
    'update_plan',
    'delete_plan',
    'create_version',
    'update_version',
    'delete_version',
    'replace_items',
    'trial',
    'activate',
    'disable',
    'copy',
)
# 这几条是更新或删除，before/after 都不能写成 None
_NONE_FORBIDDEN = (
    ('day_flag_service.py', 'DayFlagService.upsert', '更新日标记'),
    ('rollback_service.py', 'RollbackService.rollback', '解除绑定'),
    ('rollback_service.py', 'RollbackService.rollback', '方案回退'),
    ('plan_service.py', 'PlanService.replace_items', '更新方案项'),
    ('rider_service.py', 'RiderService.open_account', '开通骑手账号'),
    ('rider_service.py', 'RiderService.reset_password', '重置骑手密码'),
    ('rider_service.py', 'RiderService.disable_account', '停用骑手账号'),
    ('rider_service.py', 'RiderService.enable_account', '启用骑手账号'),
    ('rider_service.py', 'RiderService.create_binding', '新增方案绑定'),
    ('payroll_service.py', 'PayrollService.create_reversal', '反冲补发'),
    ('period_service.py', 'PeriodService.generate', '生成周期'),
    ('period_service.py', 'PeriodService.create_leave_settlement', '生成离职结算周期'),
    ('period_service.py', 'PeriodService.calculate', '算薪'),
    ('period_service.py', 'PeriodService.delete', '删除周期'),
    ('import_service.py', 'ImportService.import_orders', '导入订单'),
    ('calc_service.py', '_persist_result', '重算'),
)


def _parse(filename: str) -> ast.AST:
    return ast.parse((_SERVICE / filename).read_text(encoding='utf-8'))


def _method(tree: ast.AST, qualname: str) -> ast.AsyncFunctionDef:
    if '.' not in qualname:
        for node in tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name == qualname:
                return node
        raise AssertionError(f'找不到 {qualname}')
    class_name, func_name = qualname.split('.')
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == func_name:
                    return item
    raise AssertionError(f'找不到 {qualname}')


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f'{base}.{node.attr}' if base else node.attr
    return ''


def _record_calls(func: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.Call) and _call_name(node.func) == 'audit_service.record'
    ]


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for item in call.keywords:
        if item.arg == name:
            return item.value
    return None


def _constant(node: ast.expr | None) -> object:
    if isinstance(node, ast.Constant):
        return node.value
    return None


def _is_none_literal(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _uses_name(func: ast.AST, name: str) -> bool:
    return any(isinstance(node, ast.Name) and node.id == name for node in ast.walk(func))


def _dict_keys(node: ast.expr | None) -> list[str]:
    if not isinstance(node, ast.Dict):
        return []
    return [key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)]


def _action(call: ast.Call) -> str | None:
    value = _constant(_keyword(call, 'action'))
    return value if isinstance(value, str) else None


class _Capture:
    def __init__(self) -> None:
        self.row = None

    def add(self, row: object) -> None:
        self.row = row


def test_operator_display_name_skips_placeholder_and_uses_system() -> None:
    """占位昵称回退用户名；只有占位昵称时不写「用户数字」；后台任务写系统。"""
    admin = SimpleNamespace(user=SimpleNamespace(nickname='用户88888', username='admin', id=1))
    assert operator_display_name(admin) == 'admin'
    only_placeholder = SimpleNamespace(user=SimpleNamespace(nickname='用户9', username=None, id=2))
    assert operator_display_name(only_placeholder) == '未知'
    assert not _PLACEHOLDER.search(operator_display_name(only_placeholder))
    assert operator_display_name(None) == '系统'
    assert operator_display_name(SimpleNamespace(user=None)) == '未知'


def test_record_scrubs_placeholder_and_keeps_phone_for_read_mask() -> None:
    """自定义描述里的占位昵称换成用户名；入库不打码，读取时仍打码。"""
    db = _Capture()
    request = SimpleNamespace(user=SimpleNamespace(id=1, nickname='用户88888', username='admin'))

    async def _case() -> None:
        await audit_service.record(
            db,  # type: ignore[arg-type]
            request,  # type: ignore[arg-type]
            module='日标记',
            action='更新日标记',
            target_type='day_flag',
            target_id=3,
            target_label='站点 3',
            description='用户88888 于 2026-10-09 对 站点 3 执行了更新日标记',
            before={'phone': '13812348000'},
            after={'count': 1},
        )

    anyio.run(_case)
    assert db.row is not None
    assert db.row.operator_name == 'admin'
    assert db.row.operator_id == 1
    assert db.row.site_id == 3
    assert not _PLACEHOLDER.search(db.row.description or '')
    assert (db.row.description or '').startswith('admin ')
    assert db.row.before == {'phone': '13812348000'}
    assert mask_audit_phones(db.row.before)['phone'] == '138****8000'


def test_record_without_operator_writes_system() -> None:
    """没有请求时操作人是系统，描述里也不出现占位昵称。"""
    db = _Capture()

    async def _case() -> None:
        await audit_service.record(
            db,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            module='结算周期',
            action='重算',
            target_type='day_flag',
            target_id=1,
            target_label='后台重算',
            before={'stale': True},
            after={'stale': False},
        )

    anyio.run(_case)
    assert db.row is not None
    assert db.row.operator_name == '系统'
    assert db.row.operator_id == 0
    assert db.row.ip is None
    assert (db.row.description or '').startswith('系统 ')
    assert not _PLACEHOLDER.search(db.row.description or '')
    assert db.row.before == {'stale': True}
    assert db.row.after == {'stale': False}


def test_changed_write_paths_pass_before_and_after() -> None:
    """改过的方案写路径，以及日标记、回退，审计调用都带 before/after。"""
    plan = _parse('plan_service.py')
    for name in _PLAN_WRITES:
        calls = _record_calls(_method(plan, f'PlanService.{name}'))
        assert calls, f'PlanService.{name} 没有审计'
        for call in calls:
            assert _keyword(call, 'before') is not None, name
            assert _keyword(call, 'after') is not None, name
    for filename, qualname, action in _NONE_FORBIDDEN:
        matched = [call for call in _record_calls(_method(_parse(filename), qualname)) if _action(call) == action]
        assert matched, f'{qualname} 缺少动作 {action}'
        for call in matched:
            before = _keyword(call, 'before')
            after = _keyword(call, 'after')
            assert before is not None and not _is_none_literal(before)
            assert after is not None and not _is_none_literal(after)


def test_touched_services_do_not_spell_operator_locally() -> None:
    """操作人显示名只留在 utils/audit.py。"""
    for name in (
        'advance_service.py',
        'export_service.py',
        'rollback_service.py',
        'day_flag_service.py',
        'plan_service.py',
        'import_service.py',
    ):
        text = (_SERVICE / name).read_text(encoding='utf-8')
        assert 'def _operator_name' not in text
        assert '用户88888' not in text


def test_day_flag_upsert_records_each_day() -> None:
    """批量日标记：已有行记变更前，新行记不存在，变更后带本次提交的标记。"""
    obj = UpsertDayFlagParam(
        site_id=3,
        days=[
            DayFlagItem(biz_date=date(2026, 10, 1), bad_weather=True, remark='雨'),
            DayFlagItem(biz_date=date(2026, 10, 2), promo=True),
        ],
    )
    existed = SimpleNamespace(
        id=8,
        site_id=3,
        biz_date=date(2026, 10, 1),
        bad_weather=False,
        high_temp=False,
        promo=False,
        remark=None,
    )
    created = SimpleNamespace(
        id=9,
        site_id=3,
        biz_date=date(2026, 10, 2),
        bad_weather=False,
        high_temp=False,
        promo=True,
        remark=None,
    )

    async def _case() -> None:
        with (
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.get_visible_site_ids',
                AsyncMock(return_value=None),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.site_dao.get',
                AsyncMock(return_value=SimpleNamespace(id=3)),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.site_locked_dates',
                AsyncMock(return_value=set()),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.day_flag_dao.get_by_site_date',
                AsyncMock(side_effect=[existed, None]),
            ),
            patch('backend.plugin.rider_salary.service.day_flag_service.day_flag_dao.update', AsyncMock()),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.day_flag_dao.create',
                AsyncMock(return_value=created),
            ),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.rider_ids_for_day_flag_recalc',
                AsyncMock(return_value=[1]),
            ),
            patch('backend.plugin.rider_salary.service.day_flag_service.mark_stale', AsyncMock()),
            patch(
                'backend.plugin.rider_salary.service.day_flag_service.audit_service.record',
                AsyncMock(),
            ) as audit,
        ):
            await day_flag_service.upsert(db=AsyncMock(), request=SimpleNamespace(user=None), obj=obj)
        before = audit.await_args.kwargs['before']
        after = audit.await_args.kwargs['after']
        assert before['count'] == 2
        assert before['days'][0]['id'] == 8
        assert before['days'][0]['bad_weather'] is False
        assert before['days'][1] == {'biz_date': '2026-10-02', 'exists': False}
        assert after['count'] == 2
        assert after['days'][0]['bad_weather'] is True
        assert after['days'][0]['remark'] == '雨'
        assert after['days'][0]['biz_date'] == '2026-10-01'
        assert after['days'][1]['id'] == 9
        assert after['days'][1]['promo'] is True

    anyio.run(_case)


def test_account_status_audit_keeps_previous_status() -> None:
    """停用、启用账号时，before 是改之前的账号状态。"""
    rider = SimpleNamespace(id=4, job_no='D0004', name='周敏', user_id=18, status='on_job')
    prefix = 'backend.plugin.rider_salary.service.rider_service.'
    audit = AsyncMock()

    async def _case() -> None:
        with (
            patch.object(RiderService, '_get_visible_rider', AsyncMock(return_value=rider)),
            patch(
                f'{prefix}user_dao.get',
                AsyncMock(side_effect=[SimpleNamespace(status=1), SimpleNamespace(status=0)]),
            ),
            patch(f'{prefix}user_dao.set_status', AsyncMock()) as set_status,
            patch(f'{prefix}redis_client.delete', AsyncMock()),
            patch(f'{prefix}redis_client.delete_by_prefix', AsyncMock()),
            patch(f'{prefix}audit_service.record', audit),
        ):
            await rider_service.disable_account(
                db=AsyncMock(),
                request=SimpleNamespace(user=SimpleNamespace(id=1)),
                pk=4,
                obj=DisableRiderAccountParam(reason='暂停接单'),
            )
            await rider_service.enable_account(
                db=AsyncMock(),
                request=SimpleNamespace(user=SimpleNamespace(id=1)),
                pk=4,
                obj=EnableRiderAccountParam(reason='恢复接单'),
            )
        assert set_status.await_args_list[0].args[2] == 0
        assert set_status.await_args_list[1].args[2] == 1
        disabled, enabled = audit.await_args_list
        assert disabled.kwargs['before'] == {'user_id': 18, 'status': 1}
        assert disabled.kwargs['after'] == {'user_id': 18, 'status': 0}
        assert enabled.kwargs['before'] == {'user_id': 18, 'status': 0}
        assert enabled.kwargs['after'] == {'user_id': 18, 'status': 1}

    anyio.run(_case)


class _ReversalDb:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, row: object) -> None:
        self.added.append(row)

    async def execute(self, _stmt: object) -> SimpleNamespace:
        return SimpleNamespace(rowcount=None)

    async def flush(self) -> None:
        return None

    async def scalar(self, _stmt: object) -> None:
        return None


def _payroll() -> SimpleNamespace:
    money = Decimal('10.00')
    return SimpleNamespace(
        id=7,
        period_id=3,
        rider_id=4,
        kind='normal',
        status='finalized',
        reversed=False,
        calc_version=2,
        stale=False,
        warnings=[],
        order_count=1,
        valid_order_count=1,
        per_order_total=money,
        daily_total=money,
        period_total=money,
        bonus_total=Decimal('0.00'),
        penalty_total=Decimal('0.00'),
        gross=money,
        deduction_total=Decimal('0.00'),
        advance_deduction=Decimal('0.00'),
        net=money,
        plan_version_ids=[],
        reversed_of_id=None,
    )


def test_create_reversal_without_operator_audits_as_system() -> None:
    """没有操作人时仍写反冲审计，操作人是系统，并带原单与反冲单快照。"""
    db = _ReversalDb()
    payroll = _payroll()

    async def _case() -> None:
        with patch(
            'backend.plugin.rider_salary.service.payroll_service.payroll_detail_dao.list_by_payroll',
            AsyncMock(return_value=[]),
        ):
            await payroll_service.create_reversal(db, payroll, None, '后台反冲')  # type: ignore[arg-type]

    anyio.run(_case)
    logs = [row for row in db.added if isinstance(row, RiderSalaryAuditLog)]
    assert len(logs) == 1
    log = logs[0]
    assert log.operator_name == '系统'
    assert log.operator_id == 0
    assert log.action == '反冲补发'
    assert log.before['id'] == 7
    assert log.before['reversed'] is False
    assert log.before['net'] == '10.00'
    assert log.after['payroll']['reversed'] is True
    assert log.after['reversal']['kind'] == 'reversal'
    assert log.after['reversal']['reversed_of_id'] == 7
    assert log.after['reversal']['net'] == '-10.00'
    assert not _PLACEHOLDER.search(log.description or '')
    assert (log.description or '').startswith('系统 ')


def test_period_operator_switch_leaves_locked_actions() -> None:
    """生成、离职结算、算薪改用统一显示名；锁账四条仍用原来的本地拼接。删除本来就没有本地拼接。"""
    tree = _parse('period_service.py')
    for name in ('generate', 'create_leave_settlement', 'calculate'):
        func = _method(tree, f'PeriodService.{name}')
        assert _uses_name(func, 'operator_display_name'), name
        assert not _uses_name(func, '_operator_name'), name
    delete = _method(tree, 'PeriodService.delete')
    assert not _uses_name(delete, '_operator_name')
    for name in ('lock', 'mark_paid', 'reverse', 'carry_forward'):
        func = _method(tree, f'PeriodService.{name}')
        assert _uses_name(func, '_operator_name'), name
        assert not _uses_name(func, 'operator_display_name'), name


def test_import_order_summary_is_not_a_per_row_snapshot() -> None:
    """成功订单只记条数和日期范围，对象编号不是批次主键，避免按订单回查。"""
    calls = _record_calls(_method(_parse('import_service.py'), 'ImportService.import_orders'))
    order_calls = [call for call in calls if _constant(_keyword(call, 'target_type')) == 'order']
    batch_calls = [call for call in calls if _constant(_keyword(call, 'target_type')) == 'import_batch']
    assert len(order_calls) == 1
    assert len(batch_calls) == 1
    order_call = order_calls[0]
    assert _is_none_literal(_keyword(order_call, 'target_id'))
    assert _keyword(order_call, 'site_id') is not None
    assert _dict_keys(_keyword(order_call, 'after')) == ['count', 'date_from', 'date_to', 'rider_count']
    assert 'error_report' not in ast.dump(batch_calls[0])


def _admin_request() -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(id=1, nickname='用户88888', username='admin'))


class _Rows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


def test_generate_records_existing_periods_before_counts() -> None:
    """生成周期：跳过的已有周期进 before，after 仍是新建和跳过数量。"""
    site = SimpleNamespace(id=5, code='D5', name='东站', settle_cycle='month', cycle_config=None)
    skipped = GetGeneratedPeriodItem(
        id=12,
        site_id=5,
        rider_id=0,
        cycle_type='month',
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
        status='open',
        created=False,
    )
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=_Rows([]))
    prefix = 'backend.plugin.rider_salary.service.period_service.'

    async def _case() -> None:
        with (
            patch(f'{prefix}get_visible_site_ids', AsyncMock(return_value=None)),
            patch(f'{prefix}site_dao.get', AsyncMock(return_value=site)),
            patch(f'{prefix}assert_period_plan', AsyncMock()),
            patch.object(PeriodService, '_ensure_listed', AsyncMock(return_value=skipped)),
            patch(f'{prefix}audit_service.record', AsyncMock()) as audit,
        ):
            result = await period_service.generate(
                db=db,
                request=_admin_request(),  # type: ignore[arg-type]
                obj=GeneratePeriodParam(site_id=5, month='2026-10'),
            )
        assert result.created_count == 0
        assert result.skipped_count == 1
        kwargs = audit.await_args.kwargs
        assert kwargs['action'] == '生成周期'
        assert kwargs['target_id'] == 5
        assert kwargs['before']['existing_count'] == 1
        assert kwargs['before']['existing'][0]['id'] == 12
        assert kwargs['before']['existing'][0]['start_date'] == '2026-10-01'
        assert kwargs['after'] == {'created': 0, 'skipped': 1}
        assert (kwargs['description'] or '').startswith('admin ')
        assert not _PLACEHOLDER.search(kwargs['description'] or '')

    anyio.run(_case)


def test_leave_settlement_snapshots_only_when_created() -> None:
    """新离职周期记不存在和落库后的周期；沿用已有周期不写审计。"""
    rider = SimpleNamespace(
        id=4,
        site_id=3,
        status='resigned',
        leave_date=date(2026, 10, 15),
        job_no='D0004',
        name='周敏',
    )
    site = SimpleNamespace(id=3, name='东站', settle_cycle='month', cycle_config=None)
    period = SimpleNamespace(
        id=11,
        site_id=3,
        rider_id=4,
        cycle_type='month',
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
        status='open',
        remark='离职结算，计薪截至2026-10-15',
    )
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=rider)
    db.scalars = AsyncMock(return_value=_Rows([]))
    prefix = 'backend.plugin.rider_salary.service.period_service.'

    async def _case() -> None:
        with (
            patch(f'{prefix}get_visible_site_ids', AsyncMock(return_value=None)),
            patch(f'{prefix}site_dao.get', AsyncMock(return_value=site)),
            patch(f'{prefix}assert_period_plan', AsyncMock()),
            patch(f'{prefix}settle_period_dao.get_by_unique', AsyncMock(return_value=None)),
            patch.object(PeriodService, '_create_if_absent', AsyncMock(return_value=period)),
            patch(f'{prefix}audit_service.record', AsyncMock()) as audit,
        ):
            created = await period_service.create_leave_settlement(
                db=db,
                request=_admin_request(),  # type: ignore[arg-type]
                pk=4,
            )
            covering = SimpleNamespace(
                id=8,
                site_id=3,
                rider_id=4,
                start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 31),
                status='open',
                remark=None,
            )
            db.scalars = AsyncMock(return_value=_Rows([covering]))
            reused = await period_service.create_leave_settlement(
                db=db,
                request=_admin_request(),  # type: ignore[arg-type]
                pk=4,
            )
        assert created.created is True
        assert created.period_id == 11
        kwargs = audit.await_args.kwargs
        assert kwargs['before'] == {'exists': False, 'rider_id': 4, 'start_date': '2026-10-01'}
        assert kwargs['after']['id'] == 11
        assert kwargs['after']['leave_date'] == '2026-10-15'
        assert kwargs['after']['end_date'] == '2026-10-31'
        assert (kwargs['description'] or '').startswith('admin ')
        assert reused.created is False
        assert reused.period_id == 8
        assert audit.await_count == 1

    anyio.run(_case)


def test_calculate_snapshots_period_and_job() -> None:
    """算薪入队前记下周期，入队后带作业号和人数，不改返回值。"""
    period = SimpleNamespace(
        id=3,
        site_id=5,
        rider_id=0,
        cycle_type='month',
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
        status='open',
        remark=None,
    )
    outcome = SimpleNamespace(job_id=77, queued=True, calculated=0, warnings=['稍后重算'])
    prefix = 'backend.plugin.rider_salary.service.period_service.'

    async def _case() -> None:
        with (
            patch.object(
                PeriodService, '_load_visible', AsyncMock(return_value=(period, SimpleNamespace(name='东站'), None))
            ),
            patch(f'{prefix}riders_for_period', AsyncMock(return_value=[1, 2])),
            patch(
                'backend.plugin.rider_salary.service.calc_job_service.enqueue_period_calc',
                AsyncMock(return_value=outcome),
            ) as enqueue,
            patch(f'{prefix}read_period_calc_warnings', AsyncMock(return_value=['已有告警'])),
            patch(f'{prefix}audit_service.record', AsyncMock()) as audit,
        ):
            result = await period_service.calculate(
                db=AsyncMock(),
                request=_admin_request(),  # type: ignore[arg-type]
                pk=3,
                obj=CalculatePeriodParam(),
            )
        assert result.job_id == 77
        assert result.queued is True
        assert result.calculated == 0
        assert enqueue.await_count == 1
        kwargs = audit.await_args.kwargs
        assert kwargs['before']['id'] == 3
        assert kwargs['before']['status'] == 'open'
        assert kwargs['after']['job_id'] == 77
        assert kwargs['after']['queued'] is True
        assert kwargs['after']['calculated'] == 0
        assert kwargs['after']['rider_count'] == 2
        assert kwargs['after']['status'] == 'open'
        assert (kwargs['description'] or '').startswith('admin ')

    anyio.run(_case)


def test_delete_period_marks_deleted_after() -> None:
    """删除周期保留删除前快照，并在 after 标上已删除。"""
    period = SimpleNamespace(
        id=3,
        site_id=5,
        rider_id=0,
        cycle_type='month',
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
        status='open',
        remark='待删',
    )
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    prefix = 'backend.plugin.rider_salary.service.period_service.'

    async def _case() -> None:
        with (
            patch.object(
                PeriodService, '_load_visible', AsyncMock(return_value=(period, SimpleNamespace(name='东站'), None))
            ),
            patch(f'{prefix}settle_period_dao.delete', AsyncMock()) as delete,
            patch(f'{prefix}audit_service.record', AsyncMock()) as audit,
        ):
            await period_service.delete(db=db, request=_admin_request(), pk=3)  # type: ignore[arg-type]
        assert delete.await_count == 1
        kwargs = audit.await_args.kwargs
        assert kwargs['before']['id'] == 3
        assert kwargs['before']['remark'] == '待删'
        assert 'deleted' not in kwargs['before']
        assert kwargs['after']['deleted'] is True
        assert kwargs['after']['id'] == 3
        assert kwargs['after']['remark'] == '待删'

    anyio.run(_case)


class _ImportDb:
    def __init__(self, site: object) -> None:
        self.site = site
        self.added: list[object] = []
        self._scalar_calls = 0

    def add(self, row: object) -> None:
        row.id = 21  # type: ignore[attr-defined]
        self.added.append(row)

    def add_all(self, rows: list[object]) -> None:
        self.added.extend(rows)

    async def flush(self) -> None:
        return None

    async def scalar(self, _stmt: object) -> object:
        return self.site

    async def scalars(self, _stmt: object) -> _Rows:
        self._scalar_calls += 1
        if self._scalar_calls == 1:
            return _Rows([self.site])
        return _Rows([])


def test_import_orders_audits_batch_and_written_order_summary() -> None:
    """导入成功时写批次前后，并另记成功订单的条数和日期范围。"""
    site = SimpleNamespace(id=3, code='D3', name='东站')
    order = SimpleNamespace(rider_id=9, biz_date=date(2026, 10, 3), import_batch_id=None)
    upload = SimpleNamespace(filename='orders.xlsx', size=20, read=AsyncMock(return_value=b'x'))
    prefix = 'backend.plugin.rider_salary.service.import_service.'

    async def _case() -> None:
        with (
            patch(f'{prefix}get_visible_site_ids', AsyncMock(return_value=None)),
            patch(f'{prefix}load_upload_rows', return_value=[{'_row': 2, 'site_code': 'D3', 'job_no': 'D0009'}]),
            patch(f'{prefix}order_dao.get_existing_order_nos', AsyncMock(return_value=set())),
            patch(f'{prefix}_prefetch_import_locks', AsyncMock()),
            patch(f'{prefix}_validate_import_row', AsyncMock(return_value=None)),
            patch(f'{prefix}_build_orders', return_value=[order]),
            patch(f'{prefix}mark_stale', AsyncMock()) as stale,
            patch(f'{prefix}audit_service.record', AsyncMock()) as audit,
        ):
            result = await import_service.import_orders(
                db=_ImportDb(site),  # type: ignore[arg-type]
                request=_admin_request(),  # type: ignore[arg-type]
                file=upload,  # type: ignore[arg-type]
                site_id=3,
            )
        assert result.success_rows == 1
        assert result.batch_id == 21
        assert stale.await_count == 1
        assert audit.await_count == 2
        batch, written = audit.await_args_list
        assert batch.kwargs['target_type'] == 'import_batch'
        assert batch.kwargs['target_id'] == 21
        assert batch.kwargs['before'] == {'exists': False, 'site_id': 3, 'file_name': 'orders.xlsx'}
        assert batch.kwargs['after']['success_rows'] == 1
        assert batch.kwargs['after']['date_from'] == '2026-10-03'
        assert batch.kwargs['after']['date_to'] == '2026-10-03'
        assert 'error_report' not in batch.kwargs['after']
        assert written.kwargs['target_type'] == 'order'
        assert written.kwargs['target_id'] is None
        assert written.kwargs['site_id'] == 3
        assert written.kwargs['before'] == {'exists': False, 'count': 0}
        assert written.kwargs['after'] == {
            'count': 1,
            'date_from': '2026-10-03',
            'date_to': '2026-10-03',
            'rider_count': 1,
        }
        assert (batch.kwargs['description'] or '').startswith('admin ')
        assert (written.kwargs['description'] or '').startswith('admin ')
        assert not _PLACEHOLDER.search(batch.kwargs['description'] or '')
        assert order.import_batch_id == 21

    anyio.run(_case)


class _PersistDb:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, row: object) -> None:
        self.added.append(row)

    def add_all(self, _rows: object) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def scalar(self, _stmt: object) -> None:
        return None


def _calc_result(net: str) -> CalcResult:
    amount = Decimal(net)
    zero = Decimal('0.00')
    return CalcResult(
        rider_id=4,
        period_id=3,
        payroll_id=None,
        order_count=2,
        valid_order_count=2,
        per_order_total=amount,
        daily_total=zero,
        period_total=zero,
        bonus_total=zero,
        penalty_total=zero,
        gross=amount,
        deduction_total=zero,
        advance_deduction=zero,
        advance_deductible=zero,
        net=amount,
        plan_version_ids=[2],
        warnings=['新告警'],
        details=[],
        dailies=[],
    )


def _draft_payroll() -> SimpleNamespace:
    money = Decimal('1.00')
    zero = Decimal('0.00')
    return SimpleNamespace(
        id=9,
        period_id=3,
        rider_id=4,
        kind='normal',
        status='draft',
        calc_version=1,
        stale=True,
        gross=money,
        net=money,
        advance_deduction=zero,
        deduction_total=zero,
        order_count=1,
        valid_order_count=1,
        per_order_total=money,
        daily_total=zero,
        period_total=zero,
        bonus_total=zero,
        penalty_total=zero,
        plan_version_ids=[2],
        warnings=['旧告警'],
        calc_by=8,
        calc_time=None,
    )


def test_persist_result_audits_system_and_keeps_previous_amounts() -> None:
    """没有操作人时也写重算审计，操作人是系统；有操作人时 before 是覆盖前的金额。"""
    period = SimpleNamespace(id=3, site_id=5, start_date=date(2026, 10, 1), end_date=date(2026, 10, 31))
    rider = SimpleNamespace(id=4, job_no='D0004')
    first = _draft_payroll()
    second = _draft_payroll()
    db = _PersistDb()
    prefix = 'backend.plugin.rider_salary.service.calc_service.'

    async def _case() -> None:
        with (
            patch(
                f'{prefix}_prepare_payroll_for_persist',
                AsyncMock(side_effect=[(period, first), (period, second)]),
            ),
            patch(f'{prefix}payroll_detail_dao.logical_delete_by_payroll', AsyncMock()),
        ):
            await _persist_result(
                db,  # type: ignore[arg-type]
                rider=rider,  # type: ignore[arg-type]
                period=period,  # type: ignore[arg-type]
                result=_calc_result('8.00'),
                operator=None,
            )
            await _persist_result(
                db,  # type: ignore[arg-type]
                rider=rider,  # type: ignore[arg-type]
                period=period,  # type: ignore[arg-type]
                result=_calc_result('8.00'),
                operator=_admin_request(),  # type: ignore[arg-type]
            )

    anyio.run(_case)
    logs = [row for row in db.added if isinstance(row, RiderSalaryAuditLog)]
    assert len(logs) == 2
    system, admin = logs
    assert system.operator_name == '系统'
    assert system.operator_id == 0
    assert system.action == '重算'
    assert system.site_id == 5
    assert system.before['net'] == '1.00'
    assert system.before['stale'] is True
    assert system.before['calc_version'] == 1
    assert system.before['warnings'] == ['旧告警']
    assert system.after['net'] == '8.00'
    assert system.after['stale'] is False
    assert system.after['calc_version'] == 2
    assert system.after['warnings'] == ['新告警']
    assert system.after['calc_by'] is None
    assert (system.description or '').startswith('系统 ')
    assert admin.operator_name == 'admin'
    assert admin.before['calc_by'] == 8
    assert admin.after['calc_by'] == 1
    assert (admin.description or '').startswith('admin ')
    assert not _PLACEHOLDER.search(admin.description or '')
