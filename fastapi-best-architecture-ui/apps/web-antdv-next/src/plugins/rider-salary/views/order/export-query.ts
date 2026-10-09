import { toDateString } from '../../utils/date';

export const ORDER_EXPORT_NEED_SITE = '请先选择站点';

export interface OrderExportQuery {
  date_from?: string;
  date_to?: string;
  rider_id?: number;
  site_id?: number;
}

function positiveId(value: unknown): number | undefined {
  if (value === null || value === undefined || value === '') return undefined;
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return undefined;
  return parsed;
}

/** 订单页导出只带站点、日期和骑手，与 `/orders/export` 的参数一致。 */
export function buildOrderExportQuery(formValues: {
  date_range?: [unknown, unknown] | null;
  rider_id?: unknown;
  site_id?: unknown;
}): OrderExportQuery {
  const query: OrderExportQuery = {};
  const siteId = positiveId(formValues.site_id);
  const riderId = positiveId(formValues.rider_id);
  if (siteId) query.site_id = siteId;
  if (riderId) query.rider_id = riderId;
  const range = formValues.date_range;
  const from = toDateString(range?.[0] as Parameters<typeof toDateString>[0]);
  const to = toDateString(range?.[1] as Parameters<typeof toDateString>[0]);
  if (from) query.date_from = from;
  if (to) query.date_to = to;
  return query;
}
