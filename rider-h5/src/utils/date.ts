import dayjs, { type Dayjs } from 'dayjs'

export function currentMonth(): string {
  return dayjs().format('YYYY-MM')
}

export function toDateString(value: Date | Dayjs | null | string | undefined) {
  if (!value) return undefined
  const d = dayjs(value)
  return d.isValid() ? d.format('YYYY-MM-DD') : undefined
}

export function toDateTimeString(
  value: Date | Dayjs | null | string | undefined,
) {
  if (!value) return undefined
  const d = dayjs(value)
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : undefined
}

/** 周一起始的 6×7 月历矩阵，含上月末/下月初补齐格 */
export function buildMonthMatrix(month: string): Dayjs[][] {
  const start = dayjs(`${month}-01`)
  const weekday = start.day()
  const mondayOffset = weekday === 0 ? 6 : weekday - 1
  const first = start.subtract(mondayOffset, 'day')
  const weeks: Dayjs[][] = []
  for (let w = 0; w < 6; w += 1) {
    const week: Dayjs[] = []
    for (let d = 0; d < 7; d += 1) {
      week.push(first.add(w * 7 + d, 'day'))
    }
    weeks.push(week)
  }
  return weeks
}

export const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日']

const YEAR_MONTH = /^\d{4}-(?:0[1-9]|1[0-2])$/

function strictMonth(month: string): Dayjs | undefined {
  if (!YEAR_MONTH.test(month)) return undefined
  const d = dayjs(`${month}-01`)
  if (!d.isValid() || d.format('YYYY-MM') !== month) return undefined
  return d
}

export function shiftMonth(month: string, delta: number): string {
  const d = strictMonth(month)
  if (!d) return month
  return d.add(delta, 'month').format('YYYY-MM')
}

export function formatMonthTitle(month: string): string {
  const d = strictMonth(month)
  return d ? d.format('YYYY年M月') : month
}
