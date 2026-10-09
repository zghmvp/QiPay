import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'

import { dailyItemTitle } from '../src/utils/daily-item.ts'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const dayView = readFileSync(join(root, 'src/views/DayView.vue'), 'utf8')

describe('日详情按日项', () => {
  it('冲单奖科目在标题中可见', () => {
    const title = dailyItemTitle({ subject: '冲单奖', name: '日冲单', amount: '50.00' })
    assert.match(title, /冲单奖/)
    assert.match(title, /日冲单/)
    assert.equal(dailyItemTitle({ subject: '冲单奖', name: '冲单奖', amount: 50 }), '冲单奖')
    assert.equal(dailyItemTitle({ subject: '  ', name: null, amount: 0 }), '按日项')
  })

  it('页面展示 daily_items，并在加载失败时提供重试', () => {
    assert.match(dayView, /Skeleton/)
    assert.match(dayView, /v-if="loading"/)
    assert.match(dayView, /v-else-if="failed"/)
    assert.match(dayView, /明细加载失败，请重试/)
    assert.match(dayView, />重试</)
    assert.match(dayView, /detail\.daily_items/)
    assert.match(dayView, /按日项/)
    assert.match(dayView, /dailyItemTitle\(item\)/)
    assert.match(dayView, /title="按日项" name="daily"/)
    assert.match(dayView, /\['orders', 'daily'\]/)
    const confirmRetry = dayView.indexOf('@click="load"')
    assert.ok(confirmRetry > dayView.indexOf('failed'), '重试按钮在失败态里')
  })
})
