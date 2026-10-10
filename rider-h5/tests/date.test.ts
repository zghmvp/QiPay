import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import dayjs from 'dayjs'

import {
  WEEKDAY_LABELS,
  buildMonthMatrix,
  currentMonth,
  formatMonthTitle,
  shiftMonth,
  toDateString,
  toDateTimeString,
} from '../src/utils/date.ts'

function cell(month: string, week: number, day: number): string {
  const row = buildMonthMatrix(month)[week]
  assert.ok(row, `第 ${week} 周应存在`)
  const value = row[day]
  assert.ok(value, `第 ${week} 周第 ${day} 天应存在`)
  return value.format('YYYY-MM-DD')
}

describe('日期工具', () => {
  it('日期和日期时间格式化，空值与非法值返回 undefined', () => {
    assert.equal(toDateString('2026-10-09'), '2026-10-09')
    assert.equal(toDateString(dayjs('2026-10-09')), '2026-10-09')
    assert.equal(toDateString(new Date(2026, 9, 9, 15, 30)), '2026-10-09')
    assert.equal(toDateString(null), undefined)
    assert.equal(toDateString(undefined), undefined)
    assert.equal(toDateString(''), undefined)
    assert.equal(toDateString('不是日期'), undefined)

    assert.equal(toDateTimeString('2026-10-09 08:05:59'), '2026-10-09 08:05')
    assert.equal(toDateTimeString('2026-10-09T08:05:59'), '2026-10-09 08:05')
    assert.equal(toDateTimeString(dayjs('2026-10-09 08:05')), '2026-10-09 08:05')
    assert.equal(toDateTimeString(null), undefined)
    assert.equal(toDateTimeString('不是日期'), undefined)
  })

  it('当前月是 YYYY-MM，翻月能跨年', () => {
    assert.equal(currentMonth(), dayjs().format('YYYY-MM'))
    assert.match(currentMonth(), /^\d{4}-\d{2}$/)
    assert.equal(shiftMonth('2026-01', -1), '2025-12')
    assert.equal(shiftMonth('2026-12', 1), '2027-01')
    assert.equal(shiftMonth('2026-06', 0), '2026-06')
  })

  it('月份标题用中文，不补零', () => {
    assert.equal(formatMonthTitle('2026-09'), '2026年9月')
    assert.equal(formatMonthTitle('2026-10'), '2026年10月')
    assert.equal(formatMonthTitle('2026-01'), '2026年1月')
  })

  it('非法月份原样返回，不解析成 2001 年', () => {
    assert.equal(formatMonthTitle('not-a-month'), 'not-a-month')
    assert.equal(formatMonthTitle(''), '')
    assert.equal(shiftMonth('not-a-month', 1), 'not-a-month')
    assert.equal(shiftMonth('', -1), '')
    assert.equal(formatMonthTitle('2026-13'), '2026-13')
    assert.equal(shiftMonth('2026-13', 1), '2026-13')
  })

  it('周一起始，表头从一到日', () => {
    assert.deepEqual(WEEKDAY_LABELS, ['一', '二', '三', '四', '五', '六', '日'])
  })

  it('2026-06 从周一开始，六周补到 7 月 12 日', () => {
    const weeks = buildMonthMatrix('2026-06')
    assert.equal(weeks.length, 6)
    for (const week of weeks) assert.equal(week.length, 7)
    assert.equal(cell('2026-06', 0, 0), '2026-06-01')
    assert.equal(cell('2026-06', 0, 6), '2026-06-07')
    assert.equal(cell('2026-06', 5, 6), '2026-07-12')
  })

  it('2026-02 周日开月，首格补到 1 月 26 日', () => {
    assert.equal(cell('2026-02', 0, 0), '2026-01-26')
    assert.equal(cell('2026-02', 0, 6), '2026-02-01')
    assert.equal(cell('2026-02', 4, 6), '2026-03-01')
    assert.equal(cell('2026-02', 5, 6), '2026-03-08')
  })

  it('2026-09 周二开月，首格是 8 月 31 日', () => {
    assert.equal(cell('2026-09', 0, 0), '2026-08-31')
    assert.equal(cell('2026-09', 0, 1), '2026-09-01')
    assert.equal(cell('2026-09', 4, 2), '2026-09-30')
  })

  it('每一周都是连续的七天', () => {
    for (const week of buildMonthMatrix('2026-10')) {
      for (let index = 1; index < week.length; index += 1) {
        const prev = week[index - 1]
        const current = week[index]
        assert.ok(prev && current)
        assert.equal(current.diff(prev, 'day'), 1)
      }
    }
  })
})
