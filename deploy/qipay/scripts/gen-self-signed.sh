#!/usr/bin/env bash
# 生成演练用自签证书。浏览器会提示不受信任，正式环境请换成机构证书。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/certs"
openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
  -keyout "$ROOT/certs/privkey.pem" \
  -out "$ROOT/certs/fullchain.pem" \
  -subj "/CN=qipay.local"
chmod 600 "$ROOT/certs/privkey.pem"
echo "已生成 ${ROOT}/certs/fullchain.pem 与 privkey.pem"
