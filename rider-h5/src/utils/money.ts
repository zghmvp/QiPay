import type { MoneyValue } from '@/types'

function toNumber(value: MoneyValue): null | number {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

export function formatMoney(
  value: MoneyValue,
  options?: { sign?: boolean },
): string {
  const n = toNumber(value)
  if (n === null) return '—'
  const abs = new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  }).format(Math.abs(n))
  if (options?.sign) {
    if (n > 0) return `+${abs}`
    if (n < 0) return `-${abs}`
    return abs
  }
  return n < 0 ? `-${abs}` : abs
}

export function formatSigned(value: MoneyValue): string {
  return formatMoney(value, { sign: true })
}

export function moneyNumber(value: MoneyValue): number {
  return toNumber(value) ?? 0
}

export function isNegativeMoney(value: MoneyValue): boolean {
  const n = toNumber(value)
  return n !== null && n < 0
}

export function isPositiveMoney(value: MoneyValue): boolean {
  const n = toNumber(value)
  return n !== null && n > 0
}
