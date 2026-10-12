"""集成测试运行时：独立库、事务回滚、Redis 前缀和 httpx 客户端。"""

import asyncio
import os
import re
import subprocess
import uuid

from dataclasses import dataclass
from pathlib import Path

import httpx
import psycopg
import redis

from psycopg import sql
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_BACKEND_ROOT = Path(__file__).resolve().parents[4]
_DB_NAME_RE = re.compile(r'^fba_it_\d+_[0-9a-f]{8}$')
_PASSWORD = '123456'
_REDIS_FIELDS = (
    'JWT_USER_REDIS_PREFIX',
    'TOKEN_REDIS_PREFIX',
    'TOKEN_EXTRA_INFO_REDIS_PREFIX',
    'TOKEN_ONLINE_REDIS_PREFIX',
    'TOKEN_REFRESH_REDIS_PREFIX',
    'LOGIN_CAPTCHA_REDIS_PREFIX',
    'LOGIN_FAILURE_PREFIX',
    'USER_LOCK_REDIS_PREFIX',
    'REQUEST_LIMITER_REDIS_PREFIX',
    'CACHE_CONFIG_REDIS_PREFIX',
    'CACHE_DICT_REDIS_PREFIX',
    'CACHE_PUBSUB_CHANNEL',
    'SNOWFLAKE_REDIS_PREFIX',
)
_SQL_FILES = (
    'sql/postgresql/init_test_data.sql',
    'plugin/config/sql/postgresql/init.sql',
    'plugin/oauth2/sql/postgresql/init.sql',
    'plugin/notice/sql/postgresql/init.sql',
    'plugin/code_generator/sql/postgresql/init.sql',
    'plugin/dict/sql/postgresql/init.sql',
    'plugin/rider_salary/sql/postgresql/init.sql',
)
_ROLE_ROWS = (
    ('salary_admin', 92001, True, '薪资管理员'),
    ('site_owner', 92002, True, '站点负责人'),
    ('site_deputy', 92003, True, '站点副负责人'),
    ('rider', 92004, False, '骑手'),
)
_SEQUENCE_TABLES = ('sys_user', 'sys_user_role', 'rs_site', 'rs_rider', 'rs_site_manager')


@dataclass
class RoleAccount:
    """一种预置角色的登录结果。"""

    key: str
    username: str
    user_id: int
    headers: dict[str, str]


@dataclass
class PreparedDatabase:
    """已灌入种子的测试库。"""

    name: str
    accounts: dict[str, tuple[str, int]]
    seed_site_id: int
    seed_rider_id: int


class ApiClient:
    """在基座事件循环上调用 ``httpx.AsyncClient`` 的同步包装。"""

    def __init__(self, loop: asyncio.AbstractEventLoop, raw: httpx.AsyncClient) -> None:
        """包装已进入上下文的异步客户端。

        :param loop: 基座事件循环
        :param raw: httpx 异步客户端
        """
        self.loop = loop
        self.raw = raw

    def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        """发送请求。

        :param method: HTTP 方法
        :param url: 相对 ``/api/v1`` 的路径
        :param kwargs: 传给 ``httpx.AsyncClient.request`` 的参数
        :return: 响应
        """
        return self.loop.run_until_complete(self.raw.request(method, url, **kwargs))

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        """GET。

        :param url: 路径
        :param kwargs: 请求参数
        :return: 响应
        """
        return self.request('GET', url, **kwargs)

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        """POST。

        :param url: 路径
        :param kwargs: 请求参数
        :return: 响应
        """
        return self.request('POST', url, **kwargs)

    def put(self, url: str, **kwargs: object) -> httpx.Response:
        """PUT。

        :param url: 路径
        :param kwargs: 请求参数
        :return: 响应
        """
        return self.request('PUT', url, **kwargs)

    def delete(self, url: str, **kwargs: object) -> httpx.Response:
        """DELETE。

        :param url: 路径
        :param kwargs: 请求参数
        :return: 响应
        """
        return self.request('DELETE', url, **kwargs)


def probe_infra() -> str | None:
    """探测 PostgreSQL 与 Redis。不可达时返回原因，不导入应用。

    :return: 失败原因；两者都可达时返回 None
    """
    try:
        from backend.core.conf import settings
    except Exception as exc:
        return f'无法读取配置：{_safe_error(exc)}'
    try:
        with _maintenance_connection(settings) as conn:
            conn.execute('SELECT 1')
    except Exception as exc:
        return f'PostgreSQL 不可达：{_safe_error(exc)}'
    try:
        client = _sync_redis(settings)
        try:
            if not client.ping():
                return 'Redis 未响应'
        finally:
            client.close()
    except Exception as exc:
        return f'Redis 不可达：{_safe_error(exc)}'
    return None


def prepare_database() -> PreparedDatabase:
    """创建独立测试库并灌入框架种子、插件种子和四种角色账号。

    :return: 库名与种子账号
    """
    from backend.core.conf import settings

    name = f'fba_it_{os.getpid()}_{uuid.uuid4().hex[:8]}'
    _assert_test_db(name)
    with _maintenance_connection(settings) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        _create_schema(settings, name)
        _apply_sql_scripts(settings, name)
        accounts, site_id, rider_id = _seed_accounts(settings, name)
    except Exception:
        drop_database(name)
        raise
    return PreparedDatabase(name=name, accounts=accounts, seed_site_id=site_id, seed_rider_id=rider_id)


def drop_database(name: str) -> None:
    """断开连接并删除测试库。只接受 ``fba_it_`` 前缀的库名。

    :param name: 测试库名
    """
    from backend.core.conf import settings

    _assert_test_db(name)
    with _maintenance_connection(settings) as conn:
        conn.execute(
            'SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()',
            (name,),
        )
        conn.execute(sql.SQL('DROP DATABASE IF EXISTS {}').format(sql.Identifier(name)))


class IntegrationRuntime:
    """一个测试模块共用的应用、客户端和角色 token。"""

    def __init__(self, prepared: PreparedDatabase, app: object) -> None:
        """记录已准备的库和应用，连接在 ``open`` 里建立。

        :param prepared: 测试库
        :param app: FastAPI 应用
        """
        self.prepared = prepared
        self.app = app
        self.accounts: dict[str, RoleAccount] = {}
        self.client: ApiClient | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._engine = None
        self._raw: httpx.AsyncClient | None = None
        self._conn = None
        self._trans = None
        self._maker = None
        self._pool_maker = None
        self._original_makers: dict | None = None
        self._original_engine = None
        self._original_engine_map: dict | None = None
        self._redis_prefix: dict[str, str] = {}
        self._run_prefix = ''
        self._closed = False

    @classmethod
    def open(cls, prepared: PreparedDatabase) -> 'IntegrationRuntime':
        """导入应用，把会话绑到测试库，并登录预置角色。

        :param prepared: 已建好的测试库
        :return: 运行时
        """
        from backend.main import app

        runtime = cls(prepared, app)
        runtime.loop = asyncio.new_event_loop()
        try:
            runtime.loop.run_until_complete(runtime._open_async())
        except Exception:
            runtime._shutdown_loop()
            runtime._restore_process()
            raise
        return runtime

    def close(self) -> None:
        """关闭客户端和连接池，恢复全局引擎与 Redis 前缀，并删掉本轮 Redis 键。"""
        global ACTIVE
        if self._closed:
            return
        self._closed = True
        if ACTIVE is self:
            ACTIVE = None
        try:
            if self.loop is not None and not self.loop.is_closed():
                self.loop.run_until_complete(self._close_async())
        finally:
            if self.loop is not None and not self.loop.is_closed():
                try:
                    self.loop.run_until_complete(_detach_redis())
                except Exception:
                    pass
            self._purge_redis()
            self._restore_process()
            self._shutdown_loop()

    def begin_test(self) -> None:
        """为当前用例开启外层事务。请求里的提交只会释放保存点。"""
        if self.loop is None:
            raise RuntimeError('集成运行时尚未打开')
        self.loop.run_until_complete(self._begin_test())

    def rollback_test(self) -> None:
        """回滚当前用例的外层事务。"""
        if self.loop is None:
            return
        self.loop.run_until_complete(self._rollback_test())

    async def _open_async(self) -> None:
        from backend.core.conf import settings
        from backend.database import db as db_mod

        self._engine = create_async_engine(
            _database_url(settings, self.prepared.name),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
        )
        self._bind_process(db_mod)
        self._swap_redis_prefix()
        await _ensure_redis()
        self._raw = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url=f'http://testserver{settings.FASTAPI_API_V1_PATH}',
            timeout=60.0,
        )
        await self._raw.__aenter__()
        self.client = ApiClient(self.loop, self._raw)
        await self._login_roles()

    async def _close_async(self) -> None:
        await self._rollback_test()
        if self._raw is not None:
            await self._raw.__aexit__(None, None, None)
            self._raw = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
        await _detach_redis()

    async def _begin_test(self) -> None:
        if self._conn is not None:
            return
        self._conn = await self._engine.connect()
        self._trans = await self._conn.begin()
        self._maker._makers['default'] = async_sessionmaker(
            bind=self._conn,
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode='create_savepoint',
        )

    async def _rollback_test(self) -> None:
        if self._trans is not None:
            await self._trans.rollback()
            self._trans = None
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
        if self._maker is not None and self._pool_maker is not None:
            self._maker._makers['default'] = self._pool_maker

    async def _login_roles(self) -> None:
        admin_id = self.prepared.accounts['admin'][1]
        self.accounts['admin'] = RoleAccount(
            key='admin',
            username='admin',
            user_id=admin_id,
            headers=await self._login('admin'),
        )
        for key, _role_id, _is_staff, _nickname in _ROLE_ROWS:
            username, user_id = self.prepared.accounts[key]
            self.accounts[key] = RoleAccount(
                key=key,
                username=username,
                user_id=user_id,
                headers=await self._login(username),
            )

    async def _login(self, username: str) -> dict[str, str]:
        from backend.core.conf import settings

        captcha = await self._raw.get('/auth/captcha')
        body = captcha.json()
        if captcha.status_code != 200 or body.get('code') != 200:
            raise RuntimeError(f'获取验证码失败：{captcha.text}')
        payload = {'username': username, 'password': _PASSWORD}
        data = body.get('data') or {}
        if data.get('is_enabled', True):
            redis_client = _sync_redis(settings)
            try:
                code = redis_client.get(f'{settings.LOGIN_CAPTCHA_REDIS_PREFIX}:{data["uuid"]}')
            finally:
                redis_client.close()
            if not code:
                raise RuntimeError(f'Redis 中没有验证码：{username}')
            payload['uuid'] = data['uuid']
            payload['captcha'] = code
        response = await self._raw.post('/auth/login', json=payload)
        logged = response.json()
        if response.status_code != 200 or logged.get('code') != 200:
            raise RuntimeError(f'登录失败 {username}：{response.text}')
        token = logged['data']['access_token']
        token_type = logged['data'].get('token_type') or 'Bearer'
        return {'Authorization': f'{token_type} {token}'}

    def _bind_process(self, db_mod: object) -> None:
        self._maker = db_mod.async_db_session
        self._original_makers = dict(self._maker._makers)
        self._original_engine = db_mod.async_engine
        self._original_engine_map = dict(db_mod._database_engines)
        self._pool_maker = async_sessionmaker(bind=self._engine, autoflush=False, expire_on_commit=False)
        self._maker._makers['default'] = self._pool_maker
        db_mod.async_engine = self._engine
        db_mod._database_engines['default'] = self._engine

    def _swap_redis_prefix(self) -> None:
        from backend.core.conf import settings

        self._run_prefix = f'fba:it:{os.getpid()}{uuid.uuid4().hex[:6]}'
        for field in _REDIS_FIELDS:
            current = getattr(settings, field)
            self._redis_prefix[field] = current
            setattr(settings, field, f'{self._run_prefix}:{current}')

    def _purge_redis(self) -> None:
        if not self._run_prefix.startswith('fba:it:'):
            return
        try:
            from backend.core.conf import settings

            client = _sync_redis(settings)
        except Exception:
            return
        try:
            keys = list(client.scan_iter(match=f'{self._run_prefix}:*'))
            if keys:
                client.delete(*keys)
        finally:
            client.close()

    def _restore_process(self) -> None:
        if self._maker is not None and self._original_makers is not None:
            self._maker._makers.clear()
            self._maker._makers.update(self._original_makers)
        try:
            from backend.database import db as db_mod
        except Exception:
            db_mod = None
        if db_mod is not None and self._original_engine is not None:
            db_mod.async_engine = self._original_engine
        if db_mod is not None and self._original_engine_map is not None:
            db_mod._database_engines.clear()
            db_mod._database_engines.update(self._original_engine_map)
        if self._redis_prefix:
            from backend.core.conf import settings

            for field, value in self._redis_prefix.items():
                setattr(settings, field, value)
            self._redis_prefix = {}

    def _shutdown_loop(self) -> None:
        if self.loop is not None and not self.loop.is_closed():
            self.loop.close()
        self.loop = None


ACTIVE: IntegrationRuntime | None = None


def _assert_test_db(name: str) -> None:
    if name == 'fba' or _DB_NAME_RE.fullmatch(name) is None:
        raise RuntimeError(f'拒绝操作非测试库：{name}')


def _database_url(settings: object, name: str) -> URL:
    return URL.create(
        drivername='postgresql+asyncpg',
        username=settings.DATABASE_USER,
        password=settings.DATABASE_PASSWORD,
        host=settings.DATABASE_HOST,
        port=settings.DATABASE_PORT,
        database=name,
    )


def _maintenance_connection(settings: object) -> psycopg.Connection:
    return psycopg.connect(
        host=settings.DATABASE_HOST,
        port=settings.DATABASE_PORT,
        user=settings.DATABASE_USER,
        password=settings.DATABASE_PASSWORD,
        dbname='postgres',
        connect_timeout=3,
        autocommit=True,
    )


def _sync_redis(settings: object) -> redis.Redis:
    return redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD or None,
        db=settings.REDIS_DATABASE,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    try:
        from backend.core.conf import settings

        if settings.DATABASE_PASSWORD:
            text = text.replace(settings.DATABASE_PASSWORD, '***')
    except Exception:
        return text
    return text


def _create_schema(settings: object, name: str) -> None:
    import backend

    from backend.common.model import MappedBase

    _ = backend

    async def _run() -> None:
        engine = create_async_engine(_database_url(settings, name), pool_pre_ping=True)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(MappedBase.metadata.create_all)
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _apply_sql_scripts(settings: object, name: str) -> None:
    env = os.environ.copy()
    env['PGPASSWORD'] = settings.DATABASE_PASSWORD
    for relative in (*_SQL_FILES, *_patch_files()):
        path = _BACKEND_ROOT / relative
        if not path.is_file():
            raise RuntimeError(f'缺少初始化脚本：{path}')
        result = subprocess.run(
            [
                'psql',
                '-h',
                str(settings.DATABASE_HOST),
                '-p',
                str(settings.DATABASE_PORT),
                '-U',
                str(settings.DATABASE_USER),
                '-d',
                name,
                '-v',
                'ON_ERROR_STOP=1',
                '-f',
                str(path),
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout)[-2000:]
            raise RuntimeError(f'执行 {relative} 失败：{detail}')


def _patch_files() -> tuple[str, ...]:
    patch_dir = _BACKEND_ROOT / 'plugin' / 'rider_salary' / 'sql' / 'patch'
    return tuple(
        f'plugin/rider_salary/sql/patch/{path.name}' for path in sorted(patch_dir.glob('*.sql')) if path.is_file()
    )


def _seed_accounts(settings: object, name: str) -> tuple[dict[str, tuple[str, int]], int, int]:
    accounts: dict[str, tuple[str, int]] = {}
    with psycopg.connect(
        host=settings.DATABASE_HOST,
        port=settings.DATABASE_PORT,
        user=settings.DATABASE_USER,
        password=settings.DATABASE_PASSWORD,
        dbname=name,
        autocommit=True,
    ) as conn:
        for table in _SEQUENCE_TABLES:
            _bump_sequence(conn, table)
        admin = conn.execute('SELECT id, password, salt FROM sys_user WHERE username = %s', ('admin',)).fetchone()
        if admin is None or admin[1] is None:
            raise RuntimeError('测试库缺少管理员账号')
        accounts['admin'] = ('admin', int(admin[0]))
        password, salt = admin[1], bytes(admin[2]) if admin[2] is not None else None
        for key, role_id, is_staff, nickname in _ROLE_ROWS:
            username = f'it_{key}'
            user_id = conn.execute(
                """
                INSERT INTO sys_user (
                    uuid, username, nickname, password, salt, status,
                    is_superuser, is_staff, is_multi_login, dept_id,
                    join_time, last_password_changed_time, created_time, deleted
                ) VALUES (
                    %s, %s, %s, %s, %s, 1,
                    false, %s, true, 1,
                    now(), now(), now(), 0
                )
                RETURNING id
                """,
                (uuid.uuid4().hex, username, nickname, password, salt, is_staff),
            ).fetchone()[0]
            conn.execute('INSERT INTO sys_user_role (user_id, role_id) VALUES (%s, %s)', (user_id, role_id))
            accounts[key] = (username, int(user_id))
        site_id = conn.execute(
            """
            INSERT INTO rs_site (code, name, settle_cycle, status, deleted, created_time)
            VALUES ('FXBASE', '夹具站点', 'month', 'enable', 0, now())
            RETURNING id
            """
        ).fetchone()[0]
        rider_id = conn.execute(
            """
            INSERT INTO rs_rider (
                job_no, name, site_id, hire_date, employ_type, status, user_id, deleted, created_time
            ) VALUES ('FXBASE001', '夹具骑手', %s, '2026-01-01', 'part_time', 'on_job', %s, 0, now())
            RETURNING id
            """,
            (site_id, accounts['rider'][1]),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO rs_site_manager (site_id, user_id, role, deleted, created_time)
            VALUES (%s, %s, 'owner', 0, now())
            """,
            (site_id, accounts['site_owner'][1]),
        )
    return accounts, int(site_id), int(rider_id)


def _bump_sequence(conn: psycopg.Connection, table: str) -> None:
    if table not in _SEQUENCE_TABLES:
        raise RuntimeError(f'拒绝调整非白名单序列：{table}')
    conn.execute(
        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
        f'GREATEST(COALESCE((SELECT MAX(id) FROM {table}), 1), 1))'
    )


async def _detach_redis() -> None:
    """丢掉绑在基座事件循环上的连接，换成尚未建连的连接池。

    全局客户端被其他模块按对象引用。只换连接池，后面的 TestClient 才能在自己的循环上重连。
    """
    from redis.asyncio import ConnectionPool

    from backend.core.conf import settings
    from backend.database.redis import redis_client

    old_pool = redis_client.connection_pool
    redis_client.connection = None
    try:
        await old_pool.disconnect(inuse_connections=True)
    except Exception:
        pass
    try:
        await old_pool.aclose()
    except Exception:
        pass
    redis_client.connection_pool = ConnectionPool(
        host=settings.REDIS_HOST,
        port=int(settings.REDIS_PORT),
        password=settings.REDIS_PASSWORD or None,
        db=int(settings.REDIS_DATABASE),
        socket_timeout=settings.REDIS_TIMEOUT,
        socket_connect_timeout=settings.REDIS_TIMEOUT,
        socket_keepalive=True,
        health_check_interval=30,
        decode_responses=True,
    )


async def _ensure_redis() -> None:
    from redis.asyncio import ConnectionPool

    from backend.core.conf import settings
    from backend.database.redis import redis_client

    try:
        await redis_client.ping()
    except Exception:
        redis_client.connection_pool = ConnectionPool(
            host=settings.REDIS_HOST,
            port=int(settings.REDIS_PORT),
            password=settings.REDIS_PASSWORD or None,
            db=int(settings.REDIS_DATABASE),
            decode_responses=True,
            socket_connect_timeout=settings.REDIS_TIMEOUT,
            socket_timeout=settings.REDIS_TIMEOUT,
        )
        redis_client.connection = None
        await redis_client.ping()
