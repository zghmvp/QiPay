import { request } from '@/api/http'
import type {
  CaptchaResult,
  LoginParams,
  LoginResult,
  ResetPasswordPayload,
} from '@/types'

export function getCaptcha() {
  return request<CaptchaResult>({
    url: '/api/v1/auth/captcha',
    method: 'GET',
  })
}

export function login(data: LoginParams) {
  return request<LoginResult>({
    url: '/api/v1/auth/login',
    method: 'POST',
    data,
    skipAuthRedirect: true,
  })
}

export function logout() {
  return request<unknown>({
    url: '/api/v1/auth/logout',
    method: 'POST',
    skipToast: true,
    skipAuthRedirect: true,
  })
}

export function updateMyPassword(data: ResetPasswordPayload) {
  return request<unknown>({
    url: '/api/v1/sys/users/me/password',
    method: 'PUT',
    data,
  })
}
