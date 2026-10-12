# syntax=docker/dockerfile:1
# QiPay 生产后端镜像。构建上下文是 fastapi-best-architecture/，不要把宿主机 backend/.env 打进镜像。
# 框架自带镜像用 granian；本拓扑按 P4-03 使用 uvicorn 多 worker。

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/qipay \
    VIRTUAL_ENV=/opt/qipay/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/qipay/.venv \
    PATH="/opt/qipay/.venv/bin:/usr/local/bin:${PATH}" \
    UVICORN_WORKERS=2

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /uvx /usr/local/bin/

WORKDIR /opt/qipay

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group server --no-install-project

# 逐项复制，故意不复制 backend/.env（开发机配置）和 tests。运行时由编排注入环境变量。
COPY backend/__init__.py backend/main.py backend/cli.py backend/run.py backend/alembic.ini backend/README.md \
    backend/.env.example backend/.gitignore \
    /opt/qipay/backend/
COPY backend/alembic /opt/qipay/backend/alembic
COPY backend/app /opt/qipay/backend/app
COPY backend/common /opt/qipay/backend/common
COPY backend/core /opt/qipay/backend/core
COPY backend/database /opt/qipay/backend/database
COPY backend/locale /opt/qipay/backend/locale
COPY backend/middleware /opt/qipay/backend/middleware
COPY backend/plugin /opt/qipay/backend/plugin
COPY backend/sql /opt/qipay/backend/sql
COPY backend/static /opt/qipay/backend/static
COPY backend/utils /opt/qipay/backend/utils
COPY backend/scripts /opt/qipay/backend/scripts

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group server \
    && set -eu; \
    for req in /opt/qipay/backend/plugin/*/requirements.txt; do \
      [ -f "$req" ] || continue; \
      uv pip install --python /opt/qipay/.venv/bin/python -r "$req"; \
    done \
    && test ! -f /opt/qipay/backend/.env \
    && mkdir -p /opt/qipay/backend/log /opt/qipay/backend/static/upload /var/log/qipay

# 等待依赖端口后再 exec 真正的命令。Celery 额外等 RabbitMQ（QIPAY_WAIT_RABBITMQ=1）。
RUN cat > /usr/local/bin/qipay-wait <<'EOF'
#!/bin/sh
set -eu
python - <<'PY'
import os
import socket
import sys
import time


def wait(host: str, port: int, name: str) -> None:
    for _ in range(90):
        try:
            with socket.create_connection((host, port), 2):
                print(f"{name} 已就绪 {host}:{port}", flush=True)
                return
        except OSError:
            time.sleep(2)
    print(f"{name} 在 180 秒内未就绪 {host}:{port}", flush=True)
    sys.exit(1)


pairs = [
    ("DATABASE_HOST", "DATABASE_PORT", "postgres", 5432),
    ("REDIS_HOST", "REDIS_PORT", "redis", 6379),
]
if os.environ.get("QIPAY_WAIT_RABBITMQ") == "1":
    pairs.append(("CELERY_RABBITMQ_HOST", "CELERY_RABBITMQ_PORT", "rabbitmq", 5672))
for host_key, port_key, name, default_port in pairs:
    wait(os.environ.get(host_key, name), int(os.environ.get(port_key, default_port)), name)
PY
exec "$@"
EOF
RUN chmod +x /usr/local/bin/qipay-wait

# 多 worker 的 lifespan 都会调用 create_all。空库上并发建表会撞 PostgreSQL 类型唯一约束。
# 这里先由单进程建完表，再 exec 替换成 uvicorn。Celery 不走这个命令。
RUN cat > /usr/local/bin/qipay-serve <<'EOF'
#!/bin/sh
set -eu
python - <<'PY'
import asyncio

import backend  # 导入即注册全部模型，否则 create_all 建不出表
from backend.database.db import create_tables, dispose_database


async def main() -> None:
    await create_tables()
    await dispose_database()
    print("建表完成", flush=True)


asyncio.run(main())
PY
exec uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${UVICORN_WORKERS:-2}" \
    --proxy-headers \
    --forwarded-allow-ips='*' \
    --log-level info
EOF
RUN chmod +x /usr/local/bin/qipay-serve

WORKDIR /opt/qipay
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/qipay-wait"]
CMD ["/usr/local/bin/qipay-serve"]
