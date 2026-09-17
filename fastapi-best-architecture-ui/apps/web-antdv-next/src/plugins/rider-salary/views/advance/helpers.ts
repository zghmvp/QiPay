import type { AdvanceQuota, AdvanceResult } from '../../types/advance';

function toCount(value: unknown): null | number {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return null;
  return Math.max(0, Math.trunc(n));
}

function fromParts(
  limit: unknown,
  used: unknown,
  remaining: unknown,
): AdvanceQuota | null {
  const parsedLimit = toCount(limit);
  const parsedUsed = toCount(used);
  const parsedRemaining = toCount(remaining);
  if (parsedLimit === null && parsedUsed === null && parsedRemaining === null) {
    return null;
  }
  const resolvedLimit = parsedLimit ?? 0;
  const resolvedUsed = parsedUsed ?? 0;
  return {
    limit: resolvedLimit,
    remaining:
      parsedRemaining ?? Math.max(resolvedLimit - resolvedUsed, 0),
    used: resolvedUsed,
  };
}

/** 从列表/详情/独立查询里抽出本月次数，兼容嵌套 quota 与扁平字段。 */
export function resolveAdvanceQuota(
  row?: AdvanceQuota | AdvanceResult | null,
): AdvanceQuota | null {
  if (!row) return null;
  if ('quota' in row && row.quota) {
    const nested = fromParts(row.quota.limit, row.quota.used, row.quota.remaining);
    if (nested) return nested;
  }
  if ('limit' in row && !('amount' in row)) {
    const direct = fromParts(row.limit, row.used, row.remaining);
    if (direct) return direct;
  }
  if ('monthly_advance_limit' in row || 'monthly_advance_used' in row) {
    return fromParts(
      row.monthly_advance_limit,
      row.monthly_advance_used,
      row.monthly_advance_remaining,
    );
  }
  return null;
}

export function formatAdvanceQuota(quota: AdvanceQuota | null): string {
  if (!quota) return '—';
  if (quota.limit === 0) return '本站暂不可预支';
  return `已用 ${quota.used} / ${quota.limit}（剩 ${quota.remaining}）`;
}
