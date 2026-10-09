from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.common.log import log
from backend.database.db import async_db_session
from backend.plugin.rider_salary.utils.scope import warn_missing_scope_seeds


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """启动时检查全站可见权限码和骑手角色种子锚点是否已入库。

    :param _app: FastAPI 应用
    :return:
    """
    try:
        async with async_db_session() as db:
            await warn_missing_scope_seeds(db)
    except Exception:
        log.exception('校验全站可见权限码或骑手角色种子锚点失败')
    yield
