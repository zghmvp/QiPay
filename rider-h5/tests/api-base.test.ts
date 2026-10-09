import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { applyApiBase } from '../src/api/api-base.ts'

describe('applyApiBase', () => {
  it('开发环境把绝对源交给 axios，路径保持 /api/v1', () => {
    assert.deepEqual(applyApiBase('http://127.0.0.1:8000', '/api/v1/auth/login'), {
      baseURL: 'http://127.0.0.1:8000',
      url: '/api/v1/auth/login',
    })
  })

  it('去掉绝对源末尾斜杠', () => {
    assert.deepEqual(applyApiBase('http://127.0.0.1:8000/', '/api/v1/rider-salary/me/profile'), {
      baseURL: 'http://127.0.0.1:8000',
      url: '/api/v1/rider-salary/me/profile',
    })
  })

  it('生产相对路径 /api 不把已含 /api 的路径再拼一次', () => {
    assert.deepEqual(applyApiBase('/api', '/api/v1/auth/captcha'), {
      baseURL: '',
      url: '/api/v1/auth/captcha',
    })
  })

  it('生产 base 带末尾斜杠时同样不双写', () => {
    assert.deepEqual(applyApiBase('/api/', '/api/v1/rider-salary/me/profile'), {
      baseURL: '',
      url: '/api/v1/rider-salary/me/profile',
    })
  })

  it('相对 base 会补到尚未带该前缀的路径上', () => {
    assert.deepEqual(applyApiBase('/api', '/v1/auth/login'), {
      baseURL: '',
      url: '/api/v1/auth/login',
    })
  })

  it('未配置 base 时保持原路径', () => {
    assert.deepEqual(applyApiBase(undefined, '/api/v1/auth/logout'), {
      baseURL: '',
      url: '/api/v1/auth/logout',
    })
  })
})
