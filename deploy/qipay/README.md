# QiPay 生产部署

同域部署：管理端在 `/`，骑手 H5 在 `/rider-h5/`（Q-17 推荐方案），接口走 `/api` 反代到后端。这套文件都在仓库根的 `deploy/qipay/`，不改框架目录，也不改开发机的 `backend/.env`。

开发环境继续用 `scripts/start_all.sh`（8000 / 5173 / 5174）。本编排默认只占用本机 `8080`、`5433`、`6380`，不会停掉那三个端口上的进程。

## 拓扑

| 服务 | 容器 | 作用 |
|---|---|---|
| nginx | `qipay-nginx` | 托管两个前端，反代 `/api` 和 `/ws`，屏蔽 swagger 登录，加 CSP |
| backend | `qipay-backend` | uvicorn 多 worker（默认 2） |
| celery_worker | `qipay-celery` | 为 P5-01 预留的 Celery worker，现在先跑框架已有任务 |
| postgres | `qipay-postgres` | PostgreSQL 16。库名也叫 `fba`，但是容器卷里的独立实例 |
| redis | `qipay-redis` | Redis 7，无密码，只映射到本机 |
| rabbitmq | `qipay-rabbitmq` | `ENVIRONMENT=prod` 时框架把 Celery broker 固定为 RabbitMQ，所以必须有它 |

框架自带镜像用的是 granian。这里按部署要求使用 uvicorn，它已经在框架依赖里。

## 1. 准备前端静态文件

仓库里的 `www/admin/index.html` 和 `www/rider-h5/index.html` 只是中文占位页。下面按实际跑通的顺序换成构建产物。这些产物被 `.gitignore` 忽略，不要提交。

管理端用 Node 22，在 `fastapi-best-architecture-ui` 里用该仓库锁定的 pnpm。生产接口基址是 `/api`。这个前端的配置插件只从 env 文件读取 `VITE_GLOB_*`，已经存在的环境变量盖不住 `.env.production`，所以另外写一份被忽略的 `.env.production.local`，构建完立刻删掉。不要改框架的 `.env.production`。

```bash
cd fastapi-best-architecture-ui
printf '%s\n' 'VITE_GLOB_API_URL=/api' > apps/web-antdv-next/.env.production.local
VITE_GLOB_API_URL=/api pnpm --filter @vben/web-antdv-next build
rm -f apps/web-antdv-next/.env.production.local
rm -rf ../deploy/qipay/www/admin
mkdir -p ../deploy/qipay/www/admin
cp -a apps/web-antdv-next/dist/. ../deploy/qipay/www/admin/
```

构建结果里 `_app.config-*.js` 应为 `VITE_GLOB_API_URL` 等于 `/api`。

骑手 H5 的生产 `base` 已是 `/rider-h5/`，接口基址是 `/api`。在仓库根目录：

```bash
cd rider-h5
pnpm build
rm -rf ../deploy/qipay/www/rider-h5
mkdir -p ../deploy/qipay/www/rider-h5
cp -a dist/. ../deploy/qipay/www/rider-h5/
```

H5 的 history 路由由 Nginx 回落到 `/rider-h5/index.html`。管理端生产配置是 hash 路由，深链不经过服务端。

## 2. 修改口令

编辑 `env.plugin.example`（或复制成 `env.plugin` 后把 compose 的 `env_file` 指过去）：

- `TOKEN_SECRET_KEY` 换成 `openssl rand -base64 32`
- `DATABASE_PASSWORD` 与 `POSTGRES_PASSWORD` 保持一致
- `CELERY_RABBITMQ_PASSWORD` 与 `RABBITMQ_DEFAULT_PASS` 保持一致

`CORS_ALLOWED_ORIGINS` 已放行 `localhost` / `127.0.0.1` 的 `5173` 和 `5174`。`CORS_EXPOSE_HEADERS` 含 `Content-Disposition`，导出时浏览器才能读到文件名。同域页面访问 `/api` 不走 CORS。

## 3. 启动

在仓库根目录。默认 `UVICORN_WORKERS=2`。后端入口先单进程 `create_all`，再 `exec uvicorn`，空库也不会让多个 worker 同时建表：

```bash
COMPOSE_BAKE=false sudo docker compose -f deploy/qipay/docker-compose.prod.yml up -d --build
```

`COMPOSE_BAKE=false` 是为了在没有 buildx 的机器上走经典构建。装了 buildx 也可以照这个命令执行。

首次构建后端镜像会安装依赖，需要能访问镜像仓库和 PyPI。宿主机若要对外服务，启动前设置 `QIPAY_BIND=0.0.0.0`。默认只绑 `127.0.0.1`。

容器起来后，先确认连的是 compose 里的 Postgres（服务名 `postgres`，映射到宿主机 `5433`），不是开发机 `5432` 上的 `fba`。库名两边都叫 `fba`，要用主机名和 `inet_server_addr()` 区分：

```bash
sudo docker exec -i qipay-backend python - <<'PY'
import asyncio
import os

from sqlalchemy import text

from backend.database.db import async_engine, dispose_database


async def main() -> None:
    print("DATABASE_HOST", os.environ.get("DATABASE_HOST"))
    print("DATABASE_PORT", os.environ.get("DATABASE_PORT"))
    async with async_engine.connect() as conn:
        row = (
            await conn.execute(
                text("select current_database(), inet_server_addr()::text, inet_server_port()")
            )
        ).one()
    print("current_database", row[0])
    print("inet_server_addr", row[1])
    print("inet_server_port", row[2])
    await dispose_database()


asyncio.run(main())
PY
```

期望看到 `DATABASE_HOST postgres`，`current_database fba`，`inet_server_addr` 是容器网段地址。开发库是 `127.0.0.1:5432`。对不上就停，不要执行下面的初始化。

确认之后，**只在容器自己的库**里初始化一次。这会清空那个库里的表：

```bash
printf 'y\n' | sudo docker compose -f deploy/qipay/docker-compose.prod.yml exec -T backend fba init
```

`fba init` 会重建表，并执行框架的 `init_test_data.sql` 和各插件 `init.sql`。管理端种子管理员是 `admin` / `123456`。

登录验证码在 compose 的 Redis 里，不要读开发机 `6379`。经 Nginx `8080` 拿 token：

```bash
CAPTCHA=$(curl -sS http://127.0.0.1:8080/api/v1/auth/captcha)
UUID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["uuid"])' <<<"$CAPTCHA")
CODE=$(sudo docker exec qipay-redis redis-cli GET "fba:login:captcha:$UUID")
curl -sS -X POST http://127.0.0.1:8080/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"123456\",\"uuid\":\"$UUID\",\"captcha\":\"$CODE\"}"
```

首页、插件页的 JS/CSS，以及 `/rider-h5/login` 和它的资源，都应返回 200。

## 4. 验收

```bash
bash deploy/qipay/scripts/healthcheck.sh http://127.0.0.1:8080
```

脚本会检查：

- `/` 管理端返回 200
- `/rider-h5/` 和 `/rider-h5/login` 都返回 200，且深链内容与首页相同（history 回落）
- `/api/healthz` 反代到后端 `/metrics`（`ENVIRONMENT=prod` 才会挂这个路径）
- `/api/v1/auth/login/swagger` 返回 404，正文是「未找到」
- 响应头里有 `Content-Security-Policy`
- `/rider-h5/` 的 CSP 单独更严：`script-src 'self'`，整段策略不含 `unsafe-inline`

手工抽查：

```bash
curl -sI http://127.0.0.1:8080/ | head
curl -sI http://127.0.0.1:8080/rider-h5/ | grep -i content-security-policy
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/v1/auth/login/swagger
```

## 5. TLS

```bash
bash deploy/qipay/scripts/gen-self-signed.sh
```

然后在 `docker-compose.prod.yml` 里把 Nginx 配置换成 `nginx/qipay.tls.conf`，挂上 `./certs:/etc/qipay/certs:ro`，并打开 `8443:443` 的端口注释。自签证书只适合演练。正式证书换成 `certs/fullchain.pem` 和 `certs/privkey.pem`。80 端口会 301 到 HTTPS。HTTPS 的 `/` 和 `/rider-h5/` 都带 `Strict-Transport-Security`（H5 的 location 不继承 server 级响应头，所以 HSTS 走 `$qipay_hsts`，写在共用安全头里）。HTTP 模式把这个变量设为空串，不输出该头。

## 6. 备份与恢复

每天备份（读的是 compose 映射的 5433，不是开发库 5432）：

```bash
# /etc/cron.d/qipay 或 crontab
15 3 * * * root cd /opt/qipay && bash deploy/qipay/scripts/backup.sh >> /var/log/qipay/backup/backup.log 2>&1
```

备份是自定义格式，写到 `deploy/qipay/backups/`，默认保留 14 天，并带 sha256。

恢复：

```bash
export PGHOST=127.0.0.1 PGPORT=5433 PGUSER=qipay PGPASSWORD='你的口令'
bash deploy/qipay/scripts/restore.sh deploy/qipay/backups/qipay-fba-时间戳.dump 目标库名
```

规则：

- 目标库名是 `fba` 且端口是 `5432`：直接拒绝（开发库）
- 目标库名是 `fba` 但端口不是 5432：必须再设置 `QIPAY_ALLOW_FBA=yes`
- 执行前会打印 `current_database()`，连错库会退出

演练（在临时库 `qipay_p403_src` / `qipay_p403_dst` 上做一遍备份和恢复，结束删除）：

```bash
PGHOST=127.0.0.1 PGPORT=5432 PGUSER=root PGPASSWORD=postgres \
  bash deploy/qipay/scripts/restore-drill.sh
```

## 7. 日志轮转

- 容器标准输出：compose 使用 json-file，单文件 20MB，保留 5 个
- 挂到宿主机的文件日志：把 `QIPAY_LOG_DIR` 设为 `/var/log/qipay`，然后

```bash
sudo mkdir -p /var/log/qipay/nginx /var/log/qipay/backend /var/log/qipay/celery /var/log/qipay/backup
sudo cp deploy/qipay/logrotate/qipay /etc/logrotate.d/qipay
sudo logrotate -d /etc/logrotate.d/qipay
```

## 8. 健康检查

| 对象 | 方式 |
|---|---|
| Postgres | `pg_isready` |
| Redis | `redis-cli ping` |
| RabbitMQ | `rabbitmq-diagnostics ping` |
| 后端 | 容器内 `curl http://127.0.0.1:8000/metrics/` |
| Nginx | `wget http://127.0.0.1/healthz` |
| 对外 | `scripts/healthcheck.sh` |

`/api/v1/auth/captcha` 有每 30 秒 5 次的限流，不要拿它当探针。

## 9. 安全相关

- `/api/v1/auth/login/swagger` 在 Nginx 层返回 404，请求到不了后端（P3-03）
- CSP、`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy` 加在站点响应上（P3-12）
- `/rider-h5/` 单独使用 `nginx/snippets/security-headers-h5.conf`：`script-src 'self'`、`style-src 'self'`，没有 `'unsafe-inline'`。H5 生产包的 `index.html` 只有外链脚本和样式。Vant 图标字体的 `at.alicdn.com` woff 回退在构建时去掉，只留内嵌 woff2，所以 `font-src` 不用放行外站。源码里禁止 `v-html`，守护用例在 `rider-h5/tests/no-v-html.test.ts`，出现 `v-html` 时测试失败
- 管理端（`/`）的 `script-src` 和 `style-src` 仍带 `'unsafe-inline'`，收不紧。框架构建插件 `fastapi-best-architecture-ui/internal/vite-config/src/plugins/inject-app-loading/index.ts` 会注入一段读 localStorage 主题的内联脚本，`default-loading.html` 还会注入内联 `<style>`。这两处都在框架目录，本条不改。脚本正文嵌了包版本号，用 hash 钉在 Nginx 里的话，管理端一升级版本就要改配置，漏改就是白屏
- 访问令牌有效期在 `env.plugin.example` 的 `TOKEN_EXPIRE_SECONDS=28800`（8 小时）。框架默认是 86400（1 天）。H5 把 access token 放在 localStorage，不调用刷新接口（纲要 §10 #24），缩短有效期是为了缩小被窃取后的可用窗口。这个参数是全局的，管理端的 access token 一起变短。管理端登录后还有 httpOnly refresh cookie，过期后会请求 `/api/v1/auth/refresh` 静默换新，刷新令牌仍是框架默认 7 天，正常操作不会被踢下线。H5 不读这个 cookie，8 小时后 401，要重新登录。再短到 2 小时窗口更小，但骑手一个班次要登多次，验证码还有大约 5 次/30 秒的限流。不要在模板里改 `TOKEN_REFRESH_EXPIRE_SECONDS`，那只缩短管理端免登录时长，帮不到 H5
- 把 H5 的 access token 改存 httpOnly Cookie 需要框架改登录响应和 JWT 校验（FW-04），本条不做。H5 仍按纲要把 token 放在 localStorage。现有缓解是：`/rider-h5/` 禁止内联脚本、缩短 access token、源码禁止 `v-html`
- `ENVIRONMENT=prod` 后框架自己会关掉 `/docs` 和 `/openapi`
- Redis 和 Postgres 默认只绑在 `127.0.0.1`。RabbitMQ 不映射到宿主机

## 10. 停机

```bash
sudo docker compose -f deploy/qipay/docker-compose.prod.yml down
```

数据在命名卷 `qipay_pg` 里。`down -v` 会删掉这个卷，生产上不要加 `-v`。

## 11. 已知限制

- 框架在 `ENVIRONMENT=prod` 时把 Celery broker 固定为 RabbitMQ，所以编排里有 RabbitMQ。不能只靠 Redis 把这个开关改回去。
- 空库建表由 `/usr/local/bin/qipay-serve` 单进程先做完，再 `exec uvicorn --workers`。`UVICORN_WORKERS=2` 时两个 worker 都会打出 `Application startup complete`，日志里不应再出现 `UniqueViolation`。
- `/metrics` 不带斜杠会 307 到 `/metrics/`。健康检查和 `/api/healthz` 都请求带斜杠的地址。
- `www/` 里入库的只有中文占位页。不拷入构建产物时，页面能打开，但不是业务界面。
- `ENVIRONMENT=prod` 会向 `127.0.0.1:4317` 导出 OpenTelemetry。编排里没有收集器，日志里会有导出失败，不影响接口。
- Celery worker 目前以 root 跑在容器里，和框架自带镜像一样。P5-01 落地算薪任务前，它只消费框架已有任务。
