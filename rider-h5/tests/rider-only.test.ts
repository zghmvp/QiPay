import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  MUST_CHANGE_PASSWORD_CODE,
  MUST_CHANGE_PASSWORD_ERROR,
  MUST_CHANGE_PASSWORD_MSG,
  isMustChangePassword,
} from '../src/api/must-change.ts'
import {
  RIDER_ONLY_MSG,
  isMeProfileUrl,
  isReadGraceExpiredMessage,
  isRiderOnlyError,
  isRiderOnlyResponse,
} from '../src/api/rider-only.ts'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const PROFILE = '/api/v1/rider-salary/me/profile'

function read(relativePath: string): string {
  return readFileSync(join(root, relativePath), 'utf8')
}

describe('资料接口 403', () => {
  it('管理员登录后资料接口 403 判定为仅骑手可用', () => {
    assert.equal(RIDER_ONLY_MSG, '仅骑手可用')
    assert.equal(isMeProfileUrl(PROFILE), true)
    assert.equal(isMeProfileUrl(`${PROFILE}?t=1`), true)
    assert.equal(isMeProfileUrl(`http://127.0.0.1:8000${PROFILE}`), true)
    assert.equal(
      isRiderOnlyResponse({
        status: 403,
        code: 403,
        url: PROFILE,
      }),
      true,
    )
    assert.equal(
      isRiderOnlyError({
        response: { status: 403, data: { code: 403, msg: 'Forbidden' } },
        config: { url: PROFILE },
      }),
      true,
    )
  })

  it('非资料接口的 403 不套用这句说明', () => {
    assert.equal(isMeProfileUrl('/api/v1/rider-salary/me/calendar'), false)
    assert.equal(isMeProfileUrl('/api/v1/rider-salary/me/profiles'), false)
    assert.equal(
      isRiderOnlyResponse({
        status: 403,
        code: 403,
        url: '/api/v1/rider-salary/me/calendar',
      }),
      false,
    )
    assert.equal(isRiderOnlyResponse({ status: 401, url: PROFILE }), false)
    assert.equal(isRiderOnlyResponse({ status: 500, code: 500, url: PROFILE }), false)
  })

  it('离职超过查阅期限不会被当成仅骑手可用', () => {
    const msg = '离职已超过查阅期限，当前账号不是有效骑手账号'
    assert.equal(isReadGraceExpiredMessage(msg), true)
    assert.equal(
      isRiderOnlyResponse({
        status: 403,
        code: 403,
        url: PROFILE,
        msg,
      }),
      false,
    )
    assert.equal(
      isRiderOnlyError({
        response: { status: 403, data: { code: 403, msg } },
        config: { url: PROFILE },
      }),
      false,
    )
    assert.equal(
      isRiderOnlyResponse({
        status: 403,
        code: 403,
        url: PROFILE,
        msg: '当前账号不是有效骑手账号',
      }),
      true,
    )
  })

  it('423 须改密不会被当成仅骑手可用', () => {
    const body = {
      code: MUST_CHANGE_PASSWORD_CODE,
      msg: MUST_CHANGE_PASSWORD_MSG,
      data: { error_code: MUST_CHANGE_PASSWORD_ERROR },
    }
    assert.equal(isMustChangePassword(body), true)
    assert.equal(
      isRiderOnlyResponse({
        status: MUST_CHANGE_PASSWORD_CODE,
        code: body.code,
        url: PROFILE,
      }),
      false,
    )
    assert.equal(
      isRiderOnlyError({
        response: { status: 423, data: body },
        config: { url: PROFILE },
      }),
      false,
    )
  })
})

describe('页面可缩放与登录说明', () => {
  it('viewport 去掉禁止缩放', () => {
    const html = read('index.html')
    assert.equal(html.includes('user-scalable'), false)
    assert.equal(/maximum-scale\s*=/.test(html), false)
    assert.equal(/minimum-scale\s*=/.test(html), false)
    assert.match(html, /width=device-width/)
    assert.match(html, /initial-scale=1/)
    assert.match(html, /viewport-fit=cover/)
  })

  it('登录页写明仅骑手可用，且须改密判断仍在资料 403 之前', () => {
    const login = read('src/views/LoginView.vue')
    assert.match(login, /仅骑手可用/)
    const mustChange = login.indexOf('isMustChangePasswordError')
    const riderOnly = login.indexOf('isRiderOnlyError')
    assert.ok(mustChange >= 0 && riderOnly > mustChange)

    const http = read('src/api/http.ts')
    const errorHandler = http.slice(http.indexOf('(error: AxiosError'))
    const httpMustChange = errorHandler.indexOf('isMustChangePassword(')
    const httpGrace = errorHandler.indexOf('isReadGraceExpiredMessage(')
    const httpRiderOnly = errorHandler.indexOf('isRiderOnlyResponse(')
    assert.ok(httpMustChange >= 0 && httpGrace > httpMustChange && httpRiderOnly > httpGrace)
    assert.match(http, /redirectChangePassword/)
    assert.match(http, /RIDER_ONLY_MSG/)
    assert.match(http, /不是有效骑手/)
  })
})
