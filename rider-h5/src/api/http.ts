import axios, { type AxiosError, type AxiosRequestConfig } from 'axios'
import { showToast } from 'vant'
import { clearToken, getToken } from '@/utils/storage'
import type { ApiEnvelope } from '@/types'

export interface RequestConfig extends AxiosRequestConfig {
  skipToast?: boolean
  skipAuthRedirect?: boolean
}

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE,
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

async function redirectLogin(message: string, cfg: RequestConfig) {
  const { default: router } = await import('@/router')
  if (!cfg.skipToast) showToast(message)
  if (router.currentRoute.value.path !== '/login') {
    await router.replace('/login')
  }
}

http.interceptors.request.use((config) => {
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
  return http.request<unknown, T>(config)
}

export default http
