import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const advanceView = readFileSync(join(root, 'src/views/AdvanceView.vue'), 'utf8')

describe('预支撤回确认', () => {
  it('调用撤回接口前先弹出确认框', () => {
    const confirmAt = advanceView.indexOf('showConfirmDialog')
    const cancelAt = advanceView.indexOf('cancelAdvance(')
    assert.ok(confirmAt >= 0, '缺少确认框')
    assert.ok(cancelAt > confirmAt, '确认框必须出现在撤回请求之前')
    assert.match(advanceView, /撤回后需重新申请/)
    assert.match(advanceView, /title: '撤回申请'/)
  })
})
