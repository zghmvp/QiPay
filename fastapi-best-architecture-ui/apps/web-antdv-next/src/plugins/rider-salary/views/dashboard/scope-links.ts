import { monthRange } from '../../utils/date';

export function scopedSiteMonthQuery(
  siteId?: null | number,
  month?: string,
): Record<string, string> {
  const query: Record<string, string> = {};
  if (siteId && siteId > 0) query.site_id = String(siteId);
  if (month) query.month = month;
  return query;
}

export function monthWindowQuery(month?: string): Record<string, string> {
  if (!month) return {};
  const [date_from, date_to] = monthRange(month);
  return { date_from, date_to };
}

function siteOnly(siteId?: null | number): Record<string, string> {
  return siteId && siteId > 0 ? { site_id: String(siteId) } : {};
}

/** 六张洞察卡：已选站+月必须带 site_id+month；无站仍带月。 */
export function insightCardTarget(
  key: string,
  siteId?: null | number,
  month?: string,
): { path: string; query: Record<string, string> } {
  const siteMonth = scopedSiteMonthQuery(siteId, month);
  const window = monthWindowQuery(month);
  switch (key) {
    case 'on_job_riders':
      return {
        path: '/rider-salary/rider',
        query: { ...siteMonth, status: 'on_job' },
      };
    case 'month_order_count':
    case 'month_valid_order_count':
      return {
        path: '/rider-salary/order',
        query: { ...siteOnly(siteId), ...window },
      };
    case 'estimated_gross':
      return { path: '/rider-salary/period', query: siteMonth };
    case 'pending_advances':
      return {
        path: '/rider-salary/advance',
        query: { ...siteMonth, status: 'pending' },
      };
    case 'to_pay_advances':
      return {
        path: '/rider-salary/advance',
        query: { ...siteMonth, status: 'to_pay' },
      };
    default:
      return { path: '/rider-salary/dashboard', query: siteMonth };
  }
}

export function orderImportTarget(
  siteId?: null | number,
  month?: string,
): { path: string; query: Record<string, string> } {
  return {
    path: '/rider-salary/order',
    query: { ...siteOnly(siteId), ...monthWindowQuery(month) },
  };
}

export function calendarRiderTarget(
  riderId: number,
  siteId?: null | number,
  month?: string,
): { path: string; query: Record<string, string> } {
  return {
    path: '/rider-salary/calendar',
    query: {
      rider_id: String(riderId),
      ...scopedSiteMonthQuery(siteId, month),
    },
  };
}

/** 工作台异常落地：attention=1，禁止只抛 status=abnormal。 */
export function abnormalAttentionTarget(
  siteId?: null | number,
  month?: string,
  orderNo?: string,
): { path: string; query: Record<string, string> } {
  return {
    path: '/rider-salary/order',
    query: {
      attention: '1',
      ...siteOnly(siteId),
      ...monthWindowQuery(month),
      ...(orderNo ? { order_no: orderNo } : {}),
    },
  };
}

/** 倒计时「查看全部」：带站，禁止只切无月份的 status=open。 */
export function lockCountdownViewAllTarget(
  siteId?: null | number,
): { path: string; query: Record<string, string> } {
  return {
    path: '/rider-salary/period',
    query: {
      lock_due: '1',
      ...siteOnly(siteId),
    },
  };
}
