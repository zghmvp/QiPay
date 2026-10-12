import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'

import { stripAlicdnIconFont } from '../build/strip-alicdn-font.ts'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function read(relativePath: string): string {
  return readFileSync(join(root, relativePath), 'utf8')
}

describe('H5 字体自托管', () => {
  it('index.html 不再引用 Google Fonts，并用 base 引入本地样式', () => {
    const html = read('index.html')
    assert.equal(html.includes('fonts.googleapis.com'), false)
    assert.equal(html.includes('fonts.gstatic.com'), false)
    assert.match(html, /href="%BASE_URL%fonts\/barlow-condensed\.css"/)
  })

  it('字体文件用相对路径，不写死站点根路径', () => {
    const css = read('public/fonts/barlow-condensed.css')
    assert.match(css, /url\('\.\/barlow-condensed-600\.woff2'\)/)
    assert.match(css, /url\('\.\/barlow-condensed-700\.woff2'\)/)
    assert.equal(css.includes('fonts.googleapis.com'), false)
    assert.equal(css.includes('fonts.gstatic.com'), false)
    assert.equal(css.includes("url('/fonts/"), false)
    assert.equal(css.includes('url("/fonts/'), false)
  })

  it('数字字体是 woff2 子集，并附带可再分发的 OFL', () => {
    for (const name of ['barlow-condensed-600.woff2', 'barlow-condensed-700.woff2']) {
      const buf = readFileSync(join(root, 'public/fonts', name))
      assert.equal(buf.subarray(0, 4).toString('ascii'), 'wOF2')
      assert.ok(buf.length < 12_000, `${name} 应是数字子集，实际 ${buf.length} 字节`)
    }
    const ofl = read('public/fonts/OFL.txt')
    assert.match(ofl, /SIL OPEN FONT LICENSE Version 1\.1/)
    assert.match(ofl, /Barlow Project Authors/)
    assert.equal(/Reserved Font Name/i.test(ofl.split('PREAMBLE')[0] ?? ''), false)
  })

  it('Vant 图标字体去掉 alicdn 的 woff 回退，只留内嵌 woff2', () => {
    const css = read('node_modules/vant/es/icon/index.css')
    assert.equal(css.includes('at.alicdn.com'), true)
    const next = stripAlicdnIconFont(css)
    assert.equal(next.includes('at.alicdn.com'), false)
    assert.equal(next.includes('fonts.googleapis.com'), false)
    assert.match(next, /data:font\/woff2/)
    assert.match(next, /format\("woff2"\)/)
  })

  it('中文使用系统字体栈，数字仍用 Barlow Condensed', () => {
    const css = read('src/styles/theme.css')
    assert.match(css, /system-ui/)
    assert.match(css, /PingFang SC/)
    assert.match(css, /Microsoft YaHei/)
    assert.match(css, /'Barlow Condensed'/)
    assert.equal(css.includes('Noto Sans SC'), false)
    assert.equal(css.includes('IBM Plex Mono'), false)
    assert.equal(css.includes('fonts.googleapis.com'), false)
  })
})
