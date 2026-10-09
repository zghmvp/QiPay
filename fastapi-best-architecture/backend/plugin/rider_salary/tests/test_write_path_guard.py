"""三件套守护：AST 扫描写入五张算薪事实表的函数，必须带锁账、重算、审计。

识别规则（只看 ``service/`` 的函数；``crud/`` 只用来识别 DAO 写方法）：

1. 构造模型并 ``db.add`` / ``db.add_all``（会话名须为 ``db`` 或 ``session``）。
   模型来自构造调用、返回注解，或 ``list[模型]`` / 列表推导。
2. DAO 的写方法：crud 类里调用了 ``create_model`` / ``update_model`` /
   ``update_model_by_column`` / ``delete_model`` / ``delete_model_by_column`` 的方法。
   含用工历史的 ``close_open``。读方法不算写入。
3. ``sqlalchemy.update(模型)`` / ``sqlalchemy.delete(模型)``。出现即算写入，不追踪是否 ``execute``。
4. 直接改模型属性：对象来自 DAO 读取、``select(模型)`` 或带模型注解的参数（视为已加载），
   且属性名是映射列或逻辑删除/审计混入列。非映射属性（例如临时挂上的 ``direction``）不算。
   新建后尚未加载的对象只改字段、再 ``add``，只算第 1 类。

三件套可以写在本函数，或写在下面的等价封装 / 白名单调用链里。封装必须真的调用到根函数，
只保留同名空函数不算数。

已知盲区：

- 字符串 SQL、``text()``、``bulk_insert_mappings`` / ``bulk_update_mappings`` / ``merge`` / ``setattr``。
- ``sqlalchemy`` 以 ``sa.update`` 这种模块属性调用。
- 会话变量不叫 ``db`` / ``session``。
- 解包赋值（``a, b = ...``）、把已加载实例当参数传进另一个函数再改属性（参数没标模型注解）。
- 注解成 ``list[Any]`` 的容器。``run_calc_pipeline`` 在带符号金额为 0 时会给元素赋值，
  扫描器看不到元素类型。``_backfill_adjustments`` 的参数标成
  ``list[RiderSalaryAdjustment]``，所以 ``period_id`` 赋值能被认出来，并在白名单里豁免。
  ``_load_calc_input`` 只在内存里推导空的带符号金额，不再回写列。
- 只构造模型、由调用方 ``add`` 的工厂（如 ``_build_orders``）本身不算写入点。
- crud 层是持久化原语，三件套记在 service 调用方，不记在 DAO 方法上。
"""

from __future__ import annotations

import ast
import shutil

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
GUARDED_TABLES = frozenset({
    'rs_order',
    'rs_adjustment',
    'rs_rider_plan_binding',
    'rs_day_flag',
    'rs_rider_employ_history',
})
CRUD_WRITE_ATTRS = frozenset({
    'create_model',
    'update_model',
    'update_model_by_column',
    'delete_model',
    'delete_model_by_column',
})
# 锁账根：调用到其中任何一个即视为做过锁账校验。
LOCK_ROOTS = frozenset({'assert_not_locked', 'assert_range_unlocked', 'site_locked_dates'})
# 这些函数自己不写根名字，但函数体必须调用到锁账根，调用方才算锁账。
LOCK_WRAPPERS = frozenset({'_is_locked', '_assert_transfer_allowed', '_locked_hire_change'})
STALE_ROOTS = frozenset({'mark_stale'})
STALE_WRAPPERS = frozenset({'_mark_employ_stale'})
SESSION_NAMES = frozenset({'db', 'session'})
# 插件模型不重复声明这些混入列，但软删会写它们。
MIXIN_COLUMNS = frozenset({
    'id',
    'created_by',
    'updated_by',
    'created_time',
    'updated_time',
    'deleted',
    'deleted_time',
})
GUARD_LABELS = {'lock': '锁账校验', 'stale': '重算标记', 'audit': '审计'}


@dataclass(frozen=True)
class ValueKind:
    """表达式推断出的模型形态。"""

    model: str | None = None
    shape: str = 'none'
    origin: str = 'unknown'


NONE = ValueKind()


@dataclass(frozen=True)
class DaoInfo:
    """一个 CRUD 实例上、属于五张表的写方法与返回形态。"""

    model: str
    write_methods: frozenset[str]
    returns: Mapping[str, ValueKind]


@dataclass
class FuncFacts:
    """单个函数的调用与写入，三件套在第二遍按调用链汇总。"""

    path: str
    qualname: str
    line: int
    bare: set[str] = field(default_factory=set)
    qualified: set[str] = field(default_factory=set)
    tables: set[str] = field(default_factory=set)
    kinds: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class WriteSite:
    """一处写入及它最终是否覆盖三件套。"""

    path: str
    qualname: str
    line: int
    tables: frozenset[str]
    kinds: frozenset[str]
    lock: bool
    stale: bool
    audit: bool


@dataclass(frozen=True)
class Waiver:
    """允许缺某几件的例外。``skip`` 取 lock / stale / audit。"""

    path: str
    qualname: str
    skip: frozenset[str]
    reason: str
    audit_callers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class CallChain:
    """写入函数之外、允许继续查找三件套的调用链。"""

    path: str
    qualname: str
    hops: tuple[str, ...]
    reason: str


@dataclass
class ScanResult:
    """一次扫描的写入点、全部函数和模型表名。"""

    sites: tuple[WriteSite, ...]
    functions: dict[tuple[str, str], FuncFacts]
    tables_by_model: Mapping[str, str]


# 长期豁免必须写原因。原因里出现「待修」视为还没处理完。
WAIVERS = (
    Waiver(
        path='service/rollback_service.py',
        qualname='RollbackService.rollback',
        skip=frozenset({'lock', 'stale'}),
        reason=(
            '方案回退是越过锁账的受控通道：仅超级管理员、必须填写原因，已发薪还需确认文案。'
            '解除绑定时软删 rs_rider_plan_binding，不再做写前锁账校验，也不 mark_stale。'
            '回退会作废草稿、生成反冲单，并把已定稿或已发薪周期打回补发中，后续由补发算薪重算。'
            '每条绑定的审计带解除前快照和删除后快照。'
        ),
    ),
    Waiver(
        path='service/calc_service.py',
        qualname='_backfill_adjustments',
        skip=frozenset({'lock', 'stale', 'audit'}),
        reason=(
            '算薪落库时回填 rs_adjustment.period_id，标明这条奖惩被哪个周期归集。'
            '纲要规定算薪时回填；锁账和反冲按业务日期改 is_locked，列表也不按这个字段过滤。'
            '写入发生在算薪锁内、周期仍可出单、本次正在为它出薪资单，不是改奖惩金额，'
            '所以不再做写前锁账校验，也不 mark_stale。审计记在重算薪资单上。'
        ),
    ),
    Waiver(
        path='service/period_service.py',
        qualname='PeriodService.set_locked_flags',
        skip=frozenset({'lock', 'stale', 'audit'}),
        reason=(
            '锁账、反冲、方案回退时回写订单和奖惩的 is_locked。这是锁账动作本身，不再做写前锁账校验；'
            '锁标志不是算薪事实变更，不 mark_stale。审计记在调用方，调用方集合必须与 audit_callers 一致，'
            '且每个调用方体内有 audit_service.record。'
        ),
        audit_callers=(
            ('service/period_service.py', 'PeriodService.lock'),
            ('service/period_service.py', 'PeriodService.reverse'),
            ('service/rollback_service.py', 'RollbackService.rollback'),
        ),
    ),
)
CALL_CHAINS = (
    CallChain(
        path='service/import_service.py',
        qualname='ImportService.import_orders',
        hops=('_validate_import_row', '_is_locked'),
        reason=(
            '导入的锁账在逐行校验里：import_orders → _validate_import_row → _is_locked → assert_not_locked。'
            '重算和审计在 import_orders 本函数。'
        ),
    ),
)
WAIVER_BY_KEY = {(item.path, item.qualname): item for item in WAIVERS}
CHAIN_BY_KEY = {(item.path, item.qualname): item for item in CALL_CHAINS}

# 检测回归：这些写入点必须被认出来。多出来的、三件套齐全的写入不在这里卡死。
EXPECTED_SITES = (
    ('service/import_service.py', 'ImportService.import_orders', 'construct_add', 'rs_order'),
    ('service/order_service.py', 'OrderService.create', 'construct_add', 'rs_order'),
    ('service/order_service.py', 'OrderService.update', 'attr_flush', 'rs_order'),
    ('service/order_service.py', 'OrderService.delete', 'dao_write', 'rs_order'),
    ('service/adjustment_service.py', 'AdjustmentService.create', 'dao_write', 'rs_adjustment'),
    ('service/adjustment_service.py', 'AdjustmentService.update', 'dao_write', 'rs_adjustment'),
    ('service/adjustment_service.py', 'AdjustmentService.delete', 'dao_write', 'rs_adjustment'),
    ('service/day_flag_service.py', 'DayFlagService.upsert', 'dao_write', 'rs_day_flag'),
    ('service/rider_service.py', 'RiderService.create', 'dao_write', 'rs_rider_employ_history'),
    ('service/rider_service.py', 'RiderService.leave', 'dao_write', 'rs_rider_employ_history'),
    ('service/rider_service.py', 'RiderService.create_employ_history', 'dao_write', 'rs_rider_employ_history'),
    ('service/rider_service.py', 'RiderService.update_employ_history', 'dao_write', 'rs_rider_employ_history'),
    ('service/rider_service.py', 'RiderService.delete_employ_history', 'dao_write', 'rs_rider_employ_history'),
    ('service/rider_service.py', 'RiderService.create_binding', 'dao_write', 'rs_rider_plan_binding'),
    ('service/rider_service.py', 'RiderService.update_binding', 'dao_write', 'rs_rider_plan_binding'),
    ('service/rider_service.py', 'RiderService.delete_binding', 'dao_write', 'rs_rider_plan_binding'),
    ('service/period_service.py', 'PeriodService.set_locked_flags', 'sql_dml', 'rs_order'),
    ('service/period_service.py', 'PeriodService.set_locked_flags', 'sql_dml', 'rs_adjustment'),
    ('service/rollback_service.py', 'RollbackService.rollback', 'attr_flush', 'rs_rider_plan_binding'),
    ('service/calc_service.py', '_backfill_adjustments', 'attr_flush', 'rs_adjustment'),
)

SQL_PROBE = """\
from sqlalchemy import delete, update

from backend.plugin.rider_salary.model.adjustment import RiderSalaryAdjustment
from backend.plugin.rider_salary.model.order import RiderSalaryOrder


async def rewrite_locked_rows(db, audit_service) -> None:
    await assert_not_locked(db, site_id=1, rider_id=1, biz_date=None)
    await db.execute(update(RiderSalaryOrder).where(RiderSalaryOrder.id == 1).values(remark='x'))
    await db.execute(delete(RiderSalaryAdjustment).where(RiderSalaryAdjustment.id == 1))
    await mark_stale(db, rider_ids=[1], date_from=None, date_to=None)
    await audit_service.record(db, None)
"""


def _parse(path: Path) -> ast.AST:
    """解析源码，语法错误时带上路径。"""
    try:
        return ast.parse(path.read_text(encoding='utf-8'))
    except SyntaxError as exc:
        raise AssertionError(f'{path} 无法解析：{exc}') from exc


def _name_of(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return None


def _annotation_kind(node: ast.expr | None, models: set[str]) -> ValueKind:
    """从注解取出模型名和 scalar/list。``模型 | None`` 视为 scalar。"""
    if node is None:
        return NONE
    if isinstance(node, ast.Name):
        if node.id in models:
            return ValueKind(node.id, 'scalar', 'annotated')
        return NONE
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _annotation_kind(node.left, models)
        if left.model:
            return left
        return _annotation_kind(node.right, models)
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        outer = node.value.id
        if outer in {'list', 'Sequence', 'set', 'tuple'}:
            inner = _annotation_kind(node.slice, models)
            if inner.model:
                return ValueKind(inner.model, 'list', 'annotated')
        if outer == 'Optional':
            return _annotation_kind(node.slice, models)
    return NONE


def _class_model(node: ast.ClassDef) -> str | None:
    for base in node.bases:
        if isinstance(base, ast.Subscript) and isinstance(base.slice, ast.Name):
            return base.slice.id
    return None


def _tablename(node: ast.ClassDef) -> str | None:
    for stmt in node.body:
        if not isinstance(stmt, ast.Assign) or not isinstance(stmt.value, ast.Constant):
            continue
        targets = [target.id for target in stmt.targets if isinstance(target, ast.Name)]
        if '__tablename__' in targets and isinstance(stmt.value.value, str):
            return stmt.value.value
    return None


def _column_names(node: ast.ClassDef) -> frozenset[str]:
    """类体里的注解列，加上框架混入的主键、时间和软删列。"""
    names = set(MIXIN_COLUMNS)
    for stmt in node.body:
        target = stmt.target if isinstance(stmt, ast.AnnAssign) else None
        if isinstance(target, ast.Name):
            names.add(target.id)
        if isinstance(stmt, ast.Assign):
            for item in stmt.targets:
                if isinstance(item, ast.Name) and not item.id.startswith('_'):
                    names.add(item.id)
    return frozenset(names)


def _load_models(root: Path) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
    """类名 → 表名，以及类名 → 列名。"""
    tables: dict[str, str] = {}
    columns: dict[str, frozenset[str]] = {}
    for path in sorted((root / 'model').glob('*.py')):
        tree = _parse(path)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            table = _tablename(node)
            if table is None:
                continue
            tables[node.name] = table
            columns[node.name] = _column_names(node)
    return tables, columns


def _crud_write_methods(node: ast.ClassDef) -> set[str]:
    found: set[str] = set()
    for item in node.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in _calls_under(item):
            func = call.func
            if not isinstance(func, ast.Attribute) or func.attr not in CRUD_WRITE_ATTRS:
                continue
            if isinstance(func.value, ast.Name) and func.value.id == 'self':
                found.add(item.name)
    return found


def _crud_instances(tree: ast.AST) -> list[tuple[str, str]]:
    """模块级 ``name = CRUDClass(...)`` / ``name: CRUDClass = ...``。"""
    found: list[tuple[str, str]] = []
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.annotation, ast.Name)
        ):
            found.append((node.target.id, node.annotation.id))
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            func = node.value.func if isinstance(node.value, ast.Call) else None
            if isinstance(func, ast.Name):
                found.append((node.targets[0].id, func.id))
    return found


def _method_returns(node: ast.ClassDef, models: set[str]) -> dict[str, ValueKind]:
    found: dict[str, ValueKind] = {}
    for item in node.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        kind = _annotation_kind(item.returns, models)
        if kind.model:
            found[item.name] = ValueKind(kind.model, kind.shape, 'persistent')
    return found


def _load_daos(root: Path, models: set[str]) -> dict[tuple[str, str], DaoInfo]:
    catalog: dict[tuple[str, str], DaoInfo] = {}
    for path in sorted((root / 'crud').glob('*.py')):
        catalog.update(_catalog_crud_file(path, models))
    return catalog


def _catalog_crud_file(path: Path, models: set[str]) -> dict[tuple[str, str], DaoInfo]:
    tree = _parse(path)
    class_model = {
        node.name: model_name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and (model_name := _class_model(node))
    }
    write_by_class = {node.name: _crud_write_methods(node) for node in tree.body if isinstance(node, ast.ClassDef)}
    returns_by_class = {
        node.name: _method_returns(node, models) for node in tree.body if isinstance(node, ast.ClassDef)
    }
    catalog: dict[tuple[str, str], DaoInfo] = {}
    for instance, class_name in _crud_instances(tree):
        model = class_model.get(class_name)
        if model is None or model not in models:
            continue
        catalog[path.stem, instance] = DaoInfo(
            model=model,
            write_methods=frozenset(write_by_class.get(class_name, set())),
            returns=returns_by_class.get(class_name, {}),
        )
    return catalog


def _calls_under(node: ast.AST) -> list[ast.Call]:
    """节点里的调用，包含节点自身；不进入嵌套函数。"""
    found: list[ast.Call] = []

    def walk(current: ast.AST) -> None:
        if isinstance(current, ast.Call):
            found.append(current)
        for child in ast.iter_child_nodes(current):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            walk(child)

    walk(node)
    return found


@dataclass
class _Symbols:
    models: dict[str, str]
    daos: dict[str, DaoInfo]
    dml: dict[str, str]
    returns: dict[str, ValueKind]
    tables_by_model: Mapping[str, str]
    columns: Mapping[str, frozenset[str]]


def _import_symbols(tree: ast.AST, daos: Mapping[tuple[str, str], DaoInfo], models: set[str]) -> _Symbols:
    model_alias: dict[str, str] = {}
    dao_alias: dict[str, DaoInfo] = {}
    dml: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            _take_import(node, models, daos, model_alias, dao_alias, dml)
    return _Symbols(model_alias, dao_alias, dml, {}, {}, {})


def _take_import(
    node: ast.ImportFrom,
    models: set[str],
    daos: Mapping[tuple[str, str], DaoInfo],
    model_alias: dict[str, str],
    dao_alias: dict[str, DaoInfo],
    dml: dict[str, str],
) -> None:
    module = node.module or ''
    if 'rider_salary.model' in module:
        for alias in node.names:
            if alias.name in models:
                model_alias[alias.asname or alias.name] = alias.name
        return
    if 'rider_salary.crud' in module:
        stem = module.rsplit('.', 1)[-1]
        for alias in node.names:
            info = daos.get((stem, alias.name))
            if info is not None:
                dao_alias[alias.asname or alias.name] = info
        return
    if module != 'sqlalchemy':
        return
    for alias in node.names:
        if alias.name in {'update', 'delete'}:
            dml[alias.asname or alias.name] = alias.name


def _local_returns(tree: ast.AST, models: set[str]) -> dict[str, ValueKind]:
    """本模块函数名 → 返回注解。重名则丢弃，避免串型。"""
    found: dict[str, ValueKind] = {}
    ambiguous: set[str] = set()

    def walk(body: list[ast.stmt], prefix: list[str]) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                walk(node.body, [*prefix, node.name])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = _annotation_kind(node.returns, models)
                short = node.name
                if short in found:
                    ambiguous.add(short)
                elif kind.model:
                    found[short] = kind
                walk(node.body, [*prefix, node.name])

    walk(tree.body, [])
    for name in ambiguous:
        found.pop(name, None)
    return found


def _bind_args(node: ast.AST, env: dict[str, ValueKind], models: set[str], guarded: set[str]) -> None:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return
    args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    for arg in args:
        kind = _annotation_kind(arg.annotation, models)
        if kind.model in guarded:
            env[arg.arg] = ValueKind(kind.model, kind.shape, 'persistent')


def _eval_expr(expr: ast.expr, env: Mapping[str, ValueKind], symbols: _Symbols) -> ValueKind:
    if isinstance(expr, ast.Await):
        return _eval_expr(expr.value, env, symbols)
    if isinstance(expr, ast.Name):
        return env.get(expr.id, NONE)
    if isinstance(expr, ast.List):
        return _eval_sequence(expr.elts, env, symbols)
    if isinstance(expr, ast.ListComp):
        inner = _eval_expr(expr.elt, env, symbols)
        if inner.model and inner.shape == 'scalar':
            return ValueKind(inner.model, 'list', inner.origin)
        return NONE
    if isinstance(expr, ast.Call):
        return _eval_call(expr, env, symbols)
    return NONE


def _eval_sequence(elts: list[ast.expr], env: Mapping[str, ValueKind], symbols: _Symbols) -> ValueKind:
    models = []
    origin = 'unknown'
    for elt in elts:
        kind = _eval_expr(elt, env, symbols)
        if kind.model and kind.shape == 'scalar':
            models.append(kind.model)
            origin = kind.origin
    unique = set(models)
    if len(unique) == 1:
        return ValueKind(unique.pop(), 'list', origin)
    return NONE


def _eval_call(expr: ast.Call, env: Mapping[str, ValueKind], symbols: _Symbols) -> ValueKind:
    func = expr.func
    if isinstance(func, ast.Name):
        return _eval_name_call(expr, func.id, env, symbols)
    if isinstance(func, ast.Attribute):
        return _eval_attr_call(expr, func, env, symbols)
    return NONE


def _eval_name_call(expr: ast.Call, name: str, env: Mapping[str, ValueKind], symbols: _Symbols) -> ValueKind:
    if name == 'select':
        return _select_kind(expr, symbols)
    if name == 'list' and expr.args:
        return _as_list(_eval_expr(expr.args[0], env, symbols))
    if name in symbols.models:
        return ValueKind(symbols.models[name], 'scalar', 'constructed')
    returned = symbols.returns.get(name)
    if returned and returned.model:
        return returned
    return NONE


def _as_list(kind: ValueKind) -> ValueKind:
    """``list(查询结果)`` 收成模型列表；已经是列表则原样返回。"""
    if kind.shape == 'list' and kind.model:
        return kind
    if kind.shape == 'result' and kind.model:
        return ValueKind(kind.model, 'list', 'persistent')
    return NONE


def _select_kind(expr: ast.Call, symbols: _Symbols) -> ValueKind:
    if not expr.args or not isinstance(expr.args[0], ast.Name):
        return NONE
    model = symbols.models.get(expr.args[0].id)
    if model is None:
        return NONE
    return ValueKind(model, 'select', 'persistent')


def _eval_attr_call(
    expr: ast.Call,
    func: ast.Attribute,
    env: Mapping[str, ValueKind],
    symbols: _Symbols,
) -> ValueKind:
    receiver = _eval_expr(func.value, env, symbols)
    if func.attr == 'where' and receiver.shape == 'select':
        return receiver
    if func.attr == 'all' and receiver.shape == 'result' and receiver.model:
        return ValueKind(receiver.model, 'list', 'persistent')
    if func.attr in {'scalars', 'scalar'} and expr.args:
        inner = _eval_expr(expr.args[0], env, symbols)
        if inner.shape == 'select' and inner.model:
            shape = 'result' if func.attr == 'scalars' else 'scalar'
            return ValueKind(inner.model, shape, 'persistent')
    owner = _name_of(func.value)
    if owner is not None:
        dao = symbols.daos.get(owner)
        if dao is not None:
            returned = dao.returns.get(func.attr)
            if returned is not None:
                return returned
    return NONE


def _note_call(call: ast.Call, env: Mapping[str, ValueKind], symbols: _Symbols, facts: FuncFacts) -> None:
    func = call.func
    if isinstance(func, ast.Name):
        facts.bare.add(func.id)
        _note_sql_dml(call, func.id, symbols, facts)
        return
    if not isinstance(func, ast.Attribute):
        return
    facts.qualified.add(f'{_receiver_name(func)}.{func.attr}' if _receiver_name(func) else func.attr)
    _note_dao_call(func, symbols, facts)
    _note_session_call(call, func, env, symbols, facts)


def _receiver_name(func: ast.Attribute) -> str:
    if isinstance(func.value, ast.Name):
        return func.value.id
    return ''


def _note_sql_dml(call: ast.Call, name: str, symbols: _Symbols, facts: FuncFacts) -> None:
    dml = symbols.dml.get(name)
    if dml not in {'update', 'delete'} or not call.args or not isinstance(call.args[0], ast.Name):
        return
    model = symbols.models.get(call.args[0].id)
    table = symbols.tables_by_model.get(model or '')
    if table in GUARDED_TABLES:
        facts.tables.add(table or '')
        facts.kinds.add('sql_dml')


def _note_dao_call(func: ast.Attribute, symbols: _Symbols, facts: FuncFacts) -> None:
    owner = _receiver_name(func)
    dao = symbols.daos.get(owner)
    if dao is None or func.attr not in dao.write_methods:
        return
    table = symbols.tables_by_model.get(dao.model)
    if table in GUARDED_TABLES:
        facts.tables.add(table or '')
        facts.kinds.add('dao_write')


def _note_session_call(
    call: ast.Call,
    func: ast.Attribute,
    env: Mapping[str, ValueKind],
    symbols: _Symbols,
    facts: FuncFacts,
) -> None:
    if _receiver_name(func) not in SESSION_NAMES or func.attr not in {'add', 'add_all', 'delete'} or not call.args:
        return
    kind = _eval_expr(call.args[0], env, symbols)
    table = symbols.tables_by_model.get(kind.model or '')
    if table not in GUARDED_TABLES:
        return
    if _is_construct_add(func.attr, kind.shape):
        facts.tables.add(table)
        facts.kinds.add('construct_add')
    elif func.attr == 'delete' and kind.shape == 'scalar':
        facts.tables.add(table)
        facts.kinds.add('session_delete')


def _is_construct_add(attr: str, shape: str) -> bool:
    return (attr == 'add' and shape == 'scalar') or (attr == 'add_all' and shape == 'list')


def _note_attr_store(target: ast.expr, env: Mapping[str, ValueKind], symbols: _Symbols, facts: FuncFacts) -> None:
    if not isinstance(target, ast.Attribute) or not isinstance(target.value, ast.Name):
        return
    kind = env.get(target.value.id, NONE)
    table = symbols.tables_by_model.get(kind.model or '')
    columns = symbols.columns.get(kind.model or '', frozenset())
    if kind.shape != 'scalar' or kind.origin != 'persistent' or table not in GUARDED_TABLES:
        return
    if target.attr not in columns:
        return
    facts.tables.add(table)
    facts.kinds.add('attr_flush')


def _bind_target(target: ast.expr, kind: ValueKind, env: dict[str, ValueKind]) -> None:
    if isinstance(target, ast.Name) and kind.model:
        env[target.id] = kind
    elif isinstance(target, ast.Name) and target.id in env and kind.shape == 'none':
        return


def _element_kind(kind: ValueKind) -> ValueKind:
    if kind.shape == 'list' and kind.model:
        return ValueKind(kind.model, 'scalar', kind.origin)
    return NONE


def _analyze_function(node: ast.AST, facts: FuncFacts, symbols: _Symbols, models: set[str], guarded: set[str]) -> None:
    env: dict[str, ValueKind] = {}
    _bind_args(node, env, models, guarded)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        _analyze_body(node.body, env, symbols, facts)


def _analyze_body(body: list[ast.stmt], env: dict[str, ValueKind], symbols: _Symbols, facts: FuncFacts) -> None:
    for stmt in body:
        _analyze_stmt(stmt, env, symbols, facts)


def _analyze_compound(stmt: ast.stmt, env: dict[str, ValueKind], symbols: _Symbols, facts: FuncFacts) -> bool:
    """处理带语句体的节点。返回是否已处理。"""
    if isinstance(stmt, ast.If):
        _note_expr(stmt.test, env, symbols, facts)
        _analyze_body(stmt.body, env, symbols, facts)
        _analyze_body(stmt.orelse, env, symbols, facts)
        return True
    if isinstance(stmt, (ast.For, ast.AsyncFor)):
        _note_expr(stmt.iter, env, symbols, facts)
        _bind_target(stmt.target, _element_kind(_eval_expr(stmt.iter, env, symbols)), env)
        _analyze_body(stmt.body, env, symbols, facts)
        _analyze_body(stmt.orelse, env, symbols, facts)
        return True
    if isinstance(stmt, (ast.While, ast.AsyncWith, ast.With)):
        _analyze_body(stmt.body, env, symbols, facts)
        _analyze_body(getattr(stmt, 'orelse', []), env, symbols, facts)
        return True
    if isinstance(stmt, ast.Try):
        _analyze_try(stmt, env, symbols, facts)
        return True
    return False


def _analyze_stmt(stmt: ast.stmt, env: dict[str, ValueKind], symbols: _Symbols, facts: FuncFacts) -> None:
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return
    if _analyze_compound(stmt, env, symbols, facts):
        return
    if isinstance(stmt, ast.Assign):
        _assign(stmt, env, symbols, facts)
        return
    if isinstance(stmt, ast.AnnAssign):
        _ann_assign(stmt, env, symbols, facts)
        return
    if isinstance(stmt, ast.AugAssign):
        _note_expr(stmt.value, env, symbols, facts)
        _note_attr_store(stmt.target, env, symbols, facts)
        return
    if isinstance(stmt, (ast.Expr, ast.Return)):
        value = stmt.value
        if value is not None:
            _note_expr(value, env, symbols, facts)


def _analyze_try(stmt: ast.Try, env: dict[str, ValueKind], symbols: _Symbols, facts: FuncFacts) -> None:
    _analyze_body(stmt.body, env, symbols, facts)
    for handler in stmt.handlers:
        _analyze_body(handler.body, env, symbols, facts)
    _analyze_body(stmt.orelse, env, symbols, facts)
    _analyze_body(stmt.finalbody, env, symbols, facts)


def _assign(stmt: ast.Assign, env: dict[str, ValueKind], symbols: _Symbols, facts: FuncFacts) -> None:
    _note_expr(stmt.value, env, symbols, facts)
    kind = _eval_expr(stmt.value, env, symbols)
    for target in stmt.targets:
        _note_attr_store(target, env, symbols, facts)
        _bind_target(target, kind, env)


def _ann_assign(stmt: ast.AnnAssign, env: dict[str, ValueKind], symbols: _Symbols, facts: FuncFacts) -> None:
    if stmt.value is not None:
        _note_expr(stmt.value, env, symbols, facts)
    annotated = _annotation_kind(stmt.annotation, set(symbols.models.values()))
    evaluated = _eval_expr(stmt.value, env, symbols) if stmt.value is not None else NONE
    kind = evaluated if evaluated.model else annotated
    _note_attr_store(stmt.target, env, symbols, facts)
    _bind_target(stmt.target, kind, env)


def _note_expr(expr: ast.expr, env: Mapping[str, ValueKind], symbols: _Symbols, facts: FuncFacts) -> None:
    for call in _calls_under(expr):
        _note_call(call, env, symbols, facts)


def _iter_functions(tree: ast.AST) -> Iterable[tuple[str, ast.AST]]:
    def walk(body: list[ast.stmt], prefix: list[str]) -> Iterable[tuple[str, ast.AST]]:
        for node in body:
            if isinstance(node, ast.ClassDef):
                yield from walk(node.body, [*prefix, node.name])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield '.'.join([*prefix, node.name]), node
                yield from walk(node.body, [*prefix, node.name])

    yield from walk(tree.body, [])


def _scan_service(
    root: Path,
    daos: Mapping[tuple[str, str], DaoInfo],
    tables_by_model: Mapping[str, str],
    columns: Mapping[str, frozenset[str]],
) -> dict[tuple[str, str], FuncFacts]:
    models = set(tables_by_model)
    guarded = {name for name, table in tables_by_model.items() if table in GUARDED_TABLES}
    functions: dict[tuple[str, str], FuncFacts] = {}
    for path in sorted((root / 'service').glob('*.py')):
        tree = _parse(path)
        relative = f'service/{path.name}'
        symbols = _import_symbols(tree, daos, models)
        symbols.returns = _local_returns(tree, models)
        symbols.tables_by_model = tables_by_model
        symbols.columns = columns
        for qualname, node in _iter_functions(tree):
            facts = FuncFacts(relative, qualname, getattr(node, 'lineno', 0))
            _analyze_function(node, facts, symbols, models, guarded)
            functions[relative, qualname] = facts
    return functions


def _lookup(functions: Mapping[tuple[str, str], FuncFacts], path: str, name: str) -> FuncFacts | None:
    same = [facts for (fact_path, qual), facts in functions.items() if fact_path == path and _matches(qual, name)]
    if len(same) == 1:
        return same[0]
    any_file = [facts for (_fact_path, qual), facts in functions.items() if _matches(qual, name)]
    if len(any_file) == 1:
        return any_file[0]
    return None


def _matches(qualname: str, name: str) -> bool:
    return qualname == name or qualname.endswith(f'.{name}')


def _reaches(
    facts: FuncFacts,
    kind: str,
    functions: Mapping[tuple[str, str], FuncFacts],
    seen: set[tuple[str, str]],
) -> bool:
    key = (facts.path, facts.qualname)
    if key in seen:
        return False
    seen.add(key)
    if kind == 'audit':
        return 'audit_service.record' in facts.qualified
    roots = LOCK_ROOTS if kind == 'lock' else STALE_ROOTS
    wrappers = LOCK_WRAPPERS if kind == 'lock' else STALE_WRAPPERS
    if facts.bare & roots:
        return True
    if any(item.split('.')[-1] in roots for item in facts.qualified):
        return True
    for name in facts.bare & wrappers:
        target = _lookup(functions, facts.path, name)
        if target is not None and _reaches(target, kind, functions, seen):
            return True
    return False


def _site_has(
    facts: FuncFacts,
    kind: str,
    functions: Mapping[tuple[str, str], FuncFacts],
) -> bool:
    chain = CHAIN_BY_KEY.get((facts.path, facts.qualname))
    starts = [facts]
    if chain is not None:
        for hop in chain.hops:
            target = _lookup(functions, facts.path, hop)
            if target is not None:
                starts.append(target)
    return any(_reaches(item, kind, functions, set()) for item in starts)


def _callers_of(functions: Mapping[tuple[str, str], FuncFacts], method: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for key, facts in functions.items():
        if facts.qualname == method or facts.qualname.endswith(f'.{method}'):
            continue
        if any(item.endswith(f'.{method}') for item in facts.qualified):
            found.add(key)
    return found


def scan_plugin(root: Path) -> ScanResult:
    """扫描插件根目录下的 service / crud / model。"""
    tables_by_model, columns = _load_models(root)
    guarded_models = {name for name, table in tables_by_model.items() if table in GUARDED_TABLES}
    daos = _load_daos(root, guarded_models)
    functions = _scan_service(root, daos, tables_by_model, columns)
    sites: list[WriteSite] = []
    for facts in functions.values():
        if not facts.kinds:
            continue
        sites.append(
            WriteSite(
                path=facts.path,
                qualname=facts.qualname,
                line=facts.line,
                tables=frozenset(facts.tables),
                kinds=frozenset(facts.kinds),
                lock=_site_has(facts, 'lock', functions),
                stale=_site_has(facts, 'stale', functions),
                audit=_site_has(facts, 'audit', functions),
            )
        )
    sites.sort(key=lambda item: (item.path, item.qualname))
    return ScanResult(tuple(sites), functions, tables_by_model)


def _guard_on(site: WriteSite, guard: str) -> bool:
    if guard == 'lock':
        return site.lock
    if guard == 'stale':
        return site.stale
    return site.audit


def collect_issues(result: ScanResult) -> list[str]:
    """返回三件套缺口、失效白名单和断开的调用链。空列表表示通过。"""
    issues: list[str] = []
    by_key = {(site.path, site.qualname): site for site in result.sites}
    for site in result.sites:
        issues.extend(_site_issues(site))
    for key, waiver in WAIVER_BY_KEY.items():
        if key not in by_key:
            issues.append(f'白名单 {key[0]}:{key[1]} 没有对应的写入函数')
        if not waiver.reason.strip():
            issues.append(f'白名单 {key[0]}:{key[1]} 没有写原因')
        issues.extend(_caller_issues(waiver, result))
    issues.extend(_chain_issues(result))
    issues.extend(_wrapper_issues(result))
    return issues


def _site_issues(site: WriteSite) -> list[str]:
    waiver = WAIVER_BY_KEY.get((site.path, site.qualname))
    issues: list[str] = []
    missing = [GUARD_LABELS[name] for name in ('lock', 'stale', 'audit') if _missing(site, name, waiver)]
    if missing:
        issues.append(
            f'{site.path}:{site.line} {site.qualname} 缺少{"、".join(missing)}'
            f'；表 {", ".join(sorted(site.tables))}；写入 {", ".join(sorted(site.kinds))}'
        )
    if waiver is None:
        return issues
    covered = [GUARD_LABELS[name] for name in sorted(waiver.skip) if _guard_on(site, name)]
    if covered:
        issues.append(f'{site.path}:{site.qualname} 已有{"、".join(covered)}，请从白名单去掉对应豁免')
    return issues


def _missing(site: WriteSite, guard: str, waiver: Waiver | None) -> bool:
    if _guard_on(site, guard):
        return False
    return waiver is None or guard not in waiver.skip


def _caller_issues(waiver: Waiver, result: ScanResult) -> list[str]:
    if not waiver.audit_callers:
        return []
    actual = _callers_of(result.functions, waiver.qualname.split('.')[-1])
    expected = set(waiver.audit_callers)
    issues: list[str] = []
    if actual != expected:
        issues.append(f'{waiver.qualname} 的审计调用方是 {sorted(actual)}，白名单写的是 {sorted(expected)}')
    for key in waiver.audit_callers:
        facts = result.functions.get(key)
        if facts is None or 'audit_service.record' not in facts.qualified:
            issues.append(f'{waiver.qualname} 的调用方 {key[1]} 没有 audit_service.record')
    return issues


def _chain_issues(result: ScanResult) -> list[str]:
    issues: list[str] = []
    for chain in CALL_CHAINS:
        if not chain.reason.strip():
            issues.append(f'调用链 {chain.qualname} 没有写原因')
        current = result.functions.get((chain.path, chain.qualname))
        if current is None:
            issues.append(f'调用链起点 {chain.qualname} 不存在')
            continue
        for hop in chain.hops:
            if hop not in current.bare and not any(item.endswith(f'.{hop}') for item in current.qualified):
                issues.append(f'{current.qualname} 没有调用调用链上的 {hop}')
                break
            nxt = _lookup(result.functions, chain.path, hop)
            if nxt is None:
                issues.append(f'调用链 {hop} 找不到函数')
                break
            current = nxt
        else:
            if not _reaches(current, 'lock', result.functions, set()):
                issues.append(f'调用链 {chain.qualname} 的末端没有到达锁账根')
    return issues


def _wrapper_issues(result: ScanResult) -> list[str]:
    issues: list[str] = []
    for name, kind in [(item, 'lock') for item in sorted(LOCK_WRAPPERS)] + [
        (item, 'stale') for item in sorted(STALE_WRAPPERS)
    ]:
        facts = _lookup(result.functions, '', name)
        if facts is None:
            issues.append(f'封装 {name} 不存在')
        elif not _reaches(facts, kind, result.functions, set()):
            issues.append(f'封装 {name} 没有调用到{"锁账" if kind == "lock" else "重算"}根')
    return issues


def _stage(tmp: Path) -> Path:
    """把 model / crud / service 复制到临时目录，变异只发生在副本上。"""
    root = tmp / 'plugin'
    for name in ('model', 'crud', 'service'):
        shutil.copytree(PLUGIN_ROOT / name, root / name)
    return root


class _Stripper(ast.NodeTransformer):
    """删掉指定函数里对某个名字的直接调用（含 await）。"""

    def __init__(self, qualname: str, call_name: str) -> None:
        self.qualname = qualname
        self.call_name = call_name
        self.stack: list[str] = []
        self.removed = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        self.stack.append(node.name)
        node = self.generic_visit(node)
        self.stack.pop()
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._visit_func(node)

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST:
        self.stack.append(node.name)
        node = self.generic_visit(node)
        self.stack.pop()
        return node

    def visit_Expr(self, node: ast.Expr) -> ast.AST | None:
        if self._hit(node.value):
            return None
        return self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> ast.AST | None:
        if self._hit(node.value):
            return None
        return self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST | None:
        if node.value is not None and self._hit(node.value):
            return None
        return self.generic_visit(node)

    def generic_visit(self, node: ast.AST) -> ast.AST:
        node = super().generic_visit(node)
        body = getattr(node, 'body', None)
        if isinstance(body, list) and not body and not isinstance(node, ast.Module):
            node.body = [ast.Pass()]
        return node

    def _hit(self, expr: ast.expr) -> bool:
        if '.'.join(self.stack) != self.qualname:
            return False
        current = expr.value if isinstance(expr, ast.Await) else expr
        if not isinstance(current, ast.Call) or not isinstance(current.func, ast.Name):
            return False
        if current.func.id != self.call_name:
            return False
        self.removed += 1
        return True


def strip_named_calls(source: str, qualname: str, call_name: str) -> str:
    """从源码里去掉某函数对 ``call_name`` 的直接调用，返回仍可解析的源码。"""
    tree = ast.parse(source)
    stripper = _Stripper(qualname, call_name)
    updated = stripper.visit(tree)
    if stripper.removed == 0:
        raise AssertionError(f'{qualname} 里没有 {call_name}')
    ast.fix_missing_locations(updated)
    rendered = ast.unparse(updated)
    ast.parse(rendered)
    return rendered


def _issues_mention(issues: list[str], qualname: str, label: str) -> bool:
    return any(qualname in item and label in item for item in issues)


def test_write_paths_keep_trio() -> None:
    """现网写入要么三件套齐全，要么落在带原因的白名单里。"""
    result = scan_plugin(PLUGIN_ROOT)
    issues = collect_issues(result)
    rendered = '\n'.join(
        f'{site.path}:{site.line} {site.qualname} {sorted(site.kinds)} {sorted(site.tables)}' for site in result.sites
    )
    assert not issues, '\n'.join(issues) + '\n\n识别到的写入：\n' + rendered


def test_each_write_kind_is_detected() -> None:
    """四类写入路径在现网都至少有一处，避免扫描器漏掉整类。"""
    result = scan_plugin(PLUGIN_ROOT)
    found = {
        (site.path, site.qualname, kind, table) for site in result.sites for kind in site.kinds for table in site.tables
    }
    missing = [item for item in EXPECTED_SITES if item not in found]
    assert not missing, missing


def test_no_pending_write_path_waivers() -> None:
    """白名单里不再保留「待修」。缺件必须先补上，或写成有原因的长期豁免。"""
    pending = [item.qualname for item in WAIVERS if '待修' in item.reason]
    assert not pending


@pytest.mark.parametrize(
    ('path', 'qualname', 'call_name', 'label'),
    [
        ('service/order_service.py', 'OrderService.create', 'assert_not_locked', '锁账校验'),
        ('service/order_service.py', 'OrderService.create', 'mark_stale', '重算标记'),
        ('service/adjustment_service.py', 'AdjustmentService.create', 'assert_not_locked', '锁账校验'),
        ('service/adjustment_service.py', 'AdjustmentService.create', 'mark_stale', '重算标记'),
        ('service/order_service.py', 'OrderService.update', 'assert_not_locked', '锁账校验'),
        ('service/order_service.py', 'OrderService.update', 'mark_stale', '重算标记'),
    ],
)
def test_stripping_guard_fails(tmp_path: Path, path: str, qualname: str, call_name: str, label: str) -> None:
    """四类真实写入各去掉锁账或重算后，守护测试必须失败。副本在 tmp，不改业务代码。"""
    root = _stage(tmp_path)
    file_path = root / path
    file_path.write_text(
        strip_named_calls(file_path.read_text(encoding='utf-8'), qualname, call_name), encoding='utf-8'
    )
    issues = collect_issues(scan_plugin(root))
    assert _issues_mention(issues, qualname, label), issues


@pytest.mark.parametrize('call_name', ['assert_not_locked', 'mark_stale'])
def test_stripping_sql_dml_guard_fails(tmp_path: Path, call_name: str) -> None:
    """现网的 update() 写在锁账回写里且被豁免。合成一条 update/delete，去掉守卫后必须失败。"""
    root = _stage(tmp_path)
    probe = root / 'service' / '_sql_dml_probe.py'
    probe.write_text(SQL_PROBE, encoding='utf-8')
    assert not collect_issues(scan_plugin(root))
    label = '锁账校验' if call_name == 'assert_not_locked' else '重算标记'
    probe.write_text(strip_named_calls(SQL_PROBE, 'rewrite_locked_rows', call_name), encoding='utf-8')
    issues = collect_issues(scan_plugin(root))
    assert _issues_mention(issues, 'rewrite_locked_rows', label), issues


def test_import_lock_chain_is_required(tmp_path: Path) -> None:
    """导入的锁账在 _is_locked 里。去掉 assert_not_locked 后 import_orders 必须失败。"""
    root = _stage(tmp_path)
    file_path = root / 'service' / 'import_service.py'
    file_path.write_text(
        strip_named_calls(file_path.read_text(encoding='utf-8'), '_is_locked', 'assert_not_locked'),
        encoding='utf-8',
    )
    issues = collect_issues(scan_plugin(root))
    assert _issues_mention(issues, 'ImportService.import_orders', '锁账校验'), issues


def test_stale_wrapper_body_is_required(tmp_path: Path) -> None:
    """_mark_employ_stale 只有在体内调用 mark_stale 时才算数。"""
    root = _stage(tmp_path)
    file_path = root / 'service' / 'rider_service.py'
    file_path.write_text(
        strip_named_calls(file_path.read_text(encoding='utf-8'), '_mark_employ_stale', 'mark_stale'),
        encoding='utf-8',
    )
    issues = collect_issues(scan_plugin(root))
    assert _issues_mention(issues, 'RiderService.leave', '重算标记'), issues


def test_day_flag_lock_equivalent_is_required(tmp_path: Path) -> None:
    """日标记用 site_locked_dates，不是 assert_not_locked。去掉后 upsert 必须失败。"""
    root = _stage(tmp_path)
    file_path = root / 'service' / 'day_flag_service.py'
    file_path.write_text(
        strip_named_calls(file_path.read_text(encoding='utf-8'), 'DayFlagService.upsert', 'site_locked_dates'),
        encoding='utf-8',
    )
    issues = collect_issues(scan_plugin(root))
    assert _issues_mention(issues, 'DayFlagService.upsert', '锁账校验'), issues
