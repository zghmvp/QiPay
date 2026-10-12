#!/usr/bin/env bash
# 检查同域站点：管理端、H5 history 回落、/api 健康检查、swagger 登录被屏蔽、CSP。
# H5 的 CSP 必须单独存在，且整段策略里不能出现 unsafe-inline。
# 用法：healthcheck.sh [基址]
# 默认 http://127.0.0.1:8080 ，不访问 8000 / 5173 / 5174。
set -euo pipefail

base="${1:-${QIPAY_BASE_URL:-http://127.0.0.1:8080}}"
base="${base%/}"
fail=0
# 自签证书演练时 https 检查不能因校验失败退出。
curl_tls=()
if [[ "$base" == https:* ]]; then
  curl_tls=(-k)
fi

check() {
  local name="$1"
  local url="$2"
  local expect="$3"
  local body_file
  body_file="$(mktemp /tmp/qipay-hc-XXXXXX)"
  local code
  code="$(curl -sS "${curl_tls[@]}" -o "$body_file" -w '%{http_code}' "$url" || true)"
  if [[ "$code" != "$expect" ]]; then
    echo "失败 ${name}：${url} 状态 ${code}，期望 ${expect}" >&2
    fail=1
  else
    echo "通过 ${name}：${code} ${url}"
  fi
  if [[ "$name" == "csp" ]]; then
    :
  fi
  rm -f "$body_file"
  return 0
}

check "管理端" "${base}/" "200"
check "H5 首页" "${base}/rider-h5/" "200"
check "H5 深链" "${base}/rider-h5/login" "200"
check "接口健康检查" "${base}/api/healthz" "200"
check "边缘健康检查" "${base}/healthz" "200"
check "屏蔽 swagger 登录" "${base}/api/v1/auth/login/swagger" "404"

csp="$(curl -sSI "${curl_tls[@]}" "${base}/" | tr -d '\r' | grep -i '^content-security-policy:' || true)"
if [[ -z "${csp:-}" ]]; then
  echo "失败 CSP：响应头里没有 Content-Security-Policy" >&2
  fail=1
else
  echo "通过 CSP：${csp}"
fi

h5_csp="$(curl -sSI "${curl_tls[@]}" "${base}/rider-h5/" | tr -d '\r' | grep -i '^content-security-policy:' || true)"
if [[ -z "${h5_csp:-}" ]]; then
  echo "失败 H5 CSP：/rider-h5/ 响应头里没有 Content-Security-Policy" >&2
  fail=1
elif [[ "${h5_csp,,}" == *unsafe-inline* ]]; then
  echo "失败 H5 CSP：不应包含 unsafe-inline：${h5_csp}" >&2
  fail=1
elif [[ "${h5_csp}" != *"script-src 'self'"* ]]; then
  echo "失败 H5 CSP：script-src 不是 'self'：${h5_csp}" >&2
  fail=1
else
  echo "通过 H5 CSP：${h5_csp}"
fi

if [[ "$base" == https:* ]]; then
  h5_hsts="$(curl -sSI "${curl_tls[@]}" "${base}/rider-h5/" | tr -d '\r' | grep -i '^strict-transport-security:' || true)"
  if [[ -z "${h5_hsts:-}" || "${h5_hsts,,}" != *'max-age=15552000'* ]]; then
    echo "失败 H5 HSTS：${base}/rider-h5/ 应带 Strict-Transport-Security，实际：${h5_hsts:-无}" >&2
    fail=1
  else
    echo "通过 H5 HSTS：${h5_hsts}"
  fi
fi

h5_home="$(curl -fsS "${curl_tls[@]}" "${base}/rider-h5/")"
h5_deep="$(curl -fsS "${curl_tls[@]}" "${base}/rider-h5/login")"
if [[ "$h5_home" != "$h5_deep" ]]; then
  echo "失败 H5 history：/rider-h5/login 与首页内容不一致" >&2
  fail=1
else
  echo "通过 H5 history：深链回落到首页"
fi

swagger_body="$(curl -sS "${curl_tls[@]}" "${base}/api/v1/auth/login/swagger")"
if [[ "$swagger_body" != *'未找到'* ]]; then
  echo "失败 swagger 正文：${swagger_body}" >&2
  fail=1
else
  echo "通过 swagger 正文：未找到"
fi

if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
echo "健康检查通过 ${base}"
