from calendar import monthrange
from collections.abc import Iterable
from datetime import date

from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.log import log
from backend.core.conf import settings
from backend.database.redis import redis_client
from backend.plugin.rider_salary.enums import PayrollStatus, PeriodStatus
from backend.plugin.rider_salary.model.payroll import RiderSalaryPayroll
from backend.plugin.rider_salary.model.settle_period import RiderSalarySettlePeriod

# 设计假设（Q-19 推荐规模）：20 个站点、2000 名骑手、日 6 万单、保留 2 年。
# 预估和导入覆盖日都按这个量级做短缓存；失效仍以 mark_stale 为准，TTL 只兜底漏网写入。
ESTIMATE_CACHE_TTL_SECONDS = 600
COVERAGE_CACHE_TTL_SECONDS = 600
_TEST_REDIS_RUN_PREFIX = 'fba:it:'


def scoped_redis_key(key: str) -> str:
    """集成测试把 Redis 前缀换成 ``fba:it:…`` 时，预估和覆盖日键跟着隔离。

    :param key: 生产环境使用的键
    :return: 测试会话中的带前缀键；生产环境原样返回
    """
    sample = str(getattr(settings, 'JWT_USER_REDIS_PREFIX', '') or '')
    if not sample.startswith(_TEST_REDIS_RUN_PREFIX):
        return key
    split_at = sample.find(':', len(_TEST_REDIS_RUN_PREFIX))
    if split_at <= 0:
        return key
    return f'{sample[:split_at]}:{key}'


def estimate_cache_key(rider_id: int) -> str:
    """骑手当前周期预估。一个骑手一把键，读的时候再核对周期区间和状态。

    :param rider_id: 骑手 ID
    :return: Redis 键
    """
    return scoped_redis_key(f'rs:h5:estimate:{int(rider_id)}')


def coverage_month_prefix(month_start: date) -> str:
    """某自然月导入覆盖日的键前缀，后面接站点 ID。

    :param month_start: 月初
    :return: Redis 键前缀
    """
    return scoped_redis_key(f'rs:h5:cov:{month_start:%Y-%m}')


def coverage_cache_key(site_id: int, month_start: date) -> str:
    """站点在某自然月的导入覆盖日。

    :param site_id: 站点 ID
    :param month_start: 月初
    :return: Redis 键
    """
    return f'{coverage_month_prefix(month_start)}:{int(site_id)}'


def month_windows(start: date | None, end: date | None) -> list[tuple[date, date]]:
    """闭区间覆盖的自然月，每月为 [月初, 月末]。

    :param start: 开始日期
    :param end: 结束日期
    :return: 按时间顺序的自然月
    """
    if not isinstance(start, date) or not isinstance(end, date) or end < start:
        return []
    windows: list[tuple[date, date]] = []
    cursor = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    while cursor <= last:
        month_end = date(cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1])
        windows.append((cursor, month_end))
        year = cursor.year + 1 if cursor.month == 12 else cursor.year
        month = 1 if cursor.month == 12 else cursor.month + 1
        cursor = date(year, month, 1)
    return windows


async def get_cached_text(key: str) -> str | None:
    """读取字符串缓存。Redis 不可用时当作未命中，不打断接口。

    :param key: Redis 键
    :return: 缓存正文；没有或读失败时为 None
    """
    try:
        raw = await redis_client.get(key)
    except RedisError:
        log.warning('读取缓存失败：{}', key)
        return None
    if not raw:
        return None
    return raw if isinstance(raw, str) else str(raw)


async def set_cached_text(key: str, payload: str, *, ttl_seconds: int) -> None:
    """写入字符串缓存。写失败只记日志。

    :param key: Redis 键
    :param payload: 正文
    :param ttl_seconds: 过期秒数
    :return:
    """
    try:
        await redis_client.set(key, payload, ex=ttl_seconds)
    except RedisError:
        log.warning('写入缓存失败：{}', key)


async def invalidate_salary_caches(
    rider_ids: Iterable[int],
    date_from: date | None,
    date_to: date | None,
) -> None:
    """清掉受影响骑手的预估，以及日期范围内各自然月的导入覆盖日缓存。

    :param rider_ids: 受影响骑手
    :param date_from: 开始日期
    :param date_to: 结束日期
    :return:
    """
    keys = [estimate_cache_key(rider_id) for rider_id in {int(rider_id) for rider_id in rider_ids}]
    if keys:
        try:
            await redis_client.delete(*keys)
        except RedisError:
            log.warning('清除骑手预估缓存失败')
    try:
        for month_start, _month_end in month_windows(date_from, date_to):
            await redis_client.delete_by_prefix(coverage_month_prefix(month_start))
    except RedisError:
        log.warning('清除导入覆盖日期缓存失败')


async def mark_stale(
    db: AsyncSession,
    *,
    rider_ids: Iterable[int],
    date_from: date,
    date_to: date,
) -> int:
    """
    将覆盖日期范围内、开放或补发中周期（骑手级或 rider_id=0 站点级）下的草稿薪资单标记为需重算。

    同时清掉这些骑手的 H5 预估缓存，以及该日期范围所在自然月的导入覆盖日缓存。
    没有草稿薪资单时也同样清缓存：预估可能尚未落库。

    :param db: 数据库会话
    :param rider_ids: 受影响骑手 ID
    :param date_from: 开始日期
    :param date_to: 结束日期
    :return:
    """
    ids = list({int(rider_id) for rider_id in rider_ids})
    if not ids:
        return 0

    overlapping = select(RiderSalarySettlePeriod.id).where(
        RiderSalarySettlePeriod.status.in_([PeriodStatus.open, PeriodStatus.reopened]),
        RiderSalarySettlePeriod.start_date <= date_to,
        RiderSalarySettlePeriod.end_date >= date_from,
        RiderSalarySettlePeriod.deleted == 0,
        RiderSalarySettlePeriod.rider_id.in_([*ids, 0]),
    )
    stmt = (
        update(RiderSalaryPayroll)
        .where(
            RiderSalaryPayroll.rider_id.in_(ids),
            RiderSalaryPayroll.status == PayrollStatus.draft,
            RiderSalaryPayroll.deleted == 0,
            RiderSalaryPayroll.period_id.in_(overlapping),
        )
        .values(stale=True)
    )
    result = await db.execute(stmt)
    await invalidate_salary_caches(ids, date_from, date_to)
    return int(result.rowcount or 0)
