import type { LocationQuery, LocationQueryRaw } from 'vue-router';

import type { PeriodQuery } from '../../types/period';

/** 工作台「需重算」深链同时带上的周期状态。 */
export const STALE_PERIOD_STATUSES = ['open', 'reopened'] as const;

/** 把路由上的 status 收成列表。支持逗号分隔，也支持重复参数。 */
export function parseStatusQuery(raw: unknown): string[] {
  const parts = Array.isArray(raw) ? raw : raw == null || raw === '' ? [] : [raw];
  const values: string[] = [];
  for (const part of parts) {
    if (typeof part !== 'string') continue;
    for (const item of part.split(',')) {
      const text = item.trim();
      if (text && !values.includes(text)) values.push(text);
    }
  }
  return values;
}

/**
 * 关掉「需重算」提示时用的查询。
 * 去掉 stale，其余参数（尤其 status）原样保留，刷新后不再回到只看需重算。
 */
export function omitStaleQuery(query: LocationQuery): LocationQueryRaw {
  const next: LocationQueryRaw = { ...query };
  delete next.stale;
  return next;
}

/** 工作台用 stale=1 或 stale=true 表示只看需重算。 */
export function parseStaleFlag(raw: unknown): boolean {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value === true || value === 1 || value === '1' || value === 'true';
}

/** 多个状态合成一个查询参数，空则不传。 */
export function joinStatusQuery(
  status: string | string[] | null | undefined,
): string | undefined {
  const values = parseStatusQuery(status ?? undefined);
  return values.length ? values.join(',') : undefined;
}

/** 周期列表请求参数。需重算交给服务端，不再裁当前页。 */
export function buildPeriodListQuery(input: {
  month?: string;
  onlyStale?: boolean;
  page?: number;
  rider_id?: number;
  site_id?: number;
  size?: number;
  status?: string | string[] | null;
}): PeriodQuery {
  const status = joinStatusQuery(input.status);
  const query: PeriodQuery = {
    page: input.page,
    size: input.size,
  };
  if (input.site_id != null) query.site_id = input.site_id;
  if (input.rider_id != null) query.rider_id = input.rider_id;
  if (input.month) query.month = input.month;
  if (status) query.status = status;
  if (input.onlyStale) query.stale = true;
  return query;
}
