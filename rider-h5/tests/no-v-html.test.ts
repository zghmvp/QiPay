import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function collect(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === 'dist') continue
    const full = join(dir, entry.name)
    if (entry.isDirectory()) out.push(...collect(full))
    else if (/\.(vue|html|ts|js|mjs)$/.test(entry.name)) out.push(full)
  }
  return out
}

describe('H5 禁止 v-html', () => {
  it('源码出现 v-html 时本用例失败', () => {
    const files = [join(root, 'index.html'), ...collect(join(root, 'src')), ...collect(join(root, 'public'))]
    const hits: string[] = []
    for (const file of files) {
      const text = readFileSync(file, 'utf8')
      if (/\bv-html\b/.test(text)) hits.push(relative(root, file))
    }
    assert.deepEqual(hits, [], `禁止 v-html，命中：${hits.join(', ')}`)
  })
})
