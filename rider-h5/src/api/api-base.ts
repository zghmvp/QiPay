export interface ResolvedApiBase {
  baseURL: string
  url: string
}

/**
 * 解析 VITE_API_BASE 与请求路径。
 *
 * 开发环境是绝对源（http://127.0.0.1:8000），交给 axios 拼到 `/api/v1/...` 上。
 * 生产环境是同域相对路径 `/api`。业务路径本身已以 `/api/` 开头，不能再拼一次，
 * 否则会变成 `/api/api/v1/...`。此时 baseURL 置空，浏览器直接请求 `/api/v1/...`，
 * 由同域反向代理转发。
 */
export function applyApiBase(apiBase: string | undefined, requestUrl: string | undefined): ResolvedApiBase {
  const url = requestUrl ?? ''
  const base = (apiBase ?? '').trim().replace(/\/+$/, '')
  if (!base || !url || /^https?:\/\//i.test(url)) {
    return { baseURL: /^https?:\/\//i.test(base) ? base : '', url }
  }
  if (/^https?:\/\//i.test(base)) {
    return { baseURL: base, url }
  }
  if (url === base || url.startsWith(`${base}/`)) {
    return { baseURL: '', url }
  }
  return { baseURL: '', url: `${base}/${url.replace(/^\/+/, '')}` }
}
