import axios, { type AxiosError, type AxiosRequestConfig } from 'axios'
import { showToast } from 'vant'
import { applyApiBase } from '@/api/api-base'
import { MUST_CHANGE_PASSWORD_MSG, isMustChangePassword } from '@/api/must-change'
import { RIDER_ONLY_MSG, isReadGraceExpiredMessage, isRiderOnlyResponse } from '@/api/rider-only'
import { clearToken, getToken } from '@/utils/storage'
import type { ApiEnvelope } from '@/types'

export interface RequestConfig extends AxiosRequestConfig {
  skipToast?: boolean
  skipAuthRedirect?: boolean
}

const http = axios.create({
  timeout: 20000,
})

function extractMsg(payload: unknown, fallback: string): string {
  if (payload && typeof payload === 'object') {
    const data = payload as Record<string, unknown>
    if (typeof data.msg === 'string' && data.msg) return data.msg
    if (typeof data.detail === 'string' && data.detail) return data.detail
  }
  return fallback
}

async function redirectChangePassword() {
  const { default: router } = await import('@/router')
  if (router.currentRoute.value.path !== '/change-password') {
    await router.replace('/change-password')
  }
}

async function redirectLogin(message: string, cfg: RequestConfig) {
  const { default: router } = await import('@/router')
  if (!cfg.skipToast) showToast(message)
  if (router.currentRoute.value.path !== '/login') {
    await router.replace('/login')
  }
}

http.interceptors.request.use((config) => {
  const applied = applyApiBase(import.meta.env.VITE_API_BASE, config.url)
  config.baseURL = applied.baseURL
  config.url = applied.url
  const token = getToken()
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => {
    const envelope = response.data as ApiEnvelope<unknown> | undefined
    if (envelope && typeof envelope === 'object' && 'code' in envelope) {
      if (envelope.code !== 200) {
        const cfg = response.config as RequestConfig
        const msg = envelope.msg || '请求失败'
        if (isReadGraceExpiredMessage(msg)) {
          clearToken()
          void redirectLogin(msg, { ...cfg, skipToast: false })
          return Promise.reject(new Error(msg))
        }
        if (
          isRiderOnlyResponse({
            status: response.status,
            code: envelope.code,
            url: cfg.url,
            msg,
          })
        ) {
          clearToken()
          void redirectLogin(RIDER_ONLY_MSG, { ...cfg, skipToast: false })
          return Promise.reject(Object.assign(new Error(RIDER_ONLY_MSG), { riderOnly: true }))
        }
        if (!cfg.skipToast) showToast(msg)
        return Promise.reject(new Error(msg))
      }
      return envelope.data as never
    }
    return response.data as never
  },
  (error: AxiosError<ApiEnvelope<unknown>>) => {
    const cfg = (error.config || {}) as RequestConfig
    const status = error.response?.status
    const msg = extractMsg(error.response?.data, error.message || '网络异常')

    if (isMustChangePassword(error.response?.data)) {
      if (!cfg.skipToast) showToast(extractMsg(error.response?.data, MUST_CHANGE_PASSWORD_MSG))
      void redirectChangePassword()
      return Promise.reject(error)
    }

    const body = error.response?.data
    const bodyMsg = body && typeof body === 'object' && typeof body.msg === 'string' ? body.msg : msg
    if (isReadGraceExpiredMessage(bodyMsg)) {
      clearToken()
      void redirectLogin(bodyMsg, { ...cfg, skipToast: false })
      return Promise.reject(error)
    }
    if (
      isRiderOnlyResponse({
        status,
        code: body && typeof body === 'object' ? body.code : undefined,
        url: cfg.url,
        msg: bodyMsg,
      })
    ) {
      clearToken()
      void redirectLogin(RIDER_ONLY_MSG, { ...cfg, skipToast: false })
      return Promise.reject(error)
    }

    if (status === 401 && !cfg.skipAuthRedirect) {
      clearToken()
      void redirectLogin(msg || '请重新登录', cfg)
      return Promise.reject(error)
    }

    if (status === 403 && msg.includes('不是有效骑手')) {
      clearToken()
      void redirectLogin('当前账号不是有效骑手账号', { ...cfg, skipToast: false })
      return Promise.reject(error)
    }

    if (!cfg.skipToast) showToast(msg)
    return Promise.reject(error)
  },
)

export function request<T>(config: RequestConfig): Promise<T> {
  // 拦截器已把响应解包成 data，axios 的条件泛型无法表达这个返回值
  return http.request(config) as Promise<T>
}

export default http
