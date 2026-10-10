import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  MUST_CHANGE_PASSWORD_CODE,
  MUST_CHANGE_PASSWORD_ERROR,
  MUST_CHANGE_PASSWORD_MSG,
  isMustChangePassword,
  isMustChangePasswordError,
} from '../src/api/must-change.ts'

describe('首次改密错误', () => {
  it('识别固定中文错误和错误码', () => {
    const body = {
      code: MUST_CHANGE_PASSWORD_CODE,
      msg: MUST_CHANGE_PASSWORD_MSG,
      data: { error_code: MUST_CHANGE_PASSWORD_ERROR },
    }
    assert.equal(isMustChangePassword(body), true)
    assert.equal(isMustChangePasswordError({ response: { status: 423, data: body } }), true)
    assert.equal(isMustChangePassword({ code: 403, msg: '当前账号不是有效骑手账号' }), false)
    assert.equal(isMustChangePassword(null), false)
  })
})