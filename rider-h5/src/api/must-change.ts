export const MUST_CHANGE_PASSWORD_CODE = 423
export const MUST_CHANGE_PASSWORD_ERROR = 'MUST_CHANGE_PASSWORD'
export const MUST_CHANGE_PASSWORD_MSG = '请先修改初始密码'

export function isMustChangePassword(payload: unknown): boolean {
  if (!payload || typeof payload !== 'object') return false
  const body = payload as Record<string, unknown>
  const data = body.data
  const errorCode =
    data && typeof data === 'object' ? (data as Record<string, unknown>).error_code : undefined
  if (errorCode === MUST_CHANGE_PASSWORD_ERROR) return true
  return body.code === MUST_CHANGE_PASSWORD_CODE && body.msg === MUST_CHANGE_PASSWORD_MSG
}

export function isMustChangePasswordError(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const response = (error as { response?: { data?: unknown; status?: number } }).response
  if (response?.status === MUST_CHANGE_PASSWORD_CODE && isMustChangePassword(response.data)) return true
  return isMustChangePassword(response?.data)
}
