export const ORDER_WRITE_STALE_HINT = '需重算，尚未出账';

export function coveringCalcTarget(periodId: number): {
  path: string;
  query: Record<string, string>;
} {
  return {
    path: `/rider-salary/period/${periodId}/calculate`,
    query: {},
  };
}

export type OrderWriteKind = 'backfill' | 'fix';

export function orderWriteSuccessMessage(kind: OrderWriteKind): string {
  const verb = kind === 'fix' ? '已纠错订单' : '已补录订单';
  return `${verb}，${ORDER_WRITE_STALE_HINT}`;
}

export function monthFromBizDate(bizDate?: null | string): string | undefined {
  const text = String(bizDate ?? '').trim();
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(0, 7);
  if (/^\d{4}-\d{2}$/.test(text)) return text;
  return undefined;
}

export function isOpenOrReopened(status?: null | string): boolean {
  return status === 'open' || status === 'reopened';
}

export function coveringPeriodListTarget(
  siteId: number,
  month: string,
): { path: string; query: Record<string, string> } {
  return {
    path: '/rider-salary/period',
    query: {
      month,
      site_id: String(siteId),
    },
  };
}

export interface OrderWriteLanding {
  ctaLabel: string;
  path: string;
  query: Record<string, string>;
}

/**
 * 有覆盖期且 open|reopened → 该期算薪页。
 * 找不到覆盖期 → 该站周期列表带月，仍须写出需重算。
 */
export function resolveOrderWriteLanding(input: {
  bizDate?: null | string;
  periodId?: null | number;
  periodStatus?: null | string;
  siteId?: null | number;
}): OrderWriteLanding {
  const siteId = Number(input.siteId);
  const month = monthFromBizDate(input.bizDate);
  const periodId = Number(input.periodId);
  if (
    Number.isFinite(periodId) &&
    periodId > 0 &&
    isOpenOrReopened(input.periodStatus)
  ) {
    const calc = coveringCalcTarget(periodId);
    return {
      ctaLabel: '去该期算薪',
      path: calc.path,
      query: calc.query,
    };
  }
  if (Number.isFinite(siteId) && siteId > 0 && month) {
    const list = coveringPeriodListTarget(siteId, month);
    return {
      ctaLabel: '去周期列表',
      path: list.path,
      query: list.query,
    };
  }
  return {
    ctaLabel: '去周期列表',
    path: '/rider-salary/period',
    query: month ? { month } : {},
  };
}
