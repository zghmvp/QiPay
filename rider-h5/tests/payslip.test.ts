import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function read(relativePath: string): string {
  return readFileSync(join(root, relativePath), 'utf8')
}

describe('往期工资', () => {
  it('路由在兜底之前，入口在首页和我的', () => {
    const router = read('src/router/index.ts')
    const listAt = router.indexOf("path: '/payslips'")
    const detailAt = router.indexOf("path: '/payslips/:id'")
    const fallbackAt = router.indexOf('pathMatch')
    assert.ok(listAt > 0 && detailAt > listAt && fallbackAt > detailAt)
    assert.match(router, /往期工资/)
    assert.match(router, /工资条明细/)
    assert.match(read('src/views/HomeView.vue'), /\/payslips/)
    assert.match(read('src/views/MeView.vue'), /\/payslips/)
  })

  it('只请求骑手端工资条，页面不展示计算过程', () => {
    const api = read('src/api/me.ts')
    assert.match(api, /\/payslips/)
    assert.equal(api.includes('/payrolls'), false)
    for (const file of ['src/views/PayslipsView.vue', 'src/views/PayslipDetailView.vue']) {
      const text = read(file)
      assert.equal(text.includes('calc_trace'), false, file)
      assert.equal(text.includes('v-html'), false, file)
    }
  })

  it('离职只读时不能提交或撤回预支', () => {
    const advance = read('src/views/AdvanceView.vue')
    assert.match(advance, /read_only/)
    assert.match(advance, /离职后只能查看预支记录，不能提交或撤回/)
    const guard = advance.indexOf('if (readOnly.value)')
    const submit = advance.indexOf('createAdvance(')
    assert.ok(guard >= 0 && submit > guard)
    assert.match(advance, /!readOnly\.value && item\.status === 'pending'/)
  })
})
