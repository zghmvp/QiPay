import { formatMonthTitle } from '@/utils/date'
import type { AdvanceLimit, AdvanceMonthlyQuota } from '@/types'

const DEFAULT_LIMIT = 1

function toCount(value: unknown, fallback: number): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

/**
 * 管理端 GET /advances/quota 与 H5 GET /me/advance-quota 同一口径：
 * `monthly_advance_limit` / `used` / `remaining`（limit 为次数别名，不是金额）。
 * 接口未下发时仍绑定这些字段名，默认每月 1 次。
 */
export function readMonthlyAdvanceQuota(
  payload: AdvanceMonthlyQuota | AdvanceLimit | null | undefined,
): AdvanceMonthlyQuota {
  if (!payload) {
    return { monthly_advance_limit: DEFAULT_LIMIT, limit: DEFAULT_LIMIT, used: 0, remaining: DEFAULT_LIMIT }
  }
  const nested =
    payload.monthly_advance_limit && typeof payload.monthly_advance_limit === 'object'
      ? payload.monthly_advance_limit
      : null
  const countLimitRaw =
    nested?.limit ??
    (typeof payload.monthly_advance_limit === 'number' ? payload.monthly_advance_limit : undefined) ??
    nested?.monthly_advance_limit ??
    (payload.available == null ? payload.limit : undefined)
  const usedRaw = nested?.used ?? payload.used
  const remainingRaw = nested?.remaining ?? payload.remaining
  const month = nested?.month ?? payload.month
  const monthlyAdvanceLimit = toCount(countLimitRaw, DEFAULT_LIMIT)
  const used = toCount(usedRaw, 0)
  const remaining = remainingRaw != null ? toCount(remainingRaw, 0) : Math.max(monthlyAdvanceLimit - used, 0)
  return {
    monthly_advance_limit: monthlyAdvanceLimit,
    limit: monthlyAdvanceLimit,
    used,
    remaining,
    month,
  }
}

export function remainingAdvanceLabel(remaining: number): string {
  return `本月还可预支 ${remaining} 次`
}

export function monthlyQuotaBlockMessage(quota: AdvanceMonthlyQuota): string | null {
  const countLimit = toCount(quota.monthly_advance_limit ?? quota.limit, DEFAULT_LIMIT)
  if (quota.remaining > 0) return null
  if (countLimit <= 0) return '本站暂不可预支'
  const monthText = quota.month ? formatMonthTitle(quota.month) : ''
  if (monthText) return `本月预支次数已用完（${monthText}）`
  return '本月预支次数已用完'
}
