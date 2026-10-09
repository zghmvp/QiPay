export const RIDER_ONLY_MSG = '仅骑手可用'
export const READ_GRACE_EXPIRED_HINT = '查阅期限'

/** 离职超过只读宽限期。不能当成「仅骑手可用」。 */
export function isReadGraceExpiredMessage(msg: unknown): boolean {
  return typeof msg === 'string' && msg.includes(READ_GRACE_EXPIRED_HINT)
}

/** 判断请求是否打到骑手资料接口，忽略查询串和末尾斜杠。 */
export function isMeProfileUrl(url: string | undefined): boolean {
  if (!url) return false
  const path = url.split(/[?#]/, 1)[0] ?? ''
  return /\/rider-salary\/me\/profile\/?$/.test(path)
}

/**
 * 资料接口返回 403 时，管理员等非骑手账号需要明确中文说明。
 * 423 / MUST_CHANGE_PASSWORD 不是这类拒绝，不能在这里命中。
 */
export function isRiderOnlyResponse(input: {
  status?: number
  code?: number
  url?: string
  msg?: string
}): boolean {
  if (!isMeProfileUrl(input.url)) return false
  if (input.status !== 403 && input.code !== 403) return false
  if (isReadGraceExpiredMessage(input.msg)) return false
  return true
}

export function isRiderOnlyError(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const err = error as {
    riderOnly?: boolean
    response?: { status?: number; data?: { code?: unknown; msg?: unknown } }
    config?: { url?: string }
  }
  if (err.riderOnly === true) return true
  const data = err.response?.data
  const code = data?.code
  const msg = data?.msg
  return isRiderOnlyResponse({
    status: err.response?.status,
    code: typeof code === 'number' ? code : undefined,
    url: err.config?.url,
    msg: typeof msg === 'string' ? msg : undefined,
  })
}
