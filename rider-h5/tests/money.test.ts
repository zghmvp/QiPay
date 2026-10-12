import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  formatMoney,
  formatSigned,
  isNegativeMoney,
  isPositiveMoney,
  moneyNumber,
} from '../src/utils/money.ts'

describe('金额格式化', () => {
  it('空值和无法解析的值显示破折号', () => {
    assert.equal(formatMoney(null), '—')
    assert.equal(formatMoney(undefined), '—')
    assert.equal(formatMoney(''), '—')
    assert.equal(formatMoney('abc'), '—')
    assert.equal(formatMoney('1,234.50'), '—')
  })

  it('保留两位小数，千分位用逗号，负数只加一个减号', () => {
    assert.equal(formatMoney(0), '0.00')
    assert.equal(formatMoney('0'), '0.00')
    assert.equal(formatMoney('12.5'), '12.50')
    assert.equal(formatMoney('12.50'), '12.50')
    assert.equal(formatMoney(1234.5), '1,234.50')
    assert.equal(formatMoney('1234.5'), '1,234.50')
    assert.equal(formatMoney(-3.2), '-3.20')
    assert.equal(formatMoney('-1234.5'), '-1,234.50')
  })

  it('带符号时正数加正号，零不加号', () => {
    assert.equal(formatMoney('2', { sign: true }), '+2.00')
    assert.equal(formatMoney('-1.5', { sign: true }), '-1.50')
    assert.equal(formatMoney(0, { sign: true }), '0.00')
    assert.equal(formatMoney('abc', { sign: true }), '—')
    assert.equal(formatSigned('8.1'), '+8.10')
    assert.equal(formatSigned('-8.1'), '-8.10')
    assert.equal(formatSigned(0), '0.00')
  })

  it('数值换算把空值当 0，正负判断不把 0 算进去', () => {
    assert.equal(moneyNumber(null), 0)
    assert.equal(moneyNumber(undefined), 0)
    assert.equal(moneyNumber(''), 0)
    assert.equal(moneyNumber('x'), 0)
    assert.equal(moneyNumber('12.30'), 12.3)
    assert.equal(moneyNumber(-2), -2)

    assert.equal(isNegativeMoney('-0.01'), true)
    assert.equal(isNegativeMoney(-1), true)
    assert.equal(isNegativeMoney(0), false)
    assert.equal(isNegativeMoney('0.00'), false)
    assert.equal(isNegativeMoney(null), false)
    assert.equal(isNegativeMoney('abc'), false)

    assert.equal(isPositiveMoney('0.01'), true)
    assert.equal(isPositiveMoney(1), true)
    assert.equal(isPositiveMoney(0), false)
    assert.equal(isPositiveMoney('-1'), false)
    assert.equal(isPositiveMoney(undefined), false)
  })
})
