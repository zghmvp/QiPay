export const CALENDAR_MONTH_EXPORT_NEED_SCOPE = '请选择站点和骑手';

export interface CalendarMonthExportParams {
  month: string;
  rider_id: number;
  site_id: number;
}

/** 一个月一次请求。半月结不再按周期拆成多次下载。 */
export function buildCalendarMonthExport(input: {
  month: string;
  riderId?: number;
  siteId?: number;
}): CalendarMonthExportParams | undefined {
  if (!input.siteId || !input.riderId || !input.month) return undefined;
  return {
    month: input.month,
    rider_id: input.riderId,
    site_id: input.siteId,
  };
}
