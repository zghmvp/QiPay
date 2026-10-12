import type { CalendarDailyItem } from '@/types'

/** 日详情按日项标题。科目名始终可见，项名称不同时附在后面。 */
export function dailyItemTitle(item: Pick<CalendarDailyItem, 'name' | 'subject'>): string {
  const subject = item.subject?.trim() || '按日项'
  const name = item.name?.trim()
  if (name && name !== subject) return `${subject}（${name}）`
  return subject
}
