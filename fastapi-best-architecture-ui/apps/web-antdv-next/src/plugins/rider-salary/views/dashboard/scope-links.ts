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

/** 无方案日该行：档案绑定时间轴。只进日历（即使带齐 rider/site/month）= FAIL。 */
export function noPlanBindingTarget(
  riderId: number,
  siteId?: null | number,
  month?: string,
): { path: string; query: Record<string, string> } {
  return {
    path: `/rider-salary/rider/${riderId}`,
    query: {
      tab: 'binding',
      ...scopedSiteMonthQuery(siteId, month),
    },
  };
}

/** 无方案日「查看全部」：骑手名单，每行能进绑定。禁止空日历。 */
export function noPlanViewAllTarget(
  siteId?: null | number,
  month?: string,
): { path: string; query: Record<string, string> } {
  return {
    path: '/rider-salary/rider',
    query: {
      from: 'no_plan',
      ...scopedSiteMonthQuery(siteId, month),
    },
  };
}

/** 需重算「查看全部」：stale=1 必须带当前站+月（无站仍带月）。禁止只抛全站 stale。 */
export function stalePeriodsViewAllTarget(
  siteId?: null | number,
  month?: string,
): { path: string; query: Record<string, string> } {
  return {
    path: '/rider-salary/period',
    query: {
      stale: '1',
      ...scopedSiteMonthQuery(siteId, month),
    },
  };
}

/** 待审核预支「查看全部」：必须带当前站月，禁止只抛全站 pending。 */
export function pendingAdvancesViewAllTarget(
  siteId?: null | number,
  month?: string,
): { path: string; query: Record<string, string> } {
  return {
    path: '/rider-salary/advance',
    query: {
      status: 'pending',
      ...scopedSiteMonthQuery(siteId, month),
    },
  };
}

/** 待审核预支该行：带该条 id，进页能办这一条。 */
export function pendingAdvanceRowTarget(
  id: number,
  siteId?: null | number,
  month?: string,
): { path: string; query: Record<string, string> } {
  return {
    path: '/rider-salary/advance',
    query: {
      id: String(id),
      status: 'pending',
      ...scopedSiteMonthQuery(siteId, month),
    },
  };
}

/**
 * 需重算该行：进该周期算薪页。只开 /period?id= 抽屉 = FAIL。
 * 禁止 auto=1，进页不自动开算。
 */
export function stalePeriodCalcTarget(periodId: number): {
  path: string;
  query: Record<string, string>;
} {
  return {
    path: `/rider-salary/period/${periodId}/calculate`,
    query: {},
  };
}

/** 周期列表消费 stale=1 + 当前站月。忽略 query 仍全站 = FAIL。 */
export function periodStaleListParams(
  siteId?: null | number,
  month?: string,
): { month?: string; site_id?: number; stale: true } {
  return {
    stale: true,
    ...(siteId && siteId > 0 ? { site_id: siteId } : {}),
    ...(month ? { month } : {}),
  };
}
