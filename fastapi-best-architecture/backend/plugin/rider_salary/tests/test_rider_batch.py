"""P6-17 批量绑定、批量开户、批量重置密码。

人数用内存替身，不往库里造 100 名骑手。成功路径上 N 条绑定必须产生 N 条审计，
并且每条都先做过锁账查询、再标重算。任一失败抛出后由接口事务整单回滚。
开户和重置不接收统一密码，每人拿到独立随机口令，并要求首次登录改密。
"""

from datetime import date
from types import SimpleNamespace
from typing import Any, Self
from unittest.mock import AsyncMock, patch

import anyio
import pytest

from pydantic import ValidationError

from backend.common.exception import errors
from backend.plugin.rider_salary.enums import BindingType
from backend.plugin.rider_salary.schema.rider import (
    BatchOpenAccountParam,
    BatchPlanBindingParam,
    BatchResetPasswordParam,
    CreatePlanBindingParam,
)
from backend.plugin.rider_salary.service.rider_service import RiderService, rider_service

_START = date(2026, 10, 1)
_LOCK_SNIPPET = '该日期所属结算周期已锁账'
_FIXED_PASSWORDS = {'123456', 'Rider@123456', 'rider123456'}


def _run(case: Any) -> None:
    anyio.run(case)


def _request() -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(id=1, username='admin', dept_id=2, is_superuser=True))


def _rider(pk: int, *, user_id: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=pk,
        job_no=f'D{pk:04d}',
        name=f'骑手{pk}',
        phone=None,
        site_id=3,
        status='on_job',
        user_id=user_id,
    )


def _binding_param() -> BatchPlanBindingParam:
    return BatchPlanBindingParam(
        rider_ids=[1],
        plan_version_id=11,
        binding_type=BindingType.default,
        start_date=_START,
        end_date=None,
    )


def test_batch_schema_rejects_empty_duplicate_and_shared_password() -> None:
    """空列表、重复骑手、统一密码都在入参层拒绝。"""
    with pytest.raises(ValidationError, match='请至少选择 1 名骑手'):
        BatchPlanBindingParam(
            rider_ids=[],
            plan_version_id=11,
            binding_type=BindingType.default,
            start_date=_START,
        )
    with pytest.raises(ValidationError, match='骑手不能重复'):
        BatchPlanBindingParam(
            rider_ids=[1, 1],
            plan_version_id=11,
            binding_type=BindingType.default,
            start_date=_START,
        )
    with pytest.raises(ValidationError, match='不接受统一密码'):
        BatchOpenAccountParam.model_validate({'rider_ids': [1, 2], 'reason': '批量开户', 'password': 'Rider@123456'})
    with pytest.raises(ValidationError, match='不接受统一密码'):
        BatchResetPasswordParam.model_validate({'rider_ids': [1], 'password': '123456'})
    BatchOpenAccountParam.model_validate({'rider_ids': [1], 'reason': '批量开户', 'password': None})
    assert 'password' not in BatchOpenAccountParam.model_fields
    assert 'password' not in BatchResetPasswordParam.model_fields


def test_batch_bind_writes_one_audit_lock_and_stale_per_rider() -> None:
    """100 名骑手一次绑定，每人一条审计、一次锁账查询、一次重算标记。"""
    count = 100
    riders = {pk: _rider(pk) for pk in range(1, count + 1)}
    obj = BatchPlanBindingParam(
        rider_ids=list(riders),
        plan_version_id=11,
        binding_type=BindingType.default,
        start_date=_START,
    )

    async def _case() -> None:
        with _binding_service(riders) as env:
            result = await rider_service.create_bindings_batch(db=env.db, request=_request(), obj=obj)
            assert result.count == count
            assert [item.rider_id for item in result.items] == list(riders)
            assert len({item.binding_id for item in result.items}) == count
            assert env.audit.await_count == count
            assert env.mark_stale.await_count == count
            assert env.db.scalar.await_count == count
            assert env.binding_create.await_count == count
            stale_ids = [call.kwargs['rider_ids'] for call in env.mark_stale.await_args_list]
            assert stale_ids == [[pk] for pk in riders]
            for call in env.audit.await_args_list:
                assert call.kwargs['module'] == '骑手管理'
                assert call.kwargs['action'] == '新增方案绑定'
                assert call.kwargs['target_type'] == 'rider_plan_binding'
            audit_ids = [call.kwargs['target_id'] for call in env.audit.await_args_list]
            assert audit_ids == [item.binding_id for item in result.items]

    _run(_case)


def test_batch_bind_collects_locked_rider_and_does_not_skip_checks() -> None:
    """锁账的骑手进错误清单，其他人仍逐条走过三件套；接口以失败结束，事务回滚。"""
    riders = {pk: _rider(pk) for pk in (1, 2, 3)}
    obj = _binding_param().model_copy(update={'rider_ids': [1, 2, 3]})

    async def _case() -> None:
        with _binding_service(riders, locked_ids={2}) as env:
            with pytest.raises(errors.RequestError, match=_LOCK_SNIPPET) as caught:
                await rider_service.create_bindings_batch(db=env.db, request=_request(), obj=obj)
            assert 'D0002' in (caught.value.msg or '')
            reasons = caught.value.data['errors']
            assert len(reasons) == 1
            assert reasons[0]['rider_id'] == 2
            created = [call.args[1] for call in env.binding_create.await_args_list]
            assert created == [1, 3]
            assert env.audit.await_count == 2
            assert env.mark_stale.await_count == 2
            assert env.db.scalar.await_count == 3

    _run(_case)


def test_batch_open_issues_unique_passwords_and_requires_change() -> None:
    """批量开户不走固定口令：每人随机密码不同，审计和首次改密标记各一条。"""
    riders = {pk: _rider(pk) for pk in (1, 2, 3)}
    obj = BatchOpenAccountParam(rider_ids=[1, 2, 3], reason='批量开户')

    async def _case() -> None:
        with _account_service(riders) as env:
            result = await rider_service.open_accounts_batch(db=env.db, request=_request(), obj=obj)
            passwords = [item.initial_password for item in result.items]
            assert len(passwords) == 3
            assert len(set(passwords)) == 3
            assert _FIXED_PASSWORDS.isdisjoint(passwords)
            assert [call.kwargs['obj'].password for call in env.create_user.await_args_list] == passwords
            assert env.audit.await_count == 3
            for call in env.audit.await_args_list:
                assert call.kwargs['action'] == '开通骑手账号'
                assert call.kwargs['reason'] == '批量开户'
                assert call.kwargs['after']['must_change_password'] is True
            assert env.rider_update.await_count == 3
            for call in env.rider_update.await_args_list:
                assert call.kwargs['must_change_password'] is True
                assert call.kwargs['user_id']

    _run(_case)


def test_batch_open_reports_existing_account_without_skipping_others() -> None:
    """已开户的骑手记入错误，不会静默跳过；整单仍失败回滚。"""
    riders = {1: _rider(1), 2: _rider(2, user_id=20)}
    obj = BatchOpenAccountParam(rider_ids=[1, 2], reason='批量开户')

    async def _case() -> None:
        with _account_service(riders) as env:
            with pytest.raises(errors.RequestError, match='该骑手已开通账号') as caught:
                await rider_service.open_accounts_batch(db=env.db, request=_request(), obj=obj)
            assert caught.value.data['errors'][0]['rider_id'] == 2
            assert env.create_user.await_count == 1
            assert env.audit.await_count == 1

    _run(_case)


def test_batch_reset_issues_unique_passwords_and_requires_change() -> None:
    """批量重置同样每人一条随机密码，并重新要求首次改密。"""
    riders = {pk: _rider(pk, user_id=100 + pk) for pk in (1, 2)}
    obj = BatchResetPasswordParam(rider_ids=[1, 2], reason='批量重置')

    async def _case() -> None:
        with _account_service(riders) as env:
            result = await rider_service.reset_passwords_batch(db=env.db, request=_request(), obj=obj)
            passwords = [item.initial_password for item in result.items]
            assert len(set(passwords)) == 2
            assert _FIXED_PASSWORDS.isdisjoint(passwords)
            assert [call.kwargs['password'] for call in env.reset_password.await_args_list] == passwords
            assert env.audit.await_count == 2
            for call in env.audit.await_args_list:
                assert call.kwargs['action'] == '重置骑手密码'
                assert call.kwargs['after']['must_change_password'] is True
            for call in env.rider_update.await_args_list:
                assert call.kwargs['must_change_password'] is True

    _run(_case)


class _BindingEnv:
    def __init__(self, riders: dict[int, SimpleNamespace], *, locked_ids: set[int] | None = None) -> None:
        self.riders = riders
        self.locked_ids = locked_ids or set()
        self.seq = 1
        self.db = AsyncMock()
        self.audit = AsyncMock()
        self.mark_stale = AsyncMock()
        self.binding_create = AsyncMock(side_effect=self._create)
        self.db.scalar = AsyncMock(side_effect=self._scalar)
        prefix = 'backend.plugin.rider_salary.service.rider_service.'
        version = SimpleNamespace(is_used=True, status='active', deleted=0, plan_id=1)

        def visible(*, db: object, request: object, pk: int) -> SimpleNamespace:
            _ = (db, request)
            rider = self.riders.get(pk)
            if rider is None:
                raise errors.NotFoundError(msg='骑手不存在')
            return rider

        self._patches = [
            patch.object(RiderService, '_get_visible_rider', AsyncMock(side_effect=visible)),
            patch.object(RiderService, '_assert_plan_version_active', AsyncMock(return_value=version)),
            patch(f'{prefix}rider_plan_binding_dao.get_by_rider', AsyncMock(return_value=[])),
            patch(f'{prefix}rider_plan_binding_dao.create', self.binding_create),
            patch(f'{prefix}mark_stale', self.mark_stale),
            patch(f'{prefix}audit_service.record', self.audit),
        ]

    def _scalar(self, stmt: object) -> int | None:
        from sqlalchemy.dialects import postgresql

        sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
        for pk in self.locked_ids:
            if f'IN ({pk}, 0)' in sql:
                return 11
        return None

    def _create(self, _db: object, rider_id: int, obj: CreatePlanBindingParam) -> SimpleNamespace:
        row = SimpleNamespace(
            id=self.seq,
            rider_id=rider_id,
            plan_version_id=obj.plan_version_id,
            binding_type=getattr(obj.binding_type, 'value', obj.binding_type),
            start_date=obj.start_date,
            end_date=obj.end_date,
            remark=obj.remark,
        )
        self.seq += 1
        return row

    def __enter__(self) -> Self:
        for item in self._patches:
            item.start()
        return self

    def __exit__(self, *exc: object) -> None:
        for item in reversed(self._patches):
            item.stop()


def _binding_service(riders: dict[int, SimpleNamespace], *, locked_ids: set[int] | None = None) -> _BindingEnv:
    return _BindingEnv(riders, locked_ids=locked_ids)


class _AccountEnv:
    def __init__(self, riders: dict[int, SimpleNamespace]) -> None:
        self.riders = riders
        self.users: dict[str, SimpleNamespace] = {}
        self.next_user_id = 500
        self.db = AsyncMock()
        self.audit = AsyncMock()
        self.create_user = AsyncMock(side_effect=self._create_user)
        self.reset_password = AsyncMock(return_value=1)
        self.rider_update = AsyncMock(return_value=1)
        prefix = 'backend.plugin.rider_salary.service.rider_service.'

        def visible(*, db: object, request: object, pk: int) -> SimpleNamespace:
            _ = (db, request)
            rider = self.riders.get(pk)
            if rider is None:
                raise errors.NotFoundError(msg='骑手不存在')
            return rider

        def get_by_username(_db: object, username: str) -> SimpleNamespace | None:
            return self.users.get(username)

        self._patches = [
            patch.object(RiderService, '_get_visible_rider', AsyncMock(side_effect=visible)),
            patch(f'{prefix}user_dao.get_by_username', AsyncMock(side_effect=get_by_username)),
            patch(f'{prefix}user_dao.set_staff', AsyncMock()),
            patch(f'{prefix}user_dao.set_super', AsyncMock()),
            patch(f'{prefix}rider_dao.update', self.rider_update),
            patch(f'{prefix}site_dao.get', AsyncMock(return_value=SimpleNamespace(id=3, dept_id=8))),
            patch(f'{prefix}find_rider_role', AsyncMock(return_value=SimpleNamespace(id=9))),
            patch(f'{prefix}_reject_if_user_bound', AsyncMock()),
            patch(f'{prefix}sys_user_service.create', self.create_user),
            patch(f'{prefix}sys_user_service.reset_password', self.reset_password),
            patch(f'{prefix}audit_service.record', self.audit),
        ]

    def _create_user(self, *, db: object, obj: Any) -> None:
        _ = db
        self.users[obj.username] = SimpleNamespace(id=self.next_user_id, username=obj.username)
        self.next_user_id += 1

    def __enter__(self) -> Self:
        for item in self._patches:
            item.start()
        return self

    def __exit__(self, *exc: object) -> None:
        for item in reversed(self._patches):
            item.stop()


def _account_service(riders: dict[int, SimpleNamespace]) -> _AccountEnv:
    return _AccountEnv(riders)
