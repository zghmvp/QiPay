function scopedSiteMonthQuery(
  siteId?: null | number,
  month?: string,
): Record<string, string> {
  const query: Record<string, string> = {};
  if (siteId && siteId > 0) query.site_id = String(siteId);
  if (month) query.month = month;
  return query;
}

/**
 * 离职仍有本月订单该行：进该骑手档案（带本月）。
 * 不带 rider_id、进离职总名单、进整站订单无该人/该月 = FAIL。
 */
export function resignedWithOrdersRowTarget(
  riderId: number,
  siteId?: null | number,
  month?: string,
): { path: string; query: Record<string, string> } {
  return {
    path: `/rider-salary/rider/${riderId}`,
    query: scopedSiteMonthQuery(siteId, month),
  };
}

/**
 * 离职仍有本月订单「查看全部」：status=resigned。
 * 已选站必须带当前 site_id+month。
 */
export function resignedWithOrdersViewAllTarget(
  siteId?: null | number,
  month?: string,
): { path: string; query: Record<string, string> } {
  return {
    path: '/rider-salary/rider',
    query: {
      status: 'resigned',
      ...(siteId && siteId > 0 ? scopedSiteMonthQuery(siteId, month) : {}),
    },
  };
}
